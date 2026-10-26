"""Locations of Synker's own config, data and cache directories.

Every directory can be overridden through environment variables. The Decky
plugin uses this to point Synker at the plugin's settings/runtime folders.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP_NAME = "synker"


def _env_dir(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else None


def config_dir() -> Path:
    return _env_dir("SYNKER_CONFIG_DIR") or Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def data_dir() -> Path:
    return _env_dir("SYNKER_DATA_DIR") or Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    override = _env_dir("SYNKER_CACHE_DIR")
    if override:
        return override
    if os.environ.get("SYNKER_DATA_DIR"):
        return data_dir() / "cache"
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def home_dir() -> Path:
    """The real user's home. Under Decky this may differ from $HOME."""
    return _env_dir("SYNKER_HOME") or _env_dir("DECKY_USER_HOME") or Path.home()
