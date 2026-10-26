import os

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_gui_lists_and_backs_up(home, cfg, index, monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication

    from synker import config as config_mod
    from synker.gui.app import MainWindow
    from synker.manifest import fetch

    index.save(fetch.index_path())
    cfg.manifest_url = ""
    config_mod.save(cfg)
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.set_daemon(False)
    pool = QThreadPool.globalInstance()

    def settle():
        for _ in range(4):
            pool.waitForDone(20000)
            app.processEvents()

    settle()
    titles = [w.table.item(r, 0).text() for r in range(w.table.rowCount())]
    assert "Native Game" in titles
    w.table.selectRow(titles.index("Native Game"))
    w.backup_selected()
    settle()
    assert "Native Game: created" in w.log_view.toPlainText()
    w.close()
