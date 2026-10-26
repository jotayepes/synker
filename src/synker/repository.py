"""Layout of backups inside a storage backend.

    synker/games/<game-id>/index.json            list of backups
    synker/games/<game-id>/<backup-id>.zip       one backup (files + meta.json)
    synker/devices/<device>.json                 what each device last synced
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from synker.storage.base import Storage

ROOT = "synker"
CONFLICT_COPY = "conflict-copy"


@dataclass
class BackupEntry:
    id: str
    file: str
    created: float
    device: str
    os: str
    reason: str
    hash: str
    size: int
    files: int
    locked: bool = False
    comment: str = ""

    @property
    def created_iso(self) -> str:
        return datetime.fromtimestamp(self.created, UTC).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_iso"] = self.created_iso
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BackupEntry:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class GameIndex:
    game_id: str
    title: str = ""
    backups: list[BackupEntry] = field(default_factory=list)

    def sorted(self) -> list[BackupEntry]:
        return sorted(self.backups, key=lambda b: b.created, reverse=True)

    def latest(self) -> BackupEntry | None:
        """Newest backup that represents the game's current state (conflict copies excluded)."""
        return next((b for b in self.sorted() if b.reason != CONFLICT_COPY), None)

    def get(self, backup_id: str) -> BackupEntry | None:
        return next((b for b in self.backups if b.id == backup_id), None)


def new_backup_id(device: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in device)[:40] or "device"
    return f"{stamp}-{safe}"


class Repository:
    def __init__(self, storage: Storage):
        self.storage = storage

    def _game_dir(self, game_id: str) -> str:
        return f"{ROOT}/games/{game_id}"

    def game_ids(self) -> list[str]:
        return self.storage.list(f"{ROOT}/games")

    def load_index(self, game_id: str) -> GameIndex:
        data = self.storage.read_json(f"{self._game_dir(game_id)}/index.json") or {}
        return GameIndex(game_id, data.get("title", ""),
                         [BackupEntry.from_dict(b) for b in data.get("backups", [])])

    def save_index(self, index: GameIndex) -> None:
        self.storage.write_json(f"{self._game_dir(index.game_id)}/index.json", {
            "game_id": index.game_id,
            "title": index.title,
            "backups": [asdict(b) for b in index.sorted()],
        })

    def archive_path(self, game_id: str, entry: BackupEntry) -> str:
        return f"{self._game_dir(game_id)}/{entry.file}"

    def add(self, game_id: str, title: str, entry: BackupEntry, archive_local_path) -> GameIndex:
        self.storage.upload(archive_local_path, self.archive_path(game_id, entry))
        index = self.load_index(game_id)
        index.title = title or index.title
        index.backups = [b for b in index.backups if b.id != entry.id] + [entry]
        self.save_index(index)
        return index

    def delete(self, game_id: str, entries: list[BackupEntry]) -> None:
        if not entries:
            return
        index = self.load_index(game_id)
        drop = {e.id for e in entries}
        for e in entries:
            self.storage.delete(self.archive_path(game_id, e))
        index.backups = [b for b in index.backups if b.id not in drop]
        self.save_index(index)

    def set_locked(self, game_id: str, backup_id: str, locked: bool) -> BackupEntry:
        index = self.load_index(game_id)
        entry = index.get(backup_id)
        if not entry:
            raise KeyError(backup_id)
        entry.locked = locked
        self.save_index(index)
        return entry

    def update_device(self, device: str, os_name: str, game_id: str, backup_id: str, content_hash: str) -> None:
        path = f"{ROOT}/devices/{device}.json"
        data = self.storage.read_json(path) or {"device": device, "games": {}}
        data.update({"os": os_name, "updated": time.time()})
        data.setdefault("games", {})[game_id] = {"backup_id": backup_id, "hash": content_hash}
        self.storage.write_json(path, data)
