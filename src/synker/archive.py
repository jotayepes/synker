"""Backup archives: a zip with the save files plus a meta.json describing them."""

from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

META = "meta.json"
FORMAT_VERSION = 1


@dataclass
class ArchivedFile:
    portable: str
    kind: str
    sha256: str
    size: int
    mtime: float
    member: str


def member_name(portable: str, used: set[str]) -> str:
    """Readable zip member name: "<winAppData>/Game/x.sav" -> "files/winAppData/Game/x.sav"."""
    name = re.sub(r"[<>:]", "", portable).lstrip("/")
    name = "files/" + "/".join(p for p in name.split("/") if p not in ("", ".", ".."))
    candidate, n = name, 1
    while candidate.casefold() in used:
        n += 1
        candidate = f"{name}.{n}"
    used.add(candidate.casefold())
    return candidate


def write_archive(dest: Path, meta: dict[str, Any], files: list[tuple[Path, ArchivedFile]]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, info in files:
            zf.write(src, info.member)
        meta = dict(meta, version=FORMAT_VERSION, files=[vars(f) for _, f in files])
        zf.writestr(META, json.dumps(meta, indent=1))
    os.replace(tmp, dest)


def read_meta(path: Path) -> tuple[dict[str, Any], list[ArchivedFile]]:
    with zipfile.ZipFile(path) as zf:
        meta = json.loads(zf.read(META))
    files = [ArchivedFile(**f) for f in meta.get("files", [])]
    return meta, files


def extract_member(path: Path, member: str, target: Path, mtime: float | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".synker-part")
    with zipfile.ZipFile(path) as zf, zf.open(member) as src, tmp.open("wb") as dst:
        while chunk := src.read(1 << 20):
            dst.write(chunk)
    os.replace(tmp, target)
    if mtime:
        os.utime(target, (mtime, mtime))
