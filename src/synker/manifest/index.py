"""Compact, fast-loading index built from the ludusavi manifest.

The upstream manifest is a ~18 MB YAML file. Parsing it takes a while, so we
parse it once after each download and keep a gzipped JSON index with only
what Synker needs: save file patterns, install dirs, store ids, launch
executables and the store cloud flags.
"""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

INDEX_VERSION = 1


def normalize_title(title: str) -> str:
    """Normalise a game title for matching ("Hollow Knight™" -> "hollowknight")."""
    text = re.sub(r"[™®©]", "", title)
    text = unicodedata.normalize("NFKD", text).casefold()
    return re.sub(r"[^0-9a-z]+", "", text)


@dataclass
class FileRule:
    path: str
    tags: list[str] = field(default_factory=list)
    # List of {"os": ..., "store": ...} conditions; empty means "always".
    when: list[dict[str, str]] = field(default_factory=list)

    def applies(self, os_name: str | None = None, store: str | None = None) -> bool:
        """`when` is only a hint upstream, so an unknown os/store never excludes."""
        if not self.when:
            return True
        for cond in self.when:
            if os_name and cond.get("os") and cond["os"] != os_name:
                continue
            if store and cond.get("store") and cond["store"] != store:
                continue
            return True
        return False


@dataclass
class GameRecord:
    title: str
    files: list[FileRule] = field(default_factory=list)
    has_registry: bool = False
    install_dirs: list[str] = field(default_factory=list)
    steam_ids: list[int] = field(default_factory=list)
    flatpak_id: str | None = None
    executables: list[str] = field(default_factory=list)
    cloud: dict[str, bool] = field(default_factory=dict)

    @property
    def has_store_cloud(self) -> bool:
        return any(self.cloud.values())

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"f": [[r.path, r.tags, r.when] for r in self.files]}
        if self.has_registry:
            out["r"] = 1
        if self.install_dirs:
            out["i"] = self.install_dirs
        if self.steam_ids:
            out["s"] = self.steam_ids
        if self.flatpak_id:
            out["p"] = self.flatpak_id
        if self.executables:
            out["e"] = self.executables
        if self.cloud:
            out["c"] = self.cloud
        return out

    @classmethod
    def from_json(cls, title: str, data: dict[str, Any]) -> GameRecord:
        return cls(
            title=title,
            files=[FileRule(p, t, w) for p, t, w in data.get("f", [])],
            has_registry=bool(data.get("r")),
            install_dirs=data.get("i", []),
            steam_ids=data.get("s", []),
            flatpak_id=data.get("p"),
            executables=data.get("e", []),
            cloud=data.get("c", {}),
        )


def record_from_manifest(title: str, entry: dict[str, Any]) -> GameRecord | None:
    """Convert one upstream manifest entry, or return None if it has no save data."""
    files = []
    for path, info in (entry.get("files") or {}).items():
        info = info or {}
        when = [{k: str(v) for k, v in cond.items() if k in ("os", "store")} for cond in info.get("when") or []]
        files.append(FileRule(path=str(path), tags=list(info.get("tags") or []), when=when))
    has_registry = bool(entry.get("registry"))
    if not files and not has_registry:
        return None
    ids = entry.get("id") or {}
    steam_ids = []
    if (entry.get("steam") or {}).get("id"):
        steam_ids.append(int(entry["steam"]["id"]))
    steam_ids += [int(x) for x in ids.get("steamExtra") or []]
    executables = sorted({PurePosixPath(p.replace("\\", "/")).name for p in (entry.get("launch") or {})})
    return GameRecord(
        title=title,
        files=files,
        has_registry=has_registry,
        install_dirs=list((entry.get("installDir") or {}).keys()),
        steam_ids=steam_ids,
        flatpak_id=ids.get("flatpak"),
        executables=[e for e in executables if e and "<" not in e],
        cloud={k: bool(v) for k, v in (entry.get("cloud") or {}).items() if v},
    )


class ManifestIndex:
    def __init__(self, games: dict[str, GameRecord], aliases: dict[str, str] | None = None):
        self.games = games
        self._by_steam: dict[int, str] = {}
        self._by_name: dict[str, str] = {}
        self._by_install_dir: dict[str, str] = {}
        for title, rec in games.items():
            self._by_name.setdefault(normalize_title(title), title)
            for sid in rec.steam_ids:
                self._by_steam.setdefault(sid, title)
            for d in rec.install_dirs:
                self._by_install_dir.setdefault(d.casefold(), title)
        for alias, target in (aliases or {}).items():
            if target in games:
                self._by_name.setdefault(normalize_title(alias), target)
        self.aliases = aliases or {}

    def __len__(self) -> int:
        return len(self.games)

    def get(self, title: str) -> GameRecord | None:
        return self.games.get(title)

    def by_steam_id(self, appid: int) -> GameRecord | None:
        title = self._by_steam.get(int(appid))
        return self.games[title] if title else None

    def by_name(self, name: str) -> GameRecord | None:
        title = self._by_name.get(normalize_title(name))
        return self.games[title] if title else None

    def by_install_dir(self, dirname: str) -> GameRecord | None:
        title = self._by_install_dir.get(dirname.casefold())
        return self.games[title] if title else None

    def find(self, *, steam_id: int | None = None, name: str | None = None,
             install_dir: str | None = None) -> GameRecord | None:
        if steam_id is not None and (rec := self.by_steam_id(steam_id)):
            return rec
        if install_dir and (rec := self.by_install_dir(install_dir)):
            return rec
        if name and (rec := self.by_name(name)):
            return rec
        return None

    # -- building / persistence ------------------------------------------

    @classmethod
    def from_manifest_data(cls, data: dict[str, Any]) -> ManifestIndex:
        games: dict[str, GameRecord] = {}
        aliases: dict[str, str] = {}
        for title, entry in (data or {}).items():
            if not isinstance(entry, dict):
                continue
            title = str(title)
            if entry.get("alias"):
                aliases[title] = str(entry["alias"])
                continue
            rec = record_from_manifest(title, entry)
            if rec:
                games[title] = rec
        return cls(games, aliases)

    @classmethod
    def from_yaml_file(cls, path: Path) -> ManifestIndex:
        import yaml

        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        with path.open("rb") as fh:
            return cls.from_manifest_data(yaml.load(fh, Loader=loader))

    def save(self, path: Path) -> None:
        payload = {
            "version": INDEX_VERSION,
            "games": {t: r.to_json() for t, r in self.games.items()},
            "aliases": self.aliases,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> ManifestIndex:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("version") != INDEX_VERSION:
            raise ValueError("manifest index version mismatch")
        games = {t: GameRecord.from_json(t, d) for t, d in payload["games"].items()}
        return cls(games, payload.get("aliases", {}))
