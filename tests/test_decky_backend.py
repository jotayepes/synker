"""Exercise decky/main.py with a stub `decky` module and a shim synker binary."""

import asyncio
import importlib.util
import logging
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from synker.manifest import fetch

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def plugin(home, index, tmp_path, monkeypatch):
    index.save(fetch.index_path())
    plugin_dir = tmp_path / "plugins" / "Synker"
    (plugin_dir / "bin").mkdir(parents=True)
    shim = plugin_dir / "bin" / "synker"
    src = ROOT / "src"
    shim.write_text(f"#!/bin/sh\nPYTHONPATH={src} exec {sys.executable} -m synker \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    events = []
    decky = types.ModuleType("decky")
    decky.DECKY_PLUGIN_DIR = str(plugin_dir)
    decky.DECKY_USER_HOME = str(home)
    decky.DECKY_PLUGIN_SETTINGS_DIR = os.environ["SYNKER_CONFIG_DIR"]
    decky.DECKY_PLUGIN_RUNTIME_DIR = os.environ["SYNKER_DATA_DIR"]
    decky.logger = logging.getLogger("decky-test")

    async def emit(*args):
        events.append(args)

    decky.emit = emit
    monkeypatch.setitem(sys.modules, "decky", decky)
    spec = importlib.util.spec_from_file_location("synker_decky_main", ROOT / "decky" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    p = module.Plugin()
    p.events = events
    return p


def test_decky_flow(plugin, tmp_path):
    async def flow():
        cfg = await plugin.set_config({"storage.type": "local", "storage.path": str(tmp_path / "nas"),
                                       "backup.periodic_minutes": 5})
        assert cfg["backup"]["periodic_minutes"] == 5
        assert (await plugin.test_storage())["ok"]
        started = await plugin.game_started(2000, "Native Game")
        assert started["state"] == "local-only"
        stopped = await plugin.game_stopped(2000)
        assert stopped["action"] == "created"
        assert [e[1] for e in plugin.events] == ["started", "stopped"]
        assert (await plugin.game_started(999999, "Unknown"))["action"] == "unknown-game"
        statuses = await plugin.status()
        assert any(s["game"]["id"] == "native-game" and s["state"] == "synced" for s in statuses)
        backups = await plugin.list_backups("native-game")
        assert len(backups) == 1
        restored = await plugin.restore("native-game", backups[0]["id"])
        assert restored["action"] == "restored"

    asyncio.run(flow())
