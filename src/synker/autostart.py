"""Install the daemon to start with the user session (systemd --user on Linux, Startup folder on Windows)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "synker.service"


def daemon_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "daemon", "run"]
    exe = shutil.which("synker")
    if exe:
        return [exe, "daemon", "run"]
    return [sys.executable, "-m", "synker", "daemon", "run"]


def _unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user" / UNIT_NAME


def _startup_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "synker.cmd"


def install() -> str:
    cmd = daemon_command()
    if sys.platform == "win32":
        path = _startup_path()
        quoted = " ".join(f'"{c}"' for c in cmd)
        path.write_text(f'@echo off\r\nstart "" /min {quoted}\r\n', "utf-8")
        return str(path)
    path = _unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_start = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    path.write_text(
        "[Unit]\n"
        "Description=Synker game save backup daemon\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
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
    else:
        path = _unit_path()
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME], check=False)
    path.unlink(missing_ok=True)
    return str(path)
