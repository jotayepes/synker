import time

import pytest

from synker import engine as eng
from synker.detect.scanner import Scanner
from synker.engine import Engine
from synker.repository import BackupEntry
from synker.retention import select_for_deletion
from synker.storage import LocalStorage


def _game(cfg, index, home, gid):
    return Scanner(cfg, index, home).find(gid)


def test_backup_restore_roundtrip(home, cfg, index):
    game = _game(cfg, index, home, "proton-game")
    e = Engine(cfg)
    first = e.backup(game)
    assert first["action"] == "created"
    assert e.backup(game)["action"] == "unchanged"
    assert e.status(game)["state"] == eng.SYNCED

    save = next(f.path for f in game.find_files(refresh=True) if f.path.name == "slot.dat")
    save.write_text("modified")
    assert e.status(game)["state"] == eng.LOCAL_NEWER
    second = e.backup(game)
    assert second["action"] == "created"

    result = e.restore(game, first["backup"]["id"])
    assert not result["unresolved"]
    assert save.read_text() == "proton-save"
    assert result["snapshot"]
    e.undo_restore(game)
    assert save.read_text() == "modified"
    assert len(e.list_backups(game.id)) == 2


def test_restore_to_other_device(home, cfg, index, tmp_path, monkeypatch):
    """A save backed up from one prefix is restored into another machine's prefix."""
    game = _game(cfg, index, home, "proton-game")
    Engine(cfg).backup(game)
    # Simulate a second device: wipe local saves and the device state.
    for f in game.find_files(refresh=True):
        f.path.unlink()
    monkeypatch.setenv("SYNKER_DATA_DIR", str(tmp_path / "data2"))
    cfg.device_name = "deck"
    e2 = Engine(cfg)
    game = _game(cfg, index, home, "proton-game")
    status = e2.status(game)
    assert status["state"] == eng.REMOTE_ONLY
    res = e2.pre_launch(game)
    assert res["action"] == "restored"
    assert {f.path.read_text() for f in game.find_files(refresh=True)} == {"proton-save", "base-save"}


def test_conflict_and_policies(home, cfg, index, tmp_path, monkeypatch):
    game = _game(cfg, index, home, "native-game")
    Engine(cfg).backup(game)
    save = game.find_files()[0].path

    # Another device pushes a new version.
    monkeypatch.setenv("SYNKER_DATA_DIR", str(tmp_path / "other"))
    save.write_text("other device")
    Engine(cfg).backup(game)
    monkeypatch.setenv("SYNKER_DATA_DIR", str(tmp_path / "data"))

    # Back on this device, the local file is still the old one -> remote newer.
    save.write_text("native-1")
    e = Engine(cfg)
    assert e.status(game)["state"] == eng.REMOTE_NEWER

    # Change it locally too -> conflict.
    save.write_text("local change")
    assert e.status(game)["state"] == eng.CONFLICT
    assert e.pre_launch(game)["action"] == "ask"
    res = e.pre_launch(game, policy="keep-both")
    assert res["action"] == "restored"
    assert save.read_text() == "other device"
    reasons = [b["reason"] for b in e.list_backups(game.id)]
    assert "conflict-copy" in reasons


def test_first_exit_on_new_device_does_not_override(home, cfg, index, tmp_path, monkeypatch):
    game = _game(cfg, index, home, "native-game")
    Engine(cfg).backup(game)
    monkeypatch.setenv("SYNKER_DATA_DIR", str(tmp_path / "fresh"))
    game.find_files()[0].path.write_text("fresh new game")
    e = Engine(cfg)
    res = e.post_exit(game)
    assert res["backup"]["reason"] == "conflict-copy"
    latest = e.status(game)["latest"]
    assert latest["reason"] != "conflict-copy"


def test_offline_queue(home, cfg, index, tmp_path):
    game = _game(cfg, index, home, "native-game")
    nas = tmp_path / "nas"
    nas.write_text("not a directory")  # makes the storage unusable
    e = Engine(cfg)
    res = e.backup(game)
    assert res["action"] == "queued"
    assert e.backup(game)["action"] == "unchanged"
    nas.unlink()
    flushed = Engine(cfg).flush_queue()
    assert len(flushed["uploaded"]) == 1
    assert len(Engine(cfg).list_backups(game.id)) == 1


def _entry(i, created, locked=False):
    return BackupEntry(id=str(i), file=f"{i}.zip", created=created, device="d", os="linux", reason="exit",
                       hash=str(i), size=1, files=1, locked=locked)


def test_retention():
    now = time.time()
    entries = [_entry(i, now - i * 3600 * 6) for i in range(40)]  # every 6h for 10 days
    entries.append(_entry(99, now - 90 * 86400, locked=True))
    doomed = {b.id for b in select_for_deletion(entries, keep_last=5, keep_daily_days=3, now=now)}
    kept = {b.id for b in entries} - doomed
    assert {"0", "1", "2", "3", "4", "99"} <= kept
    assert len(kept) <= 5 + 4 + 1
    assert "39" in doomed


def test_local_storage_rejects_traversal(tmp_path):
    from synker.storage import StorageError

    s = LocalStorage(tmp_path)
    with pytest.raises(StorageError):
        s.write_bytes("../evil", b"x")
    assert s.test()["ok"]
