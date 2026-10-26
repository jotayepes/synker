"""Storage of the SMB password.

Lookup order: the SYNKER_SMB_PASSWORD environment variable, then the OS
keyring (if the optional `keyring` package works), then a 0600 file in the
config directory. The Decky plugin always ends up on the file because no
keyring daemon is reachable from the plugin loader.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from synker import paths

SERVICE = "synker"
SECRETS_FILE = "secrets.json"


def _keyring():
    if os.environ.get("SYNKER_NO_KEYRING"):
        return None
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _file() -> Path:
    return paths.config_dir() / SECRETS_FILE


def _read_file() -> dict[str, str]:
    try:
        return json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write_file(data: dict[str, str]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def get_password(account: str) -> str | None:
    env = os.environ.get("SYNKER_SMB_PASSWORD")
    if env is not None:
        return env
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, account)
            if value is not None:
                return value
        except Exception:
            pass
    return _read_file().get(account)


def set_password(account: str, password: str) -> str:
    """Store the password and return where it was stored ("keyring" or "file")."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, account, password)
            return "keyring"
        except Exception:
            pass
    data = _read_file()
    data[account] = password
    _write_file(data)
    return "file"


def smb_account(host: str, username: str) -> str:
    return f"smb://{username}@{host}"
