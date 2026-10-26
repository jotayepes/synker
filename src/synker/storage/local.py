"""A plain folder. Also works for NAS shares already mounted (NFS, CIFS, GVFS...)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO

from synker.storage.base import Storage, StorageError


class LocalStorage(Storage):
    name = "local"

    def __init__(self, root: str | Path):
        if not root:
            raise StorageError("no backup folder configured")
        self.root = Path(root).expanduser()

    def describe(self) -> str:
        return str(self.root)

    def _p(self, path: str) -> Path:
        parts = [p for p in path.split("/") if p]
        if any(p == ".." for p in parts):
            raise StorageError(f"invalid path {path!r}")
        return self.root.joinpath(*parts)

    def exists(self, path: str) -> bool:
        return self._p(path).exists()

    def list(self, path: str) -> list[str]:
        try:
            return sorted(os.listdir(self._p(path)))
        except FileNotFoundError:
            return []

    def open_read(self, path: str) -> BinaryIO:
        try:
            return self._p(path).open("rb")
        except FileNotFoundError as exc:
            raise StorageError(f"not found: {path}") from exc

    def _write_stream(self, path: str, src: BinaryIO) -> None:
        target = self._p(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            with tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            os.replace(tmp, target)
        except OSError as exc:
            raise StorageError(f"cannot write {target}: {exc}") from exc

    def delete(self, path: str) -> None:
        target = self._p(path)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
