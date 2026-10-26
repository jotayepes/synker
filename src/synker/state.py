"""Per-device local state: what was last synced for each game, plus a file hash cache."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from synker import paths

_lock = threading.RLock()


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, path)


class DeviceState:
    """Remembers, per game, the backup this device last backed up or restored."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.data_dir() / "state.json"

    def get(self, game_id: str) -> dict[str, Any] | None:
        with _lock:
            return _load(self.path).get("games", {}).get(game_id)

    def set(self, game_id: str, backup_id: str, content_hash: str) -> None:
        with _lock:
            data = _load(self.path)
            data.setdefault("games", {})[game_id] = {"backup_id": backup_id, "hash": content_hash}
            _save(self.path, data)

    def all(self) -> dict[str, Any]:
        with _lock:
            return _load(self.path).get("games", {})


class HashCache:
    """sha256 of files keyed by (path, size, mtime) so unchanged saves are not re-read."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.cache_dir() / "hashes.json"
        self._data: dict[str, list] | None = None
        self._dirty = False

    def _entries(self) -> dict[str, list]:
        if self._data is None:
            self._data = _load(self.path)
        return self._data

    def sha256(self, file: Path, size: int, mtime: float) -> str:
        key = str(file)
        entry = self._entries().get(key)
        if entry and entry[0] == size and entry[1] == mtime:
            return entry[2]
        digest = file_sha256(file)
        self._entries()[key] = [size, mtime, digest]
        self._dirty = True
        return digest

    def flush(self) -> None:
        if self._dirty and self._data is not None:
            with _lock:
                _save(self.path, self._data)
            self._dirty = False


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def content_hash(items: list[tuple[str, str]]) -> str:
    """Hash of a save set from sorted (portable path, file sha256) pairs."""
    h = hashlib.sha256()
    for portable, digest in sorted(items):
        h.update(f"{portable}\0{digest}\n".encode())
    return h.hexdigest()
