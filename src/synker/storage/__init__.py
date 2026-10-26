"""Backup storage backends."""

from __future__ import annotations

from synker import secrets
from synker.config import Config
from synker.storage.base import Storage, StorageError
from synker.storage.local import LocalStorage

__all__ = ["Storage", "StorageError", "LocalStorage", "open_storage"]


def open_storage(cfg: Config) -> Storage:
    if cfg.storage.type == "smb":
        from synker.storage.smb import SmbStorage

        smb = cfg.storage.smb
        password = secrets.get_password(secrets.smb_account(smb.host, smb.username))
        return SmbStorage(smb, password)
    return LocalStorage(cfg.storage.path)
