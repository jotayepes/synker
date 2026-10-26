"""SMB2/3 network share via the pure-Python `smbprotocol` client (no mounting, no root)."""

from __future__ import annotations

import shutil
from typing import BinaryIO

from synker.config import SmbConfig
from synker.storage.base import Storage, StorageError


class SmbStorage(Storage):
    name = "smb"

    def __init__(self, cfg: SmbConfig, password: str | None, timeout: int = 15):
        if not cfg.host or not cfg.share:
            raise StorageError("SMB host and share must be configured")
        try:
            import smbclient
            from smbprotocol.exceptions import SMBException
        except ImportError as exc:  # pragma: no cover
            raise StorageError("the 'smbprotocol' package is not installed") from exc
        self._smb = smbclient
        self._exc = (SMBException, OSError)
        self.cfg = cfg
        self.base = f"\\\\{cfg.host}\\{cfg.share}"
        sub = cfg.path.strip("/\\").replace("/", "\\")
        if sub:
            self.base += "\\" + sub
        username = cfg.username or None
        if username and cfg.domain:
            username = f"{cfg.domain}\\{username}"
        try:
            smbclient.register_session(cfg.host, username=username, password=password, port=cfg.port,
                                       encrypt=cfg.encrypt or None, connection_timeout=timeout)
        except self._exc as exc:
            raise StorageError(f"cannot connect to {cfg.host}: {exc}") from exc
        self._username = username

    def describe(self) -> str:
        return "smb:" + self.base.replace("\\", "/")

    def _p(self, path: str) -> str:
        parts = [p for p in path.split("/") if p]
        if any(p == ".." for p in parts):
            raise StorageError(f"invalid path {path!r}")
        return "\\".join([self.base] + parts)

    def exists(self, path: str) -> bool:
        try:
            return self._smb.path.exists(self._p(path))
        except self._exc as exc:
            raise StorageError(str(exc)) from exc

    def list(self, path: str) -> list[str]:
        try:
            return sorted(self._smb.listdir(self._p(path)))
        except FileNotFoundError:
            return []
        except self._exc as exc:
            raise StorageError(str(exc)) from exc

    def open_read(self, path: str) -> BinaryIO:
        try:
            return self._smb.open_file(self._p(path), mode="rb")
        except FileNotFoundError as exc:
            raise StorageError(f"not found: {path}") from exc
        except self._exc as exc:
            raise StorageError(str(exc)) from exc

    def _write_stream(self, path: str, src: BinaryIO) -> None:
        target = self._p(path)
        parent = target.rsplit("\\", 1)[0]
        tmp = target + ".part"
        try:
            self._smb.makedirs(parent, exist_ok=True)
            with self._smb.open_file(tmp, mode="wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            self._smb.replace(tmp, target)
        except self._exc as exc:
            raise StorageError(f"cannot write {path}: {exc}") from exc

    def delete(self, path: str) -> None:
        target = self._p(path)
        try:
            if self._smb.path.isdir(target):
                for name in self._smb.listdir(target):
                    self.delete(f"{path}/{name}")
                self._smb.rmdir(target)
            elif self._smb.path.exists(target):
                self._smb.remove(target)
        except self._exc as exc:
            raise StorageError(f"cannot delete {path}: {exc}") from exc

    def close(self) -> None:
        try:
            self._smb.delete_session(self.cfg.host, port=self.cfg.port)
        except Exception:
            pass
