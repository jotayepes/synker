"""User configuration, stored as TOML in the config directory."""

from __future__ import annotations

import socket
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import tomli_w

from synker import paths

CONFIG_FILE = "config.toml"
CONFLICT_POLICIES = ("ask", "prefer-remote", "prefer-local", "keep-both")
STORAGE_TYPES = ("local", "smb")


@dataclass
class SmbConfig:
    host: str = ""
    share: str = ""
    path: str = "synker"
    username: str = ""
    domain: str = ""
    port: int = 445
    encrypt: bool = False


@dataclass
class StorageConfig:
    type: str = "local"
    # Folder used by the "local" storage type (can be a mounted NAS share).
    path: str = ""
    smb: SmbConfig = field(default_factory=SmbConfig)


@dataclass
class BackupConfig:
    keep_last: int = 10
    keep_daily_days: int = 30
    periodic_minutes: int = 15
    include_cloud_games: bool = False
    auto_restore: bool = True
    conflict_policy: str = "ask"
    backup_on_exit: bool = True


@dataclass
class CustomGame:
    name: str
    paths: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)


@dataclass
class Config:
    device_name: str = field(default_factory=socket.gethostname)
    storage: StorageConfig = field(default_factory=StorageConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    # Extra Steam installs (folders containing steamapps/) and Wine prefixes.
    steam_roots: list[str] = field(default_factory=list)
    wine_prefixes: list[str] = field(default_factory=list)
    # Game ids or titles that should never be backed up.
    ignored_games: list[str] = field(default_factory=list)
    # Emulator profile ids that are turned off.
    disabled_emulators: list[str] = field(default_factory=list)
    custom_games: list[CustomGame] = field(default_factory=list)
    manifest_url: str = "https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml"

    # -- serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        cfg = cls()
        storage = data.get("storage", {})
        cfg.storage = StorageConfig(
            type=storage.get("type", "local"),
            path=storage.get("path", ""),
            smb=_build(SmbConfig, storage.get("smb", {})),
        )
        cfg.backup = _build(BackupConfig, data.get("backup", {}))
        cfg.custom_games = [_build(CustomGame, g) for g in data.get("custom_games", [])]
        for name in ("device_name", "steam_roots", "wine_prefixes", "ignored_games", "disabled_emulators",
                     "manifest_url"):
            if name in data:
                setattr(cfg, name, data[name])
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.storage.type not in STORAGE_TYPES:
            raise ValueError(f"storage.type must be one of {STORAGE_TYPES}, got {self.storage.type!r}")
        if self.backup.conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(f"backup.conflict_policy must be one of {CONFLICT_POLICIES}")
        if self.backup.keep_last < 1:
            raise ValueError("backup.keep_last must be at least 1")

    # -- dotted access used by `synker config set` and the Decky plugin --

    def set_value(self, key: str, raw: Any) -> None:
        target: Any = self
        parts = key.split(".")
        for part in parts[:-1]:
            target = getattr(target, part)
        name = parts[-1]
        if not hasattr(target, name):
            raise KeyError(key)
        current = getattr(target, name)
        setattr(target, name, _coerce(raw, current))
        self.validate()

    def is_storage_configured(self) -> bool:
        if self.storage.type == "local":
            return bool(self.storage.path)
        smb = self.storage.smb
        return bool(smb.host and smb.share)


def _build(cls, data: dict[str, Any]):
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def _coerce(raw: Any, current: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    if isinstance(current, bool):
        if raw.lower() in ("1", "true", "yes", "on"):
            return True
        if raw.lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"expected a boolean, got {raw!r}")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, list):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def config_path() -> Path:
    return paths.config_dir() / CONFIG_FILE


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        return Config.from_dict(tomllib.load(fh))


def save(cfg: Config, path: Path | None = None) -> Path:
    cfg.validate()
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        tomli_w.dump(cfg.to_dict(), fh)
    tmp.replace(path)
    return path
