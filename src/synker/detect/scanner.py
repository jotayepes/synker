"""Find installed games and their save files.

Sources, in priority order (the first one to claim a title wins):

1. Steam apps (with their Proton prefix when present)
2. Non-Steam shortcuts in Steam (with their Proton prefix)
3. Heroic (Epic/GOG) and Lutris games (with their Wine prefix)
4. User-defined custom games
5. Emulators (built-in profiles)
6. A "full scan": every manifest game whose saves live in a well known
   folder (AppData, Documents, XDG dirs, extra Wine prefixes...), regardless
   of how it was installed.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from synker.config import Config
from synker.detect import emulators, launchers, placeholders
from synker.detect.globber import Globber, iter_files
from synker.detect.placeholders import HOME, WINDOWS_FAMILY, PathContext
from synker.detect.steam import SteamInstall, is_flatpak_root
from synker.manifest.index import FileRule, GameRecord, ManifestIndex, normalize_title

log = logging.getLogger(__name__)

ABS = "<abs>"
_GAME_SPECIFIC = ("<base>", "<root>", "<game>", "<storeGameId>")


def slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "game"


@dataclass
class SaveFile:
    path: Path
    portable: str
    kind: str
    size: int
    mtime: float


@dataclass
class Game:
    id: str
    title: str
    source: str
    store: str | None = None
    appid: int | None = None
    install_path: Path | None = None
    contexts: list[PathContext] = field(default_factory=list)
    rules: list[FileRule] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    cloud_covered: bool = False
    ignored: bool = False
    _files: list[SaveFile] | None = field(default=None, repr=False)

    def find_files(self, globber: Globber | None = None, refresh: bool = False) -> list[SaveFile]:
        if self._files is not None and not refresh:
            return self._files
        globber = globber or Globber()
        seen: set[str] = set()
        out: list[SaveFile] = []
        for ctx in self.contexts:
            for rule in self.rules:
                if not rule.applies(ctx.os_name, self.store):
                    continue
                for pattern in ctx.expand(rule.path):
                    for match in globber.glob(pattern, ctx.case_insensitive):
                        for f in iter_files(match):
                            key = os.path.realpath(f)
                            if key in seen:
                                continue
                            seen.add(key)
                            try:
                                st = f.stat()
                            except OSError:
                                continue
                            portable = ctx.to_portable(f) or ABS + str(f).replace("\\", "/")
                            out.append(SaveFile(f, portable, ctx.kind, st.st_size, st.st_mtime))
        out.sort(key=lambda s: s.portable)
        self._files = out
        return out

    def target_for(self, portable: str, kind: str | None = None) -> Path | None:
        """Where a backed-up file should be restored on this machine."""
        if portable.startswith(ABS):
            return Path(portable[len(ABS):])
        family = "windows" if kind in WINDOWS_FAMILY else "linux"

        def rank(ctx: PathContext) -> int:
            if ctx.kind == kind:
                return 0
            return 1 if (ctx.kind in WINDOWS_FAMILY) == (family == "windows") else 2

        for ctx in sorted(self.contexts, key=rank):
            if portable.startswith(HOME) and kind and rank(ctx) == 2:
                continue  # a Linux home is not a Windows profile folder
            if ctx.can_resolve(portable):
                return ctx.from_portable(portable)
        return None

    def to_dict(self, with_files: bool = False) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "store": self.store,
            "appid": self.appid,
            "install_path": str(self.install_path) if self.install_path else None,
            "contexts": [c.label for c in self.contexts],
            "cloud_covered": self.cloud_covered,
            "ignored": self.ignored,
        }
        if with_files:
            files = self.find_files()
            data["files"] = [{"path": str(f.path), "portable": f.portable, "size": f.size} for f in files]
            data["size"] = sum(f.size for f in files)
        return data


class Scanner:
    def __init__(self, cfg: Config, index: ManifestIndex, home: Path | None = None):
        from synker import paths

        self.cfg = cfg
        self.index = index
        self.home = home or paths.home_dir()
        self.globber = Globber()
        self.native = self._native_context()
        self.extra_prefixes = [placeholders.wine_context(Path(p).expanduser(), label=f"wine:{p}")
                               for p in cfg.wine_prefixes if (Path(p).expanduser() / "drive_c").is_dir()]
        self._steam: list[SteamInstall] | None = None

    def _native_context(self) -> PathContext:
        if sys.platform == "win32":
            return placeholders.windows_context()
        return placeholders.linux_context(self.home)

    @property
    def steam(self) -> list[SteamInstall]:
        if self._steam is None:
            self._steam = SteamInstall.discover(self.home, self.cfg.steam_roots)
        return self._steam

    # -- helpers ---------------------------------------------------------

    def _native_for(self, root: Path | None, base: Path | None, game_id: str | None = None) -> PathContext:
        ctx = self.native
        if root is not None and is_flatpak_root(root) and ctx.kind == "linux":
            sandbox = self.home / ".var" / "app" / "com.valvesoftware.Steam"
            ctx = placeholders.linux_context(self.home, extra_xdg=[
                (str(sandbox / ".local" / "share"), str(sandbox / ".config")),
                (str(sandbox / "data"), str(sandbox / "config")),
            ])
        return ctx.with_game(root=root, base=base, store_game_id=game_id)

    def _flatpak_contexts(self, record: GameRecord | None) -> list[PathContext]:
        if not record or not record.flatpak_id or self.native.kind != "linux":
            return []
        sandbox = self.home / ".var" / "app" / record.flatpak_id
        if not sandbox.is_dir():
            return []
        ctx = placeholders.linux_context(self.home, extra_xdg=[(str(sandbox / "data"), str(sandbox / "config"))])
        ctx.label = f"flatpak:{record.flatpak_id}"
        return [ctx]

    @staticmethod
    def _rules(record: GameRecord, wine: bool) -> list[FileRule]:
        rules = list(record.files)
        if wine and record.has_registry:
            rules.append(FileRule("<winePrefix>/user.reg", ["save"]))
        return rules

    def _is_ignored(self, game_id: str, title: str) -> bool:
        wanted = {x.casefold() for x in self.cfg.ignored_games}
        return game_id.casefold() in wanted or title.casefold() in wanted

    def _cloud_covered(self, record: GameRecord, store: str | None) -> bool:
        if self.cfg.backup.include_cloud_games:
            return False
        if store:
            return bool(record.cloud.get(store))
        return record.has_store_cloud

    # -- sources -------------------------------------------------------

    def _from_record(self, record: GameRecord, source: str, store: str | None, contexts: list[PathContext],
                     appid: int | None = None, install: Path | None = None,
                     processes: list[str] | None = None) -> Game:
        has_wine = any(c.kind == "wine" for c in contexts)
        game_id = slugify(record.title)
        procs = list(record.executables) + list(processes or [])
        return Game(
            id=game_id, title=record.title, source=source, store=store, appid=appid, install_path=install,
            contexts=contexts + self._flatpak_contexts(record), rules=self._rules(record, has_wine),
            processes=procs, cloud_covered=self._cloud_covered(record, store),
            ignored=self._is_ignored(game_id, record.title),
        )

    def steam_games(self) -> list[Game]:
        games = []
        for install in self.steam:
            for app in install.apps():
                record = self.index.find(steam_id=app.appid, install_dir=app.installdir, name=app.name)
                if not record:
                    continue
                contexts = [self._native_for(app.library, app.install_path, str(app.appid))]
                prefix = install.proton_prefix(app.appid)
                if prefix:
                    contexts.append(placeholders.wine_context(prefix, label=f"proton:{app.appid}").with_game(
                        root=app.library, base=app.install_path, store_game_id=str(app.appid)))
                games.append(self._from_record(record, "steam", "steam", contexts, app.appid, app.install_path))
            for sc in install.shortcuts():
                start = Path(sc.start_dir) if sc.start_dir else (Path(sc.exe).parent if sc.exe else None)
                record = self.index.find(name=sc.name, install_dir=start.name if start else None)
                if not record:
                    continue
                contexts = [self._native_for(None, start)]
                prefix = install.proton_prefix(sc.appid)
                if prefix:
                    contexts.append(placeholders.wine_context(prefix, label=f"proton:{sc.appid}").with_game(base=start))
                exe = [Path(sc.exe).name] if sc.exe else []
                games.append(self._from_record(record, "steam-shortcut", None, contexts, sc.appid, start, exe))
        return games

    def launcher_games(self) -> list[Game]:
        if sys.platform == "win32":
            found = launchers.heroic_games(self.home)
        else:
            found = launchers.heroic_games(self.home) + launchers.lutris_games(self.home)
        games = []
        for lg in found:
            record = self.index.find(name=lg.name,
                                     install_dir=lg.install_path.name if lg.install_path else None)
            if not record:
                continue
            contexts = [self._native_for(None, lg.install_path)]
            if lg.prefix:
                contexts.append(placeholders.wine_context(lg.prefix, label=f"{lg.source}:{lg.prefix}")
                                .with_game(base=lg.install_path))
            games.append(self._from_record(record, lg.source, lg.store, contexts, install=lg.install_path))
        return games

    def custom_games(self) -> list[Game]:
        games = []
        for cg in self.cfg.custom_games:
            gid = f"custom-{slugify(cg.name)}"
            rules = []
            for p in cg.paths:
                p = p.replace("\\", "/")
                if p.startswith("~"):
                    p = "<home>" + p[1:]
                rules.append(FileRule(p))
            games.append(Game(id=gid, title=cg.name, source="custom", contexts=[self.native] + self.extra_prefixes,
                              rules=rules, processes=list(cg.processes), ignored=self._is_ignored(gid, cg.name)))
        return games

    def emulator_games(self) -> list[Game]:
        games = []
        win = self.native.kind == "windows"
        for prof in emulators.PROFILES:
            if prof.id in self.cfg.disabled_emulators:
                continue
            templates = prof.windows if win else prof.linux
            if not templates:
                continue
            game = Game(id=prof.game_id, title=prof.name, source="emulator", contexts=[self.native],
                        rules=[FileRule(t) for t in templates], processes=list(prof.processes),
                        ignored=self._is_ignored(prof.game_id, prof.name))
            if game.find_files(self.globber):
                games.append(game)
        return games

    def full_scan(self, skip_titles: set[str]) -> list[Game]:
        contexts = [self.native] + self.extra_prefixes
        games = []
        for title, record in self.index.games.items():
            if title in skip_titles:
                continue
            rules = [r for r in record.files
                     if not any(ph in r.path for ph in _GAME_SPECIFIC)]
            if not rules:
                continue
            game = self._from_record(record, "detected", None, list(contexts))
            game.rules = rules
            if game.find_files(self.globber):
                games.append(game)
        return games

    # -- entry point ---------------------------------------------------

    def scan(self, full: bool = True) -> list[Game]:
        games: dict[str, Game] = {}
        for game in self.steam_games() + self.launcher_games() + self.custom_games() + self.emulator_games():
            games.setdefault(game.id, game)
        if full:
            claimed = {g.title for g in games.values()}
            for game in self.full_scan(claimed):
                games.setdefault(game.id, game)
        return sorted(games.values(), key=lambda g: normalize_title(g.title))

    def find(self, ref: str | None = None, *, appid: int | None = None, name: str | None = None) -> Game | None:
        """Locate one game by id, title, Steam appid or name. Tries a quick scan first."""
        for full in (False, True):
            games = self.scan(full=full)
            for g in games:
                if appid is not None and g.appid == appid:
                    return g
            for key in [k for k in (ref, name) if k]:
                for g in games:
                    if key == g.id or normalize_title(key) == normalize_title(g.title):
                        return g
                if key.isdigit():
                    for g in games:
                        if g.appid == int(key):
                            return g
        return None
