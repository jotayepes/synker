"""Backup, restore and sync logic shared by the CLI, the daemon, the GUI and the Decky plugin."""

from __future__ import annotations

import logging
import platform
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from synker import archive, paths, retention
from synker.archive import ArchivedFile
from synker.config import Config
from synker.detect.scanner import Game, SaveFile
from synker.repository import CONFLICT_COPY, BackupEntry, GameIndex, Repository, new_backup_id
from synker.state import DeviceState, HashCache, content_hash
from synker.storage import Storage, StorageError, open_storage

log = logging.getLogger(__name__)

SNAPSHOTS_KEPT = 5

# Sync states
SYNCED = "synced"
LOCAL_NEWER = "local-newer"
REMOTE_NEWER = "remote-newer"
CONFLICT = "conflict"
LOCAL_ONLY = "local-only"
REMOTE_ONLY = "remote-only"
EMPTY = "empty"
OFFLINE = "offline"


def os_name() -> str:
    return platform.system().lower() or "unknown"


@dataclass
class LocalSet:
    files: list[SaveFile]
    digests: list[str]
    hash: str | None
    size: int


class Engine:
    def __init__(self, cfg: Config, storage: Storage | None = None, state: DeviceState | None = None,
                 hashes: HashCache | None = None):
        self.cfg = cfg
        self._storage = storage
        self.state = state or DeviceState()
        self.hashes = hashes or HashCache()
        self.queue_dir = paths.data_dir() / "queue"
        self.snapshot_dir = paths.data_dir() / "snapshots"

    # -- storage -----------------------------------------------------------

    def storage(self) -> Storage:
        if self._storage is None:
            self._storage = open_storage(self.cfg)
        return self._storage

    def repo(self) -> Repository:
        return Repository(self.storage())

    def close(self) -> None:
        if self._storage is not None:
            self._storage.close()
            self._storage = None
        self.hashes.flush()

    # -- local side --------------------------------------------------------

    def local_set(self, game: Game, refresh: bool = True) -> LocalSet:
        files = game.find_files(refresh=refresh)
        digests = [self.hashes.sha256(f.path, f.size, f.mtime) for f in files]
        self.hashes.flush()
        h = content_hash([(f.portable, d) for f, d in zip(files, digests, strict=True)]) if files else None
        return LocalSet(files, digests, h, sum(f.size for f in files))

    def _build_archive(self, game: Game, local: LocalSet, dest: Path, entry: BackupEntry) -> None:
        used: set[str] = set()
        items = [(f.path, ArchivedFile(f.portable, f.kind, d, f.size, f.mtime, archive.member_name(f.portable, used)))
                 for f, d in zip(local.files, local.digests, strict=True)]
        archive.write_archive(dest, {"game": {"id": game.id, "title": game.title}, "backup": entry.to_dict()}, items)

    def _entry(self, local: LocalSet, reason: str) -> BackupEntry:
        backup_id = new_backup_id(self.cfg.device_name)
        return BackupEntry(id=backup_id, file=f"{backup_id}.zip", created=time.time(), device=self.cfg.device_name,
                           os=os_name(), reason=reason, hash=local.hash or "", size=local.size,
                           files=len(local.files))

    # -- status ------------------------------------------------------------

    def _index(self, game: Game) -> GameIndex:
        return self.repo().load_index(game.id)

    @staticmethod
    def classify(local_hash: str | None, latest: BackupEntry | None, last_hash: str | None) -> str:
        if latest is None:
            return LOCAL_ONLY if local_hash else EMPTY
        if local_hash is None:
            return REMOTE_ONLY
        if local_hash == latest.hash:
            return SYNCED
        if last_hash is not None and local_hash == last_hash:
            return REMOTE_NEWER
        if last_hash is not None and latest.hash == last_hash:
            return LOCAL_NEWER
        return CONFLICT

    def status(self, game: Game, local: LocalSet | None = None) -> dict[str, Any]:
        local = local or self.local_set(game)
        last = self.state.get(game.id) or {}
        result: dict[str, Any] = {
            "game": game.to_dict(),
            "local_hash": local.hash,
            "local_files": len(local.files),
            "local_size": local.size,
            "last_synced": last.get("backup_id"),
            "queued": len(self._queued(game.id)),
        }
        try:
            latest = self._index(game).latest()
        except StorageError as exc:
            result.update(state=OFFLINE, error=str(exc), latest=None)
            return result
        result["latest"] = latest.to_dict() if latest else None
        result["state"] = self.classify(local.hash, latest, last.get("hash"))
        return result

    # -- backup ------------------------------------------------------------

    def backup(self, game: Game, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        local = self.local_set(game)
        if not local.files:
            return {"game_id": game.id, "action": "no-files"}
        self.flush_queue()
        for queued in self._queued(game.id):
            if queued["entry"]["hash"] == local.hash and not force:
                return {"game_id": game.id, "action": "unchanged", "queued": True}

        entry = self._entry(local, reason)
        try:
            index = self._index(game)
            latest = index.latest()
            if latest and latest.hash == local.hash and not force and reason != CONFLICT_COPY:
                self.state.set(game.id, latest.id, latest.hash)
                return {"game_id": game.id, "action": "unchanged", "backup": latest.to_dict()}
        except StorageError as exc:
            return self._queue(game, local, entry, str(exc))

        with tempfile.TemporaryDirectory(prefix="synker-") as tmp:
            zip_path = Path(tmp) / entry.file
            self._build_archive(game, local, zip_path, entry)
            try:
                self.repo().add(game.id, game.title, entry, zip_path)
            except StorageError as exc:
                return self._queue(game, local, entry, str(exc), zip_path)
        self._after_upload(game.id, entry)
        return {"game_id": game.id, "action": "created", "backup": entry.to_dict()}

    def _after_upload(self, game_id: str, entry: BackupEntry) -> None:
        if entry.reason != CONFLICT_COPY:
            self.state.set(game_id, entry.id, entry.hash)
            try:
                self.repo().update_device(self.cfg.device_name, os_name(), game_id, entry.id, entry.hash)
            except StorageError as exc:
                log.warning("could not update device record: %s", exc)
        self.apply_retention(game_id)

    def apply_retention(self, game_id: str) -> list[str]:
        repo = self.repo()
        index = repo.load_index(game_id)
        doomed = retention.select_for_deletion(index.backups, self.cfg.backup.keep_last,
                                               self.cfg.backup.keep_daily_days)
        repo.delete(game_id, doomed)
        return [b.id for b in doomed]

    # -- offline queue -----------------------------------------------------

    def _queued(self, game_id: str) -> list[dict[str, Any]]:
        import json

        folder = self.queue_dir / game_id
        out = []
        for meta in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                out.append(json.loads(meta.read_text("utf-8")))
            except (OSError, ValueError):
                continue
        return out

    def _queue(self, game: Game, local: LocalSet, entry: BackupEntry, error: str,
               built: Path | None = None) -> dict[str, Any]:
        import json

        folder = self.queue_dir / game.id
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / entry.file
        if built and built.exists():
            shutil.copy2(built, dest)
        else:
            self._build_archive(game, local, dest, entry)
        (folder / f"{entry.id}.json").write_text(
            json.dumps({"title": game.title, "entry": entry.to_dict()}), "utf-8")
        # Remember it locally so the next status check does not report a conflict.
        if entry.reason != CONFLICT_COPY:
            self.state.set(game.id, entry.id, entry.hash)
        log.warning("storage unavailable (%s); backup of %s queued", error, game.id)
        return {"game_id": game.id, "action": "queued", "error": error, "backup": entry.to_dict()}

    def flush_queue(self) -> dict[str, Any]:
        uploaded, failed = [], []
        if not self.queue_dir.is_dir():
            return {"uploaded": uploaded, "failed": failed}
        for folder in sorted(p for p in self.queue_dir.iterdir() if p.is_dir()):
            for item in self._queued(folder.name):
                entry = BackupEntry.from_dict(item["entry"])
                zip_path = folder / entry.file
                try:
                    self.repo().add(folder.name, item.get("title", ""), entry, zip_path)
                except StorageError as exc:
                    failed.append({"game_id": folder.name, "backup_id": entry.id, "error": str(exc)})
                    return {"uploaded": uploaded, "failed": failed}
                zip_path.unlink(missing_ok=True)
                (folder / f"{entry.id}.json").unlink(missing_ok=True)
                self._after_upload(folder.name, entry)
                uploaded.append({"game_id": folder.name, "backup_id": entry.id})
            if not any(folder.iterdir()):
                folder.rmdir()
        return {"uploaded": uploaded, "failed": failed}

    # -- restore -----------------------------------------------------------

    def list_backups(self, game_id: str) -> list[dict[str, Any]]:
        return [b.to_dict() for b in self.repo().load_index(game_id).sorted()]

    def snapshot_local(self, game: Game, local: LocalSet | None = None) -> Path | None:
        """Keep a local copy of the current saves before overwriting them."""
        local = local or self.local_set(game)
        if not local.files:
            return None
        entry = self._entry(local, "pre-restore")
        folder = self.snapshot_dir / game.id
        dest = folder / entry.file
        self._build_archive(game, local, dest, entry)
        for old in sorted(folder.glob("*.zip"), reverse=True)[SNAPSHOTS_KEPT:]:
            old.unlink(missing_ok=True)
        return dest

    def restore(self, game: Game, backup_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        index = self._index(game)
        entry = index.get(backup_id) if backup_id else index.latest()
        if not entry:
            raise LookupError(f"no backup {backup_id or ''} found for {game.id}".replace("  ", " "))
        with tempfile.TemporaryDirectory(prefix="synker-") as tmp:
            zip_path = Path(tmp) / entry.file
            self.storage().download(self.repo().archive_path(game.id, entry), zip_path)
            result = self.restore_archive(game, zip_path, dry_run=dry_run)
        result["backup"] = entry.to_dict()
        if not dry_run and not result["unresolved"]:
            self.state.set(game.id, entry.id, entry.hash)
            try:
                self.repo().update_device(self.cfg.device_name, os_name(), game.id, entry.id, entry.hash)
            except StorageError:
                pass
        return result

    def restore_archive(self, game: Game, zip_path: Path, dry_run: bool = False) -> dict[str, Any]:
        _meta, files = archive.read_meta(zip_path)
        plan: list[tuple[ArchivedFile, Path]] = []
        unresolved: list[str] = []
        for f in files:
            target = game.target_for(f.portable, f.kind)
            if target is None:
                unresolved.append(f.portable)
            else:
                plan.append((f, target))
        if files and not plan:
            raise RuntimeError(
                f"none of the {len(files)} files of this backup can be placed on this machine "
                f"(for Proton games, launch the game once so its prefix exists)")
        snapshot = None
        if not dry_run:
            snapshot = self.snapshot_local(game)
            for f, target in plan:
                archive.extract_member(zip_path, f.member, target, f.mtime)
        return {
            "game_id": game.id,
            "action": "dry-run" if dry_run else "restored",
            "files": [{"portable": f.portable, "target": str(t)} for f, t in plan],
            "unresolved": unresolved,
            "snapshot": str(snapshot) if snapshot else None,
        }

    def undo_restore(self, game: Game) -> dict[str, Any]:
        snaps = sorted((self.snapshot_dir / game.id).glob("*.zip"), reverse=True)
        if not snaps:
            raise LookupError(f"no local snapshot for {game.id}")
        latest = snaps[0]
        result = self.restore_archive(game, latest)
        latest.unlink(missing_ok=True)
        return result

    # -- automation hooks --------------------------------------------------

    def pre_launch(self, game: Game, policy: str | None = None) -> dict[str, Any]:
        """Called right before (or as) a game starts: pull newer saves from the NAS."""
        policy = policy or self.cfg.backup.conflict_policy
        local = self.local_set(game)
        status = self.status(game, local)
        state = status["state"]
        result = {"game_id": game.id, "state": state, "action": "none"}
        if state in (REMOTE_NEWER, REMOTE_ONLY):
            if self.cfg.backup.auto_restore:
                result.update(action="restored", restore=self.restore(game))
            else:
                result["action"] = "restore-available"
        elif state == CONFLICT:
            if policy == "prefer-remote":
                result.update(action="restored", restore=self.restore(game))
            elif policy == "keep-both":
                result["conflict_copy"] = self.backup(game, reason=CONFLICT_COPY, force=True)
                result.update(action="restored", restore=self.restore(game))
            elif policy == "prefer-local":
                result["action"] = "kept-local"
            else:
                result["action"] = "ask"
        return result

    def post_exit(self, game: Game, reason: str = "exit") -> dict[str, Any]:
        """Called when a game closes (or periodically while it runs).

        If this device never synced the game and its saves differ from the NAS
        (typically a fresh save created on first launch, before the restore
        could happen), the backup is stored as a conflict copy so it does not
        replace the real progress as the latest version.
        """
        local = self.local_set(game)
        last = self.state.get(game.id)
        if last is None and local.hash:
            try:
                latest = self._index(game).latest()
            except StorageError:
                latest = None
            if latest and latest.hash != local.hash:
                result = self.backup(game, reason=CONFLICT_COPY)
                result["state"] = CONFLICT
                return result
        return self.backup(game, reason=reason)
