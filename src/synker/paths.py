"""Locations of Synker's own config, data and cache directories.

Every directory can be overridden through environment variables. The Decky
plugin uses this to point Synker at the plugin's settings/runtime folders.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import platformdirs

APP_NAME = "synker"


def _env_dir(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else None


def decky_dirs() -> tuple[Path, Path] | None:
    """Settings/runtime dirs when running as the binary bundled in a Decky plugin.

    That binary lives in ~/homebrew/plugins/<plugin>/bin/synker; when it is
    called directly (e.g. from a Steam launch option) it must use the same
    folders as the plugin.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if len(exe.parents) < 4 or exe.parent.name != "bin" or exe.parents[2].name != "plugins":
        return None
    homebrew, plugin = exe.parents[3], exe.parents[1].name
    return homebrew / "settings" / plugin, homebrew / "data" / plugin


def config_dir() -> Path:
    override = _env_dir("SYNKER_CONFIG_DIR")
    if override:
        return override
    decky = decky_dirs()
    if decky:
        return decky[0]
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def data_dir() -> Path:
    override = _env_dir("SYNKER_DATA_DIR")
    if override:
        return override
    decky = decky_dirs()
    if decky:
        return decky[1]
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    override = _env_dir("SYNKER_CACHE_DIR")
    if override:
        return override
    if os.environ.get("SYNKER_DATA_DIR") or decky_dirs():
        return data_dir() / "cache"
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def home_dir() -> Path:
    """The real user's home. Under Decky this may differ from $HOME."""
    return _env_dir("SYNKER_HOME") or _env_dir("DECKY_USER_HOME") or Path.home()
