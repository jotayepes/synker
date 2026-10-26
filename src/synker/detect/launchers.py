"""Heroic (Epic/GOG) and Lutris games installed on Linux, with their Wine prefixes."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


@dataclass
class LauncherGame:
    source: str  # "heroic-epic" | "heroic-gog" | "lutris"
    store: str  # manifest store name: "epic" | "gog" | "other"
    name: str
    install_path: Path | None
    prefix: Path | None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


# -- Heroic ------------------------------------------------------------------


def heroic_dirs(home: Path) -> list[Path]:
    dirs = [home / ".config" / "heroic",
            home / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic"]
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        dirs.append(Path(os.environ["APPDATA"]) / "heroic")
    return [d for d in dirs if d.is_dir()]


def _heroic_prefix(heroic: Path, app_name: str) -> Path | None:
    data = _load_json(heroic / "GamesConfig" / f"{app_name}.json") or {}
    prefix = (data.get(app_name) or {}).get("winePrefix")
    if not prefix:
        return None
    prefix = Path(prefix)
    # Proton prefixes keep the actual Wine prefix in a pfx/ subfolder.
    if (prefix / "pfx" / "drive_c").is_dir():
        return prefix / "pfx"
    return prefix if (prefix / "drive_c").is_dir() else None


def heroic_games(home: Path) -> list[LauncherGame]:
    games = []
    for heroic in heroic_dirs(home):
        legendary = _load_json(heroic / "legendaryConfig" / "legendary" / "installed.json") or {}
        for app_name, info in legendary.items():
            if not isinstance(info, dict):
                continue
            games.append(LauncherGame("heroic-epic", "epic", info.get("title") or app_name,
                                      Path(info["install_path"]) if info.get("install_path") else None,
                                      _heroic_prefix(heroic, app_name)))
        gog = _load_json(heroic / "gog_store" / "installed.json") or {}
        titles = {}
        library = _load_json(heroic / "store_cache" / "gog_library.json") or {}
        for entry in library.get("games", []) if isinstance(library, dict) else []:
            if isinstance(entry, dict) and entry.get("app_name"):
                titles[str(entry["app_name"])] = entry.get("title")
        for info in gog.get("installed", []) if isinstance(gog, dict) else []:
            app_name = str(info.get("appName", ""))
            install = Path(info["install_path"]) if info.get("install_path") else None
            name = titles.get(app_name) or (install.name if install else app_name)
            games.append(LauncherGame("heroic-gog", "gog", name, install, _heroic_prefix(heroic, app_name)))
    return games


# -- Lutris ------------------------------------------------------------------


def lutris_games(home: Path) -> list[LauncherGame]:
    games = []
    for data_dir, config_dir in (
        (home / ".local" / "share" / "lutris", home / ".config" / "lutris"),
        (home / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris",
         home / ".var" / "app" / "net.lutris.Lutris" / "config" / "lutris"),
    ):
        db = data_dir / "pga.db"
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = con.execute("SELECT name, directory, configpath FROM games WHERE installed = 1").fetchall()
            con.close()
        except sqlite3.Error as exc:
            log.debug("cannot read %s: %s", db, exc)
            continue
        for name, directory, configpath in rows:
            prefix = None
            install = Path(directory) if directory else None
            for games_dir in (config_dir / "games", data_dir / "games"):
                cfg_file = games_dir / f"{configpath}.yml"
                if not cfg_file.is_file():
                    continue
                try:
                    cfg = yaml.safe_load(cfg_file.read_text("utf-8")) or {}
                except (OSError, yaml.YAMLError):
                    break
                game = cfg.get("game") or {}
                if game.get("prefix"):
                    prefix = Path(os.path.expanduser(game["prefix"]))
                if not install and game.get("working_dir"):
                    install = Path(game["working_dir"])
                elif not install and game.get("exe"):
                    install = Path(game["exe"]).parent
                break
            if prefix is not None and not (prefix / "drive_c").is_dir():
                prefix = None
            games.append(LauncherGame("lutris", "other", name, install, prefix))
    return games
