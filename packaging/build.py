"""Build standalone executables with PyInstaller.

    python packaging/build.py            # CLI only  -> dist/synker[.exe]
    python packaging/build.py --gui      # CLI + GUI -> dist/synker-gui[.exe]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = [
    "--noconfirm", "--clean", "--onefile",
    "--paths", str(ROOT / "src"),
    "--collect-submodules", "synker",
    "--collect-submodules", "smbprotocol",
    "--collect-submodules", "smbclient",
    "--collect-submodules", "spnego",
    "--hidden-import", "yaml",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]


def run(args: list[str]) -> None:
    print("+ pyinstaller", " ".join(args))
    subprocess.check_call([sys.executable, "-m", "PyInstaller", *args])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true")
    opts = parser.parse_args()
    run(COMMON + ["--name", "synker", "--console", "--exclude-module", "PySide6",
                  str(ROOT / "packaging" / "synker_cli.py")])
    if opts.gui:
        run(COMMON + ["--name", "synker-gui", "--windowed", "--collect-submodules", "keyring",
                      str(ROOT / "packaging" / "synker_gui.py")])


if __name__ == "__main__":
    main()
