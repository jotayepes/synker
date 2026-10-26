"""Desktop GUI (PySide6): game list, backup history/restore, settings and a tray icon running the daemon."""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from synker import autostart, secrets
from synker import config as config_mod
from synker.daemon import Daemon, describe_event
from synker.detect.scanner import Game, Scanner
from synker.engine import Engine
from synker.gui.i18n import tr
from synker.manifest import fetch
from synker.storage import open_storage

log = logging.getLogger(__name__)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


# -- background work ---------------------------------------------------------


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:
            log.debug("task failed: %s", traceback.format_exc())
            self.signals.failed.emit(str(exc))
        else:
            self.signals.done.emit(result)


class Bridge(QObject):
    """Forwards daemon events (from its thread) to the GUI thread."""

    event = Signal(str, dict)


# -- dialogs -----------------------------------------------------------------


class BackupsDialog(QDialog):
    def __init__(self, window: MainWindow, game: Game):
        super().__init__(window)
        self.window_ = window
        self.game = game
        self.setWindowTitle(game.title)
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("Date"), tr("Device"), tr("Reason"), tr("Files"), tr("Size"),
                                              tr("Locked")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for label, slot in ((tr("Restore"), self.restore), (tr("Lock / unlock"), self.toggle_lock),
                            (tr("Undo last restore"), self.undo)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()
        close = QPushButton("OK")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.backups: list[dict] = []
        self.reload()

    def reload(self) -> None:
        def work():
            engine = Engine(self.window_.cfg)
            try:
                return engine.list_backups(self.game.id)
            finally:
                engine.close()

        self.window_.run(work, self._show)

    def _show(self, backups: list[dict]) -> None:
        self.backups = backups
        self.table.setRowCount(len(backups))
        for row, b in enumerate(backups):
            values = [b["created_iso"].replace("T", " ")[:19], b["device"], tr(b["reason"]), str(b["files"]),
                      human_size(b["size"]), "✔" if b.get("locked") else ""]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def _selected(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        return self.backups[rows[0].row()] if rows else None

    def restore(self) -> None:
        b = self._selected()
        if not b:
            return
        if QMessageBox.question(self, tr("Restore"),
                                tr("Restore this backup? Current saves are kept in a local snapshot.")) \
                != QMessageBox.StandardButton.Yes:
            return

        def work():
            engine = Engine(self.window_.cfg)
            try:
                return engine.restore(self.game, b["id"])
            finally:
                engine.close()

        self.window_.run(work, lambda r: self.window_.log_line(f"{self.game.title}: restored {b['id']}"
                                                                f" ({len(r['files'])} files)"))

    def toggle_lock(self) -> None:
        b = self._selected()
        if not b:
            return

        def work():
            engine = Engine(self.window_.cfg)
            try:
                return engine.repo().set_locked(self.game.id, b["id"], not b.get("locked"))
            finally:
                engine.close()

        self.window_.run(work, lambda _r: self.reload())

    def undo(self) -> None:
        def work():
            engine = Engine(self.window_.cfg)
            try:
                return engine.undo_restore(self.game)
            finally:
                engine.close()

        self.window_.run(work, lambda _r: self.window_.log_line(f"{self.game.title}: {tr('Undo last restore')}"))


class CustomGameDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(tr("Add custom game…"))
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.paths = QPlainTextEdit()
        self.processes = QLineEdit()
        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Paths (one per line, placeholders like <home> allowed)"), self.paths)
        form.addRow(tr("Process names (comma separated, optional)"), self.processes)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def value(self) -> config_mod.CustomGame:
        return config_mod.CustomGame(
            self.name.text().strip(),
            [p.strip() for p in self.paths.toPlainText().splitlines() if p.strip()],
            [p.strip() for p in self.processes.text().split(",") if p.strip()],
        )


# -- main window -------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = config_mod.load()
        self.pool = QThreadPool.globalInstance()
        self._tasks: set[_Task] = set()
        self.games: list[Game] = []
        self.daemon: Daemon | None = None
        self.daemon_thread: threading.Thread | None = None
        self.bridge = Bridge()
        self.bridge.event.connect(self._on_daemon_event)

        self.setWindowTitle("Synker")
        self.resize(980, 600)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
        self.setWindowIcon(icon)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._games_tab(), tr("Games"))
        self.tabs.addTab(self._settings_tab(), tr("Settings"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, tr("Log"))
        self.statusBar()
        self._tray(icon)
        self._load_settings()

        if not self.cfg.is_storage_configured():
            self.tabs.setCurrentIndex(1)
            self.statusBar().showMessage(tr("Configure where to store backups first."))
        else:
            self.refresh()
            self.set_daemon(True)

    # -- infrastructure ----------------------------------------------------

    def run(self, fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None) -> None:
        task = _Task(fn)
        self._tasks.add(task)
        self.statusBar().showMessage(tr("Working…"))

        def done(result):
            self._tasks.discard(task)
            self.statusBar().clearMessage()
            if on_done:
                on_done(result)

        def failed(message):
            self._tasks.discard(task)
            self.statusBar().clearMessage()
            self.log_line(f"{tr('Error')}: {message}")
            QMessageBox.warning(self, tr("Error"), message)

        task.signals.done.connect(done)
        task.signals.failed.connect(failed)
        self.pool.start(task)

    def log_line(self, text: str) -> None:
        from datetime import datetime

        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    # -- games tab -----------------------------------------------------------

    def _games_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("Game"), tr("Source"), tr("State"), tr("Files"),
                                              tr("Latest backup")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _i: self.show_backups())
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, slot in ((tr("Refresh"), self.refresh), (tr("Back up selected"), self.backup_selected),
                            (tr("Back up all"), self.backup_all), (tr("Backups / restore…"), self.show_backups),
                            (tr("Ignore"), self.ignore_selected), (tr("Add custom game…"), self.add_custom)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        return w

    def refresh(self) -> None:
        cfg = self.cfg

        def work():
            index = fetch.load_index(cfg.manifest_url)
            games = [g for g in Scanner(cfg, index).scan() if not g.ignored and not g.cloud_covered]
            statuses = {}
            if cfg.is_storage_configured():
                engine = Engine(cfg)
                try:
                    for g in games:
                        statuses[g.id] = engine.status(g)
                finally:
                    engine.close()
            return games, statuses

        self.run(work, self._show_games)

    def _show_games(self, result) -> None:
        games, statuses = result
        # Hide installed games that have no saves, neither here nor on the NAS.
        games = [g for g in games if g.find_files() or statuses.get(g.id, {}).get("state") not in (None, "empty")]
        self.games = games
        self.table.setRowCount(len(games))
        for row, g in enumerate(games):
            st = statuses.get(g.id, {})
            latest = (st.get("latest") or {}).get("created_iso", "")
            files = g.find_files()
            values = [g.title, tr(g.source), tr(st.get("state", "")), f"{len(files)} · {human_size(sum(f.size for f in files))}",
                      latest.replace("T", " ")[:16]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setToolTip("\n".join(str(f.path) for f in files[:30]))
                self.table.setItem(row, col, item)

    def _selected_game(self) -> Game | None:
        rows = self.table.selectionModel().selectedRows()
        return self.games[rows[0].row()] if rows else None

    def backup_selected(self) -> None:
        game = self._selected_game()
        if game:
            self._backup([game])

    def backup_all(self) -> None:
        self._backup(list(self.games))

    def _backup(self, games: list[Game]) -> None:
        cfg = self.cfg

        def work():
            engine = Engine(cfg)
            try:
                return [(g.title, engine.backup(g)) for g in games]
            finally:
                engine.close()

        def done(results):
            for title, r in results:
                self.log_line(f"{title}: {r['action']}")
            self.refresh()

        self.run(work, done)

    def show_backups(self) -> None:
        game = self._selected_game()
        if game:
            BackupsDialog(self, game).exec()
            self.refresh()

    def ignore_selected(self) -> None:
        game = self._selected_game()
        if game:
            self.cfg.ignored_games.append(game.id)
            config_mod.save(self.cfg)
            self.refresh()

    def add_custom(self) -> None:
        dlg = CustomGameDialog(self)
        if dlg.exec() and dlg.value().name and dlg.value().paths:
            game = dlg.value()
            self.cfg.custom_games = [g for g in self.cfg.custom_games if g.name != game.name] + [game]
            config_mod.save(self.cfg)
            self.refresh()

    # -- settings tab --------------------------------------------------------

    def _settings_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.f_device = QLineEdit()
        self.f_type = QComboBox()
        self.f_type.addItem(tr("NAS (SMB)"), "smb")
        self.f_type.addItem(tr("Local / mounted folder"), "local")
        self.f_type.currentIndexChanged.connect(self._toggle_storage_fields)
        self.f_path = QLineEdit()
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.f_path)
        path_row.addWidget(browse)
        self.path_widget = QWidget()
        self.path_widget.setLayout(path_row)
        self.f_host = QLineEdit()
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_share = QLineEdit()
        self.f_smbpath = QLineEdit()
        self.f_user = QLineEdit()
        self.f_password = QLineEdit()
        self.f_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_password.setPlaceholderText(tr("(unchanged)"))
        self.f_domain = QLineEdit()
        self.f_encrypt = QCheckBox(tr("Encrypt (SMB3)"))
        self.f_auto_restore = QCheckBox(tr("Restore newer saves when a game starts"))
        self.f_on_exit = QCheckBox(tr("Back up when a game closes"))
        self.f_periodic = QSpinBox()
        self.f_periodic.setRange(0, 240)
        self.f_cloud = QCheckBox(tr("Include games that have store cloud saves"))
        self.f_keep = QSpinBox()
        self.f_keep.setRange(1, 1000)
        self.f_daily = QSpinBox()
        self.f_daily.setRange(0, 3650)
        self.f_policy = QComboBox()
        for value, label in (("ask", tr("Ask")), ("prefer-remote", tr("Use NAS version")),
                             ("prefer-local", tr("Keep this device's version")), ("keep-both", tr("Keep both"))):
            self.f_policy.addItem(label, value)

        form.addRow(tr("Device name"), self.f_device)
        form.addRow(tr("Storage type"), self.f_type)
        form.addRow(tr("Folder"), self.path_widget)
        self.smb_rows = [(tr("Host or IP"), self.f_host), (tr("Port"), self.f_port), (tr("Share"), self.f_share),
                         (tr("Folder in share"), self.f_smbpath), (tr("User"), self.f_user),
                         (tr("Password"), self.f_password), (tr("Domain"), self.f_domain), ("", self.f_encrypt)]
        for label, widget in self.smb_rows:
            form.addRow(label, widget)
        form.addRow("", self.f_auto_restore)
        form.addRow("", self.f_on_exit)
        form.addRow(tr("Periodic backup while playing (minutes, 0 = off)"), self.f_periodic)
        form.addRow("", self.f_cloud)
        form.addRow(tr("Backups kept"), self.f_keep)
        form.addRow(tr("Daily backups kept (days)"), self.f_daily)
        form.addRow(tr("On conflict"), self.f_policy)
        buttons = QHBoxLayout()
        for label, slot in ((tr("Save"), self.save_settings), (tr("Test connection"), self.test_connection),
                            (tr("Update game database"), self.update_manifest)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        self.f_autostart = QCheckBox(tr("Start with the session"))
        self.f_autostart.toggled.connect(self._set_autostart)
        buttons.addWidget(self.f_autostart)
        buttons.addStretch()
        form.addRow(buttons)
        self.form = form
        return w

    def _toggle_storage_fields(self) -> None:
        smb = self.f_type.currentData() == "smb"
        self.form.setRowVisible(self.path_widget, not smb)
        for _label, widget in self.smb_rows:
            self.form.setRowVisible(widget, smb)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Folder"), self.f_path.text())
        if folder:
            self.f_path.setText(folder)

    def _load_settings(self) -> None:
        c = self.cfg
        self.f_device.setText(c.device_name)
        self.f_type.setCurrentIndex(0 if c.storage.type == "smb" else 1)
        self.f_path.setText(c.storage.path)
        smb = c.storage.smb
        self.f_host.setText(smb.host)
        self.f_port.setValue(smb.port)
        self.f_share.setText(smb.share)
        self.f_smbpath.setText(smb.path)
        self.f_user.setText(smb.username)
        self.f_domain.setText(smb.domain)
        self.f_encrypt.setChecked(smb.encrypt)
        b = c.backup
        self.f_auto_restore.setChecked(b.auto_restore)
        self.f_on_exit.setChecked(b.backup_on_exit)
        self.f_periodic.setValue(b.periodic_minutes)
        self.f_cloud.setChecked(b.include_cloud_games)
        self.f_keep.setValue(b.keep_last)
        self.f_daily.setValue(b.keep_daily_days)
        self.f_policy.setCurrentIndex(max(0, self.f_policy.findData(b.conflict_policy)))
        self.f_autostart.blockSignals(True)
        self.f_autostart.setChecked(autostart.is_installed())
        self.f_autostart.blockSignals(False)
        self._toggle_storage_fields()

    def save_settings(self) -> bool:
        c = self.cfg
        c.device_name = self.f_device.text().strip() or c.device_name
        c.storage.type = self.f_type.currentData()
        c.storage.path = self.f_path.text().strip()
        smb = c.storage.smb
        smb.host, smb.port, smb.share = self.f_host.text().strip(), self.f_port.value(), self.f_share.text().strip()
        smb.path, smb.username = self.f_smbpath.text().strip(), self.f_user.text().strip()
        smb.domain, smb.encrypt = self.f_domain.text().strip(), self.f_encrypt.isChecked()
        b = c.backup
        b.auto_restore, b.backup_on_exit = self.f_auto_restore.isChecked(), self.f_on_exit.isChecked()
        b.periodic_minutes, b.include_cloud_games = self.f_periodic.value(), self.f_cloud.isChecked()
        b.keep_last, b.keep_daily_days = self.f_keep.value(), self.f_daily.value()
        b.conflict_policy = self.f_policy.currentData()
        try:
            config_mod.save(c)
            if self.f_password.text():
                secrets.set_password(secrets.smb_account(smb.host, smb.username), self.f_password.text())
                self.f_password.clear()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Error"), str(exc))
            return False
        self.statusBar().showMessage(tr("Saved"), 3000)
        if self.daemon:
            self.set_daemon(False)
            self.set_daemon(True)
        return True

    def test_connection(self) -> None:
        if not self.save_settings():
            return
        cfg = self.cfg

        def work():
            with open_storage(cfg) as storage:
                return storage.test()

        self.run(work, lambda r: QMessageBox.information(self, "Synker", f"{tr('Connection OK')}: {r['location']}"))

    def update_manifest(self) -> None:
        url = self.cfg.manifest_url
        self.run(lambda: fetch.update(url, force=True), lambda r: (self.log_line(f"manifest: {vars(r)}"),
                                                                   self.refresh()))

    def _set_autostart(self, enabled: bool) -> None:
        try:
            path = autostart.install(gui=True) if enabled else autostart.uninstall()
            self.log_line(f"autostart: {path}")
        except OSError as exc:
            QMessageBox.warning(self, tr("Error"), str(exc))

    # -- daemon & tray -------------------------------------------------------

    def _tray(self, icon: QIcon) -> None:
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        show = QAction(tr("Show"), self)
        show.triggered.connect(self.showNormal)
        self.daemon_action = QAction(tr("Automatic backups (daemon)"), self, checkable=True)
        self.daemon_action.toggled.connect(self.set_daemon)
        quit_action = QAction(tr("Quit"), self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(show)
        menu.addAction(self.daemon_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal()
                                    if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def set_daemon(self, enabled: bool) -> None:
        if enabled and self.daemon is None and self.cfg.is_storage_configured():
            self.daemon = Daemon(self.cfg, on_event=lambda k, d: self.bridge.event.emit(k, d))
            self.daemon_thread = threading.Thread(target=self.daemon.run, daemon=True, name="synker-daemon")
            self.daemon_thread.start()
            self.log_line("daemon started")
        elif not enabled and self.daemon is not None:
            self.daemon.stop()
            self.daemon = None
            self.log_line("daemon stopped")
        self.daemon_action.blockSignals(True)
        self.daemon_action.setChecked(self.daemon is not None)
        self.daemon_action.blockSignals(False)

    def _on_daemon_event(self, kind: str, data: dict) -> None:
        message = describe_event(kind, data)
        self.log_line(message or f"{kind}: {data.get('title', '')}")
        if message and self.tray.isVisible():
            self.tray.showMessage("Synker", message)
        if kind in ("stopped", "started"):
            self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.tray.isVisible() and self.daemon is not None:
            self.hide()
            event.ignore()
        else:
            self.quit()

    def quit(self) -> None:
        self.set_daemon(False)
        QApplication.quit()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("Synker")
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    if "--minimized" not in sys.argv:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
