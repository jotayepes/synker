"""End-to-end test against a real SMB server.

Runs only when SYNKER_TEST_SMB_HOST is set, e.g.:

    SYNKER_TEST_SMB_HOST=127.0.0.1 SYNKER_TEST_SMB_PORT=445 SYNKER_TEST_SMB_SHARE=saves \
    SYNKER_TEST_SMB_USER=user SYNKER_TEST_SMB_PASSWORD=pass pytest -m smb
"""

import os
import uuid

import pytest

from synker import engine as eng
from synker.config import SmbConfig
from synker.detect.scanner import Scanner
from synker.engine import Engine
from synker.storage.smb import SmbStorage

pytestmark = [
    pytest.mark.smb,
    pytest.mark.skipif(not os.environ.get("SYNKER_TEST_SMB_HOST"), reason="no SMB test server configured"),
]


@pytest.fixture
def smb_cfg():
    return SmbConfig(
        host=os.environ["SYNKER_TEST_SMB_HOST"],
        port=int(os.environ.get("SYNKER_TEST_SMB_PORT", "445")),
        share=os.environ.get("SYNKER_TEST_SMB_SHARE", "saves"),
        path=f"synker-test-{uuid.uuid4().hex[:8]}",
        username=os.environ.get("SYNKER_TEST_SMB_USER", ""),
    )


def test_smb_storage_primitives(smb_cfg):
    with SmbStorage(smb_cfg, os.environ.get("SYNKER_TEST_SMB_PASSWORD")) as s:
        assert s.test()["ok"]
        s.write_json("a/b/c.json", {"x": 1})
        assert s.read_json("a/b/c.json") == {"x": 1}
        assert s.list("a/b") == ["c.json"]
        s.delete("a")
        assert not s.exists("a")


def test_smb_backup_and_restore(home, cfg, index, smb_cfg):
    storage = SmbStorage(smb_cfg, os.environ.get("SYNKER_TEST_SMB_PASSWORD"))
    game = Scanner(cfg, index, home).find("proton-game")
    e = Engine(cfg, storage=storage)
    assert e.backup(game)["action"] == "created"
    assert e.status(game)["state"] == eng.SYNCED
    save = next(f.path for f in game.find_files(refresh=True) if f.path.name == "slot.dat")
    save.write_text("changed")
    e.restore(game)
    assert save.read_text() == "proton-save"
    storage.delete("")
    e.close()
