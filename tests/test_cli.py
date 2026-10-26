import json

from synker import cli
from synker.manifest import fetch


def test_cli_end_to_end(home, index, tmp_path, capsys, monkeypatch):
    index.save(fetch.index_path())
    nas = tmp_path / "nas"
    assert cli.main(["--json", "config", "set", "storage.path", str(nas)]) == 0
    capsys.readouterr()

    assert cli.main(["--json", "--no-manifest-update", "scan"]) == 0
    games = {g["id"] for g in json.loads(capsys.readouterr().out)}
    assert "native-game" in games and "cloud-game" not in games

    assert cli.main(["--json", "--no-manifest-update", "backup", "--appid", "2000"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["action"] == "created"

    assert cli.main(["--json", "--no-manifest-update", "list", "native-game"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1

    assert cli.main(["--json", "--no-manifest-update", "status", "native-game"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["state"] == "synced"

    assert cli.main(["--json", "storage-test"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(["--json", "--no-manifest-update", "restore", "nope"]) == 1
    assert "error" in json.loads(capsys.readouterr().out)


def test_watcher_matches(home, cfg, index):
    from synker.detect.scanner import Scanner
    from synker.watcher import ProcessWatcher

    w = ProcessWatcher(Scanner(cfg, index, home).scan())
    assert w.match("reaper", "/x/reaper", ["reaper", "SteamLaunch", "AppId=1000", "--", "x"], "") == "proton-game"
    assert w.match("retroarch", "/usr/bin/retroarch", ["retroarch"], "/") == "emu-retroarch"
    assert w.match("bash", "/bin/bash", ["bash"], "/") is None
