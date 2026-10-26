"""Glob expansion with optional case-insensitivity and a directory listing cache.

Manifest paths are evaluated as globs after placeholder substitution. Inside
Wine/Proton prefixes (and on Windows) names must match case-insensitively,
because the game may write `SaveGames` while the manifest says `savegames`.
Scanning thousands of manifest entries hits the same parent directories over
and over, so listings are cached for the lifetime of a Globber.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

_MAGIC = re.compile(r"[*?\[]")


def _split(pattern: str) -> tuple[str, list[str]]:
    pattern = pattern.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", pattern):
        anchor, rest = pattern[:3], pattern[3:]
    elif pattern.startswith("/"):
        anchor, rest = "/", pattern[1:]
    else:
        return "", []
    return anchor, [p for p in rest.split("/") if p not in ("", ".")]


class Globber:
    def __init__(self) -> None:
        self._listing: dict[str, list[str] | None] = {}

    def listdir(self, path: str) -> list[str]:
        cached = self._listing.get(path, False)
        if cached is not False:
            return cached or []
        try:
            entries = os.listdir(path)
        except OSError:
            entries = None
        self._listing[path] = entries
        return entries or []

    def glob(self, pattern: str, case_insensitive: bool = False) -> list[str]:
        """Return existing paths matching an absolute glob pattern."""
        anchor, parts = _split(pattern)
        if not anchor:
            return []
        current = [anchor]
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            nxt: list[str] = []
            if part == "**":
                for base in current:
                    nxt.append(base)
                    nxt.extend(self._all_dirs(base))
            elif part == "..":
                nxt = [os.path.dirname(os.path.normpath(b)) or b for b in current]
            elif _MAGIC.search(part):
                pat = part.casefold() if case_insensitive else part
                for base in current:
                    for name in self.listdir(base):
                        cand = name.casefold() if case_insensitive else name
                        if fnmatch.fnmatchcase(cand, pat):
                            nxt.append(os.path.join(base, name))
            else:
                for base in current:
                    direct = os.path.join(base, part)
                    if not case_insensitive:
                        if part in self.listdir(base):
                            nxt.append(direct)
                        continue
                    folded = part.casefold()
                    nxt.extend(os.path.join(base, n) for n in self.listdir(base) if n.casefold() == folded)
            if not last:
                nxt = [p for p in nxt if os.path.isdir(p)]
            current = list(dict.fromkeys(nxt))
            if not current:
                return []
        return [p for p in current if os.path.exists(p)]

    def _all_dirs(self, base: str) -> list[str]:
        out = []
        for root, dirs, _files in os.walk(base):
            out.extend(os.path.join(root, d) for d in dirs)
        return out


def iter_files(path: str) -> list[Path]:
    """A matched file, or every file under a matched directory."""
    if os.path.isfile(path):
        return [Path(path)]
    found = []
    for root, _dirs, files in os.walk(path):
        found.extend(Path(root, f) for f in files)
    return found


def case_insensitive_resolve(base: Path, rest: str) -> Path:
    """Join `rest` onto `base`, reusing existing entries that differ only by case."""
    current = base
    for part in [p for p in rest.replace("\\", "/").split("/") if p]:
        candidate = current / part
        if not candidate.exists() and current.is_dir():
            folded = part.casefold()
            for name in os.listdir(current):
                if name.casefold() == folded:
                    candidate = current / name
                    break
        current = candidate
    return current
