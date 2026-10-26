"""Built-in emulator profiles.

Each profile lists the folders holding in-game saves, memory cards and save
states, as manifest-style templates. Flatpak locations are written against
``<home>/.var/app/<flatpak id>``. EmuDeck symlinks ~/Emulation/saves to these
same folders, so they are covered too.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmulatorProfile:
    id: str
    name: str
    processes: tuple[str, ...]
    linux: tuple[str, ...] = ()
    windows: tuple[str, ...] = ()

    @property
    def game_id(self) -> str:
        return f"emu-{self.id}"


def _flatpak(app_id: str, *subpaths: str) -> tuple[str, ...]:
    return tuple(f"<home>/.var/app/{app_id}/{p}" for p in subpaths)


def _yuzu_like(id_: str, name: str, dirname: str, proc: str, flatpak_id: str | None = None) -> EmulatorProfile:
    fp = _flatpak(flatpak_id, f"data/{dirname}/nand/user/save") if flatpak_id else ()
    return EmulatorProfile(
        id_, name, (proc, f"{proc}.exe", f"{proc}-cmd"),
        linux=(f"<xdgData>/{dirname}/nand/user/save",) + fp,
        windows=(f"<winAppData>/{dirname}/nand/user/save",),
    )


def _citra_like(id_: str, name: str, linux_dir: str, win_dir: str, proc: str,
                flatpak_id: str | None = None) -> EmulatorProfile:
    fp = (_flatpak(flatpak_id, f"data/{linux_dir}/sdmc/Nintendo 3DS", f"data/{linux_dir}/states")
          if flatpak_id else ())
    return EmulatorProfile(
        id_, name, (proc, f"{proc}.exe", f"{proc}-qt", f"{proc}-qt.exe"),
        linux=(f"<xdgData>/{linux_dir}/sdmc/Nintendo 3DS", f"<xdgData>/{linux_dir}/states") + fp,
        windows=(f"<winAppData>/{win_dir}/sdmc/Nintendo 3DS", f"<winAppData>/{win_dir}/states"),
    )


PROFILES: tuple[EmulatorProfile, ...] = (
    EmulatorProfile(
        "retroarch", "RetroArch", ("retroarch", "retroarch.exe"),
        linux=("<xdgConfig>/retroarch/saves", "<xdgConfig>/retroarch/states")
        + _flatpak("org.libretro.RetroArch", "config/retroarch/saves", "config/retroarch/states"),
        windows=("<winAppData>/RetroArch/saves", "<winAppData>/RetroArch/states"),
    ),
    EmulatorProfile(
        "dolphin", "Dolphin", ("dolphin-emu", "dolphin-emu-nogui", "Dolphin.exe"),
        linux=("<xdgData>/dolphin-emu/GC", "<xdgData>/dolphin-emu/Wii/title", "<xdgData>/dolphin-emu/StateSaves")
        + _flatpak("org.DolphinEmu.dolphin-emu", "data/dolphin-emu/GC", "data/dolphin-emu/Wii/title",
                   "data/dolphin-emu/StateSaves"),
        windows=("<winDocuments>/Dolphin Emulator/GC", "<winDocuments>/Dolphin Emulator/Wii/title",
                 "<winDocuments>/Dolphin Emulator/StateSaves", "<winAppData>/Dolphin Emulator/GC",
                 "<winAppData>/Dolphin Emulator/Wii/title", "<winAppData>/Dolphin Emulator/StateSaves"),
    ),
    EmulatorProfile(
        "pcsx2", "PCSX2", ("pcsx2", "pcsx2-qt", "pcsx2-qt.exe", "pcsx2-qtx64.exe", "pcsx2-qtx64-avx2.exe"),
        linux=("<xdgConfig>/PCSX2/memcards", "<xdgConfig>/PCSX2/sstates")
        + _flatpak("net.pcsx2.PCSX2", "config/PCSX2/memcards", "config/PCSX2/sstates"),
        windows=("<winDocuments>/PCSX2/memcards", "<winDocuments>/PCSX2/sstates"),
    ),
    EmulatorProfile(
        "duckstation", "DuckStation",
        ("duckstation-qt", "duckstation-qt-x64-ReleaseLTCG.exe", "DuckStation.AppImage"),
        linux=("<xdgData>/duckstation/memcards", "<xdgData>/duckstation/savestates")
        + _flatpak("org.duckstation.DuckStation", "data/duckstation/memcards", "data/duckstation/savestates"),
        windows=("<winDocuments>/DuckStation/memcards", "<winDocuments>/DuckStation/savestates",
                 "<winLocalAppData>/DuckStation/memcards", "<winLocalAppData>/DuckStation/savestates"),
    ),
    EmulatorProfile(
        "ppsspp", "PPSSPP", ("PPSSPPSDL", "ppsspp", "PPSSPPQt", "PPSSPPWindows64.exe", "PPSSPPWindows.exe"),
        linux=("<xdgConfig>/ppsspp/PSP/SAVEDATA", "<xdgConfig>/ppsspp/PSP/PPSSPP_STATE")
        + _flatpak("org.ppsspp.PPSSPP", "config/ppsspp/PSP/SAVEDATA", "config/ppsspp/PSP/PPSSPP_STATE"),
        windows=("<winDocuments>/PPSSPP/PSP/SAVEDATA", "<winDocuments>/PPSSPP/PSP/PPSSPP_STATE"),
    ),
    EmulatorProfile(
        "rpcs3", "RPCS3", ("rpcs3", "rpcs3.exe"),
        linux=("<xdgConfig>/rpcs3/dev_hdd0/home/00000001/savedata",)
        + _flatpak("net.rpcs3.RPCS3", "config/rpcs3/dev_hdd0/home/00000001/savedata"),
    ),
    EmulatorProfile(
        "cemu", "Cemu", ("cemu", "Cemu", "Cemu.exe"),
        linux=("<xdgData>/Cemu/mlc01/usr/save",) + _flatpak("info.cemu.Cemu", "data/Cemu/mlc01/usr/save"),
        windows=("<winAppData>/Cemu/mlc01/usr/save",),
    ),
    EmulatorProfile(
        "ryujinx", "Ryujinx", ("Ryujinx", "Ryujinx.exe", "Ryujinx.sh"),
        linux=("<xdgConfig>/Ryujinx/bis/user/save",) + _flatpak("org.ryujinx.Ryujinx", "config/Ryujinx/bis/user/save"),
        windows=("<winAppData>/Ryujinx/bis/user/save",),
    ),
    _yuzu_like("yuzu", "yuzu", "yuzu", "yuzu", "org.yuzu_emu.yuzu"),
    _yuzu_like("suyu", "suyu", "suyu", "suyu"),
    _yuzu_like("sudachi", "Sudachi", "sudachi", "sudachi"),
    _yuzu_like("citron", "Citron", "citron", "citron"),
    _yuzu_like("eden", "Eden", "eden", "eden"),
    _citra_like("citra", "Citra", "citra-emu", "Citra", "citra", "org.citra_emu.citra"),
    _citra_like("lime3ds", "Lime3DS", "lime3ds-emu", "Lime3DS", "lime3ds", "io.github.lime3ds.Lime3DS"),
    _citra_like("azahar", "Azahar", "azahar-emu", "Azahar", "azahar", "org.azahar_emu.Azahar"),
    EmulatorProfile(
        "vita3k", "Vita3K", ("Vita3K", "Vita3K.exe"),
        linux=("<xdgData>/Vita3K/Vita3K/ux0/user/00/savedata",),
        windows=("<winAppData>/Vita3K/Vita3K/ux0/user/00/savedata",),
    ),
    EmulatorProfile(
        "xenia", "Xenia", ("xenia.exe", "xenia_canary.exe"),
        windows=("<winDocuments>/Xenia/content",),
    ),
)


def by_id(profile_id: str) -> EmulatorProfile | None:
    return next((p for p in PROFILES if p.id == profile_id), None)
