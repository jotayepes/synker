"""Install the daemon to start with the user session (systemd --user on Linux, Startup folder on Windows)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "synker.service"


def daemon_command(gui: bool = False) -> list[str]:
    """Command started at login: the CLI daemon, or the GUI minimised to the tray (it runs the daemon)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if gui:
            gui_exe = exe.with_name("synker-gui" + exe.suffix)
            return [str(gui_exe if gui_exe.exists() else exe), "--minimized"]
        cli_exe = exe.with_name("synker" + exe.suffix)
        return [str(cli_exe if cli_exe.exists() else exe), "daemon", "run"]
    if gui:
        exe = shutil.which("synker-gui")
        return [exe, "--minimized"] if exe else [sys.executable, "-m", "synker.gui.app", "--minimized"]
    exe = shutil.which("synker")
    if exe:
        return [exe, "daemon", "run"]
    return [sys.executable, "-m", "synker", "daemon", "run"]


def _unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user" / UNIT_NAME


def _startup_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "synker.cmd"


def _desktop_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / "synker.desktop"


def is_installed() -> bool:
    if sys.platform == "win32":
        return _startup_path().exists()
    return _unit_path().exists() or _desktop_path().exists()


def install(gui: bool = False) -> str:
    """Start Synker at login: the GUI (tray) when gui=True, otherwise the headless daemon."""
    cmd = daemon_command(gui)
    if sys.platform == "win32":
        path = _startup_path()
        quoted = " ".join(f'"{c}"' for c in cmd)
        path.write_text(f'@echo off\r\nstart "" /min {quoted}\r\n', "utf-8")
        return str(path)
    exec_line = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    if gui:
        # Graphical apps belong in XDG autostart, which runs inside the desktop session.
        path = _desktop_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\nType=Application\nName=Synker\n"
            "Comment=Automatic game save backup\n"
            f"Exec={exec_line}\nX-GNOME-Autostart-enabled=true\n",
            "utf-8",
        )
        return str(path)
    path = _unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Unit]\n"
        "Description=Synker game save backup daemon\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"ExecStart={exec_line}\n"
        "Restart=on-failure\n"
        "RestartSec=30\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        "utf-8",
    )
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME], check=False)
    return str(path)


def uninstall() -> str:
    if sys.platform == "win32":
        path = _startup_path()
        path.unlink(missing_ok=True)
        return str(path)
    removed = []
    if _unit_path().exists():
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME], check=False)
        _unit_path().unlink()
        removed.append(str(_unit_path()))
    if _desktop_path().exists():
        _desktop_path().unlink()
        removed.append(str(_desktop_path()))
    return ", ".join(removed)
