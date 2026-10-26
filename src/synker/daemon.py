"""Desktop daemon: watches running games and backs them up / restores them automatically."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from synker import config as config_mod
from synker.detect.scanner import Game, Scanner
from synker.engine import Engine
from synker.manifest import fetch
from synker.watcher import ProcessWatcher

log = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], None]


def desktop_notify(title: str, body: str) -> None:
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Synker", title, body], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe_event(kind: str, data: dict[str, Any]) -> str | None:
    title = data.get("title", data.get("game_id", "?"))
    result = data.get("result") or {}
    action = result.get("action")
    if kind == "started" and action == "restored":
        return f"{title}: saves restored from the NAS"
    if kind == "started" and action == "ask":
        return f"{title}: save conflict between this device and the NAS, open Synker to choose"
    if kind == "started" and action == "restore-available":
        return f"{title}: a newer save is available on the NAS"
    if kind == "stopped" and action == "created":
        return f"{title}: saves backed up"
    if kind == "stopped" and action == "queued":
        return f"{title}: NAS unreachable, backup queued"
    if kind == "error":
        return f"{title}: {data.get('error')}"
    return None


class Daemon:
    def __init__(self, cfg: config_mod.Config | None = None, poll_seconds: float = 5,
                 rescan_seconds: float = 900, on_event: EventCallback | None = None):
        self.cfg = cfg or config_mod.load()
        self.poll = poll_seconds
        self.rescan_seconds = rescan_seconds
        self.on_event = on_event
        self.stop_event = threading.Event()
        self.running: dict[str, dict[str, float]] = {}
        self.games: dict[str, Game] = {}
        self._last_scan = 0.0
        self._last_flush = 0.0
        self.watcher = ProcessWatcher([])

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        log.info("%s %s", kind, data)
        if self.on_event:
            self.on_event(kind, data)
        else:
            msg = describe_event(kind, data)
            if msg:
                desktop_notify("Synker", msg)

    def rescan(self) -> None:
        index = fetch.load_index(self.cfg.manifest_url)
        games = Scanner(self.cfg, index).scan()
        self.games = {g.id: g for g in games if not g.ignored and not g.cloud_covered}
        self.watcher.set_games(list(self.games.values()))
        self._last_scan = time.time()
        log.info("watching %d games", len(self.games))

    def _with_engine(self, fn: Callable[[Engine], dict[str, Any]], kind: str, game: Game) -> None:
        engine = Engine(self.cfg)
        try:
            result = fn(engine)
            self.emit(kind, {"game_id": game.id, "title": game.title, "result": result})
        except Exception as exc:  # keep the daemon alive whatever happens
            log.exception("%s failed for %s", kind, game.id)
            self.emit("error", {"game_id": game.id, "title": game.title, "error": str(exc)})
        finally:
            engine.close()

    def tick(self) -> None:
        now = time.time()
        if now - self._last_scan > self.rescan_seconds:
            self.rescan()
        current = self.watcher.running()
        for gid in current - set(self.running):
            game = self.games[gid]
            self.running[gid] = {"started": now, "last_backup": now}
            self._with_engine(lambda e, g=game: e.pre_launch(g), "started", game)
        periodic = self.cfg.backup.periodic_minutes * 60
        for gid in current & set(self.running):
            info = self.running[gid]
            if periodic and now - info["last_backup"] >= periodic:
                info["last_backup"] = now
                game = self.games[gid]
                self._with_engine(lambda e, g=game: e.post_exit(g, reason="periodic"), "periodic", game)
        for gid in set(self.running) - current:
            del self.running[gid]
            game = self.games.get(gid)
            if game and self.cfg.backup.backup_on_exit:
                self._with_engine(lambda e, g=game: e.post_exit(g), "stopped", game)
        if now - self._last_flush > 300:
            self._last_flush = now
            engine = Engine(self.cfg)
            try:
                engine.flush_queue()
            except Exception as exc:
                log.debug("queue flush failed: %s", exc)
            finally:
                engine.close()

    def run(self) -> None:
        log.info("synker daemon started")
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("daemon tick failed")
            self.stop_event.wait(self.poll)
        log.info("synker daemon stopped")

    def stop(self) -> None:
        self.stop_event.set()
