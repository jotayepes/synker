"""Placeholder contexts: how manifest placeholders map to real folders.

The substitution rules follow ludusavi (MIT, Copyright (c) 2020 Matthew T.
Kennerly), `src/scan.rs::parse_paths`.

A context describes one "environment" a game's saves can live in:

* ``windows``: native Windows.
* ``linux``: native Linux (XDG directories, Flatpak sandboxes).
* ``wine``: a Wine or Proton prefix on Linux (``.../pfx`` with ``drive_c``).

Synker stores saves in a *portable* form, e.g. ``<winAppData>/Game/save.dat``,
so a backup made on Windows can be restored into a Proton prefix on a Steam
Deck and vice versa.
"""

from __future__ import annotations

import itertools
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from synker.detect.globber import case_insensitive_resolve

ROOT = "<root>"
GAME = "<game>"
BASE = "<base>"
HOME = "<home>"
STORE_GAME_ID = "<storeGameId>"
STORE_USER_ID = "<storeUserId>"
OS_USER_NAME = "<osUserName>"
WIN_APP_DATA = "<winAppData>"
WIN_LOCAL_APP_DATA = "<winLocalAppData>"
WIN_LOCAL_APP_DATA_LOW = "<winLocalAppDataLow>"
WIN_DOCUMENTS = "<winDocuments>"
WIN_PUBLIC = "<winPublic>"
WIN_PROGRAM_DATA = "<winProgramData>"
WIN_DIR = "<winDir>"
XDG_DATA = "<xdgData>"
XDG_CONFIG = "<xdgConfig>"
# Synker extension: the root of a Wine prefix (used for *.reg registry files).
WINE_PREFIX = "<winePrefix>"

_PLACEHOLDER_RE = re.compile(r"<[A-Za-z]+>")
# Placeholders that are not meaningful as restore anchors.
_NON_ANCHORS = {STORE_USER_ID, STORE_GAME_ID, OS_USER_NAME, GAME}

WINDOWS_FAMILY = {"windows", "wine"}


def _posix(path: str | Path) -> str:
    return str(path).replace("\\", "/").rstrip("/")


@dataclass
class PathContext:
    kind: str  # "windows" | "linux" | "wine"
    values: dict[str, list[str]] = field(default_factory=dict)
    label: str = ""

    @property
    def case_insensitive(self) -> bool:
        return self.kind in WINDOWS_FAMILY

    @property
    def os_name(self) -> str:
        return "linux" if self.kind == "linux" else "windows"

    def with_game(self, *, root: str | Path | None = None, base: str | Path | None = None,
                  store_game_id: str | None = None) -> PathContext:
        values = dict(self.values)
        if root:
            values[ROOT] = [_posix(root)]
        if base:
            values[BASE] = [_posix(base)]
            values[GAME] = [Path(base).name]
        if store_game_id:
            values[STORE_GAME_ID] = [str(store_game_id)]
        return PathContext(self.kind, values, self.label)

    # -- forward: template -> glob patterns ------------------------------

    def expand(self, template: str) -> list[str]:
        """Substitute placeholders; returns [] if one cannot be resolved here."""
        found = list(dict.fromkeys(_PLACEHOLDER_RE.findall(template)))
        choices = []
        for ph in found:
            if ph == STORE_USER_ID:
                choices.append(["*"])
            elif ph in self.values and self.values[ph]:
                choices.append(self.values[ph])
            else:
                return []
        out = []
        for combo in itertools.product(*choices):
            path = template.replace("\\", "/")
            for ph, value in zip(found, combo, strict=True):
                path = path.replace(ph, value)
            out.append(path)
        return out

    # -- backward: real path <-> portable path ---------------------------

    def _anchors(self) -> list[tuple[str, str]]:
        anchors = [(ph, v) for ph, vals in self.values.items() if ph not in _NON_ANCHORS
                   for v in vals if v and "*" not in v]
        anchors.sort(key=lambda a: len(a[1]), reverse=True)
        return anchors

    def to_portable(self, path: str | Path) -> str | None:
        real = _posix(path)
        cmp_real = real.casefold() if self.case_insensitive else real
        for ph, value in self._anchors():
            cmp_value = value.casefold() if self.case_insensitive else value
            if cmp_real == cmp_value or cmp_real.startswith(cmp_value + "/"):
                return ph + real[len(value):]
        return None

    def from_portable(self, portable: str) -> Path | None:
        m = re.match(r"^(<[A-Za-z]+>)(.*)$", portable)
        if not m:
            return None
        ph, rest = m.groups()
        values = self.values.get(ph)
        if not values:
            return None
        base = next((v for v in values if Path(v).exists()), values[0])
        if self.case_insensitive:
            return case_insensitive_resolve(Path(base), rest)
        return Path(base + rest)

    def can_resolve(self, portable: str) -> bool:
        m = re.match(r"^(<[A-Za-z]+>)", portable)
        return bool(m and self.values.get(m.group(1)))


