"""Detect which known games are currently running, from the process list."""

from __future__ import annotations

import os
import re
import sys

import psutil

from synker.detect.scanner import Game

_APPID_RE = re.compile(r"AppId=(\d+)")
_CASE_INSENSITIVE = sys.platform == "win32"


def _norm(path: str) -> str:
    path = path.replace("\\", "/").rstrip("/")
    return path.casefold() if _CASE_INSENSITIVE else path


class ProcessWatcher:
    def __init__(self, games: list[Game]):
        self.set_games(games)

    def set_games(self, games: list[Game]) -> None:
        self.by_appid: dict[int, str] = {}
        self.by_install: list[tuple[str, str]] = []
        self.by_name: dict[str, str] = {}
        for g in games:
            if g.ignored:
                continue
            if g.appid:
                self.by_appid.setdefault(g.appid, g.id)
            if g.install_path and g.source != "detected":
                self.by_install.append((_norm(str(g.install_path)) + "/", g.id))
            # Only explicit process names (emulators, custom games, shortcut exes);
            # manifest launch names such as "game.exe" are too generic.
            if g.source in ("emulator", "custom", "steam-shortcut"):
                for proc in g.processes:
                    self.by_name.setdefault(proc.casefold(), g.id)
        self.by_install.sort(key=lambda x: len(x[0]), reverse=True)

    def match(self, name: str, exe: str, cmdline: list[str], cwd: str) -> str | None:
        joined = " ".join(cmdline)
        if "AppId=" in joined:
            m = _APPID_RE.search(joined)
            if m and int(m.group(1)) in self.by_appid:
                return self.by_appid[int(m.group(1))]
        candidates = [exe, cwd] + [c for c in cmdline[:1]]
        for cand in candidates:
            if not cand:
                continue
            norm = _norm(cand) + "/"
            for prefix, gid in self.by_install:
                if norm.startswith(prefix):
                    return gid
        names = {name.casefold()}
        if cmdline:
            names.add(os.path.basename(cmdline[0].replace("\\", "/")).casefold())
        if exe:
            names.add(os.path.basename(exe).casefold())
        for n in names:
            if n in self.by_name:
                return self.by_name[n]
        return None

    def running(self) -> set[str]:
        found: set[str] = set()
        for proc in psutil.process_iter(["name", "exe", "cmdline", "cwd"]):
            info = proc.info
            gid = self.match(info.get("name") or "", info.get("exe") or "", info.get("cmdline") or [],
                             info.get("cwd") or "")
            if gid:
                found.add(gid)
        return found
