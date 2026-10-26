from pathlib import Path

from synker.detect import placeholders
from synker.detect.globber import Globber
from synker.detect.scanner import Scanner
from synker.detect.steam import SteamInstall


def test_steam_discovery(home):
    installs = SteamInstall.discover(home)
    assert len(installs) == 1
    apps = {a.appid: a for a in installs[0].apps()}
    assert set(apps) == {1000, 2000, 3000}
    shortcuts = installs[0].shortcuts()
    assert shortcuts[0].appid == -1234567890 & 0xFFFFFFFF
    assert shortcuts[0].start_dir == "/games/shortcut"
    assert installs[0].proton_prefix(1000) is not None


def test_case_insensitive_glob(tmp_path):
    (tmp_path / "AppData" / "Roaming").mkdir(parents=True)
    g = Globber()
    assert g.glob(f"{tmp_path}/appdata/ROAMING", case_insensitive=True)
    assert not g.glob(f"{tmp_path}/appdata/ROAMING", case_insensitive=False)


def test_scan_finds_all_sources(home, cfg, index):
    games = {g.id: g for g in Scanner(cfg, index, home).scan()}
    assert set(games) >= {"proton-game", "native-game", "cloud-game", "shortcut-game", "loose-game", "emu-retroarch"}
    assert games["cloud-game"].cloud_covered
    assert games["loose-game"].source == "detected"

    proton = {f.portable: f for f in games["proton-game"].find_files()}
    assert "<winAppData>/protondev/protongame/saves/slot.dat" in proton
    assert "<base>/userdata/slot1.sav" in proton

    native = [f.portable for f in games["native-game"].find_files()]
    assert native == ["<xdgData>/NativeGame/save1.dat"]

    sc = [f.portable for f in games["shortcut-game"].find_files()]
    assert sc == ["<winDocuments>/My Games/Shortcut Game/profile.sav"]


def test_portable_paths_cross_platform(tmp_path):
    pfx = tmp_path / "pfx"
    (pfx / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming").mkdir(parents=True)
    wine = placeholders.wine_context(pfx)
    win = placeholders.windows_context(home=Path("C:/Users/jo"), env={"USERNAME": "jo"})
    real = pfx / "drive_c/users/steamuser/AppData/Roaming/Game/a.sav"
    portable = wine.to_portable(real)
    assert portable == "<winAppData>/Game/a.sav"
    assert str(win.from_portable(portable)).replace("\\", "/") == "C:/Users/jo/AppData/Roaming/Game/a.sav"
    assert wine.from_portable("<winAppData>/Game/a.sav") == real


def test_find_by_appid_and_name(home, cfg, index):
    sc = Scanner(cfg, index, home)
    assert sc.find(appid=1000).id == "proton-game"
    assert sc.find("Native Game").id == "native-game"
    assert sc.find(name="loose game").id == "loose-game"
