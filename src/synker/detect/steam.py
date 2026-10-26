"""Steam discovery: installs, libraries, installed apps, non-Steam shortcuts, Proton prefixes."""

from __future__ import annotations

import logging
import os
import re
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

import vdf

log = logging.getLogger(__name__)

# Runtimes and redistributables that show up as installed "apps".
TOOL_APPIDS = {228980, 1070560, 1391110, 1628350, 1493710, 1826330, 2180100, 2348590, 3658110}
TOOL_NAME_RE = re.compile(r"^(proton (\d|experimental|hotfix|next|easyanticheat|battleye)|steam linux runtime|steamworks common)", re.I)


@dataclass
class SteamApp:
    appid: int
    name: str
    installdir: str
    library: Path

    @property
    def install_path(self) -> Path:
        return self.library / "steamapps" / "common" / self.installdir


@dataclass
class SteamShortcut:
    appid: int
    name: str
    exe: str
    start_dir: str


def shortcut_appid(exe: str, name: str) -> int:
    """Legacy appid computation for shortcuts without a stored appid."""
    return (zlib.crc32((exe + name).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def candidate_roots(home: Path) -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
    else:
        roots += [
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam",
        ]
    return roots


def is_flatpak_root(root: Path) -> bool:
    return "com.valvesoftware.Steam" in str(root)


class SteamInstall:
    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def discover(cls, home: Path, extra: list[str] | None = None) -> list[SteamInstall]:
        seen: set[str] = set()
        out = []
        for root in [Path(p).expanduser() for p in extra or []] + candidate_roots(home):
            if not (root / "steamapps").is_dir():
                continue
            real = os.path.realpath(root)
            if real in seen:
                continue
            seen.add(real)
            out.append(cls(root))
        return out

    def libraries(self) -> list[Path]:
        libs = [self.root]
        for candidate in (self.root / "steamapps" / "libraryfolders.vdf",
                          self.root / "config" / "libraryfolders.vdf"):
            try:
                data = vdf.loads(candidate.read_text("utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            for key, value in folders.items():
                if not key.isdigit():
                    continue
                path = value.get("path") if isinstance(value, dict) else value
                if path:
                    libs.append(Path(path))
            break
        seen: set[str] = set()
        unique = []
        for lib in libs:
            real = os.path.realpath(lib)
            if real not in seen and (lib / "steamapps").is_dir():
                seen.add(real)
                unique.append(lib)
        return unique

    def apps(self) -> list[SteamApp]:
        apps: dict[int, SteamApp] = {}
        for lib in self.libraries():
            steamapps = lib / "steamapps"
            for acf in steamapps.glob("appmanifest_*.acf"):
                try:
                    state = vdf.loads(acf.read_text("utf-8", errors="replace")).get("AppState", {})
                    appid = int(state["appid"])
                except (OSError, SyntaxError, ValueError, KeyError):
                    log.debug("unreadable %s", acf)
                    continue
                name = state.get("name", "")
                if appid in TOOL_APPIDS or TOOL_NAME_RE.match(name):
                    continue
                apps.setdefault(appid, SteamApp(appid, name, state.get("installdir", ""), lib))
        return list(apps.values())

    def user_ids(self) -> list[str]:
        try:
            return [d for d in os.listdir(self.root / "userdata") if d.isdigit() and d != "0"]
        except OSError:
            return []

    def shortcuts(self) -> list[SteamShortcut]:
        found: dict[int, SteamShortcut] = {}
        for uid in self.user_ids():
            path = self.root / "userdata" / uid / "config" / "shortcuts.vdf"
            try:
                data = vdf.binary_loads(path.read_bytes())
            except (OSError, SyntaxError, ValueError):
                continue
            for entry in (data.get("shortcuts") or {}).values():
                entry = {k.casefold(): v for k, v in entry.items()}
                name = entry.get("appname", "")
                exe = entry.get("exe", "")
                appid = entry.get("appid")
                appid = (int(appid) & 0xFFFFFFFF) if appid is not None else shortcut_appid(exe, name)
                found.setdefault(appid, SteamShortcut(appid, name, exe.strip('"'),
                                                      entry.get("startdir", "").strip('"')))
        return list(found.values())

    def proton_prefix(self, appid: int) -> Path | None:
        for lib in self.libraries():
            pfx = lib / "steamapps" / "compatdata" / str(appid) / "pfx"
            if (pfx / "drive_c").is_dir():
                return pfx
        return None