# -- context factories -----------------------------------------------------


def _windows_known_folder(guid: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", wintypes.BYTE * 8)]

        import uuid

        u = uuid.UUID(guid)
        g = GUID(u.fields[0], u.fields[1], u.fields[2], (wintypes.BYTE * 8)(*u.bytes[8:]))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
            return None
        value = out.value
        ctypes.windll.ole32.CoTaskMemFree(out)
        return value
    except Exception:
        return None


def windows_context(home: Path | None = None, env: dict[str, str] | None = None) -> PathContext:
    env = env if env is not None else dict(os.environ)
    home_s = _posix(home or env.get("USERPROFILE") or Path.home())
    local = _posix(env.get("LOCALAPPDATA") or f"{home_s}/AppData/Local")
    documents = _windows_known_folder("FDD39AD0-238F-46AF-ADB4-6C85480369C7") if home is None else None
    values = {
        HOME: [home_s],
        OS_USER_NAME: [env.get("USERNAME") or Path(home_s).name],
        WIN_APP_DATA: [_posix(env.get("APPDATA") or f"{home_s}/AppData/Roaming")],
        WIN_LOCAL_APP_DATA: [local],
        WIN_LOCAL_APP_DATA_LOW: [_posix(Path(local).parent / "LocalLow")],
        WIN_DOCUMENTS: [_posix(documents or f"{home_s}/Documents")],
        WIN_PUBLIC: [_posix(env.get("PUBLIC") or "C:/Users/Public")],
        WIN_PROGRAM_DATA: [_posix(env.get("PROGRAMDATA") or "C:/ProgramData")],
        WIN_DIR: [_posix(env.get("WINDIR") or "C:/Windows")],
    }
    return PathContext("windows", values, label="windows")


def linux_context(home: Path, env: dict[str, str] | None = None,
                  extra_xdg: list[tuple[str, str]] | None = None) -> PathContext:
    env = env if env is not None else dict(os.environ)
    home_s = _posix(home)
    xdg_data = [_posix(env.get("XDG_DATA_HOME") or f"{home_s}/.local/share")]
    xdg_config = [_posix(env.get("XDG_CONFIG_HOME") or f"{home_s}/.config")]
    for data, config in extra_xdg or []:
        if data not in xdg_data:
            xdg_data.append(data)
        if config not in xdg_config:
            xdg_config.append(config)
    values = {
        HOME: [home_s],
        OS_USER_NAME: [Path(home_s).name],
        XDG_DATA: xdg_data,
        XDG_CONFIG: xdg_config,
    }
    return PathContext("linux", values, label="linux")


def wine_user(prefix: Path) -> str:
    users = prefix / "drive_c" / "users"
    try:
        names = [n for n in os.listdir(users) if n.casefold() not in ("public", "default")]
    except OSError:
        return "steamuser"
    if "steamuser" in names:
        return "steamuser"
    return names[0] if names else "steamuser"


def wine_context(prefix: Path, label: str = "wine") -> PathContext:
    """Context for a Wine prefix (the directory that contains drive_c)."""
    p = _posix(prefix)
    user = wine_user(prefix)
    drive_c = f"{p}/drive_c"
    home = f"{drive_c}/users/{user}"
    values = {
        WINE_PREFIX: [p],
        HOME: [home],
        OS_USER_NAME: [user],
        WIN_APP_DATA: [f"{home}/AppData/Roaming", f"{home}/Application Data"],
        WIN_LOCAL_APP_DATA: [f"{home}/AppData/Local", f"{home}/Local Settings/Application Data"],
        WIN_LOCAL_APP_DATA_LOW: [f"{home}/AppData/LocalLow"],
        WIN_DOCUMENTS: [f"{home}/Documents", f"{home}/My Documents"],
        WIN_PUBLIC: [f"{drive_c}/users/Public"],
        WIN_PROGRAM_DATA: [f"{drive_c}/ProgramData"],
        WIN_DIR: [f"{drive_c}/windows"],
    }
    return PathContext("wine", values, label=label)


def native_context(home: Path) -> PathContext:
    if sys.platform == "win32":
        return windows_context()
    return linux_context(home)
