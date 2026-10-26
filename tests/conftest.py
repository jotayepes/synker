from __future__ import annotations

from pathlib import Path

import pytest
import vdf

from synker.config import Config
from synker.manifest.index import ManifestIndex

MANIFEST = {
    "Proton Game": {
        "files": {
            "<winAppData>/ProtonDev/ProtonGame/Saves": {"tags": ["save"], "when": [{"os": "windows"}]},
            "<base>/userdata/*.sav": {"tags": ["save"]},
        },
        "installDir": {"ProtonGame": {}},
        "steam": {"id": 1000},
    },
    "Native Game": {
        "files": {"<xdgData>/NativeGame/save*.dat": {"tags": ["save"], "when": [{"os": "linux"}]}},
        "installDir": {"NativeGame": {}},
        "steam": {"id": 2000},
    },
    "Cloud Game": {
        "cloud": {"steam": True},
        "files": {"<xdgConfig>/CloudGame": {"tags": ["save"]}},
        "steam": {"id": 3000},
    },
    "Registry Game": {
        "registry": {"HKEY_CURRENT_USER/Software/Reg": {"tags": ["save"]}},
        "steam": {"id": 4000},
    },
    "Shortcut Game": {
        "files": {"<winDocuments>/My Games/Shortcut Game": {"tags": ["save"]}},
    },
    "Loose Game": {
        "files": {"<xdgConfig>/loosegame/profile.json": {"tags": ["save"]}},
    },
    "Old Name": {"alias": "Native Game"},
    "Stub": {"steam": {"id": 5000}},
}


def write(path: Path, content: str | bytes = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return path


def acf(appid: int, name: str, installdir: str) -> str:
    return vdf.dumps({"AppState": {"appid": str(appid), "name": name, "installdir": installdir}})


@pytest.fixture
def index() -> ManifestIndex:
    return ManifestIndex.from_manifest_data(MANIFEST)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    steam = home / ".local" / "share" / "Steam"
    library2 = tmp_path / "sdcard" / "SteamLibrary"
    write(steam / "steamapps" / "libraryfolders.vdf", vdf.dumps({"libraryfolders": {
        "0": {"path": str(steam)}, "1": {"path": str(library2)}}}))
    # Proton game installed on the SD card library, prefix there too.
    write(library2 / "steamapps" / "appmanifest_1000.acf", acf(1000, "Proton Game", "ProtonGame"))
    write(library2 / "steamapps" / "common" / "ProtonGame" / "userdata" / "slot1.sav", "base-save")
    pfx = library2 / "steamapps" / "compatdata" / "1000" / "pfx"
    write(pfx / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / "protondev" / "protongame"
          / "saves" / "slot.dat", "proton-save")
    # Native game.
    write(steam / "steamapps" / "appmanifest_2000.acf", acf(2000, "Native Game", "NativeGame"))
    (steam / "steamapps" / "common" / "NativeGame").mkdir(parents=True)
    write(home / ".local" / "share" / "NativeGame" / "save1.dat", "native-1")
    write(home / ".local" / "share" / "NativeGame" / "other.txt", "not a save")
    # Cloud game.
    write(steam / "steamapps" / "appmanifest_3000.acf", acf(3000, "Cloud Game", "CloudGame"))
    write(home / ".config" / "CloudGame" / "s.dat")
    # Proton tool that must be ignored.
    write(steam / "steamapps" / "appmanifest_1493710.acf", acf(1493710, "Proton Experimental", "Proton - Exp"))
    # Non-Steam shortcut with its own prefix.
    shortcuts = {"shortcuts": {"0": {"appid": -1234567890, "AppName": "Shortcut Game",
                                     "Exe": '"/games/shortcut/game.exe"', "StartDir": '"/games/shortcut"'}}}
    write(steam / "userdata" / "42" / "config" / "shortcuts.vdf", vdf.binary_dumps(shortcuts))
    sc_appid = -1234567890 & 0xFFFFFFFF
    write(steam / "steamapps" / "compatdata" / str(sc_appid) / "pfx" / "drive_c" / "users" / "steamuser"
          / "Documents" / "My Games" / "Shortcut Game" / "profile.sav", "shortcut-save")
    # Loose game found only by the full scan.
    write(home / ".config" / "loosegame" / "profile.json", "{}")
    # Emulator.
    write(home / ".config" / "retroarch" / "saves" / "zelda.srm", "sram")

    monkeypatch.setenv("SYNKER_HOME", str(home))
    monkeypatch.setenv("SYNKER_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SYNKER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SYNKER_NO_KEYRING", "1")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(device_name="testbox")
    c.storage.type = "local"
    c.storage.path = str(tmp_path / "nas")
    return c
