"""Windows tray app that starts, stops and watches the Jarvis bot running inside WSL.

Runs with the Windows Python (PySide6). The bot writes its PID to state/jarvis.pid and its
output to state/jarvis.log, both inside the WSL repo; this script only drives them via wsl.exe.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget

DISTRO = "Ubuntu"
REPO = "/home/felip/projetos/jarvis"
LOG_WIN = rf"\\wsl.localhost\{DISTRO}{REPO.replace('/', chr(92))}\state\jarvis.log"
CHECK_EVERY_MS = 5000
RESTART_DELAY_S = 5
MAX_RESTARTS = 5  # per RESTART_WINDOW_S, then give up and stay red
RESTART_WINDOW_S = 600
MAX_LOG_BYTES = 1_000_000
NO_WINDOW = subprocess.CREATE_NO_WINDOW

IS_ALIVE = 'grep -qs jarvis "/proc/$(cat state/jarvis.pid 2>/dev/null)/cmdline"'
START = (
    "mkdir -p state; "
    f'[ -f state/jarvis.log ] && [ "$(stat -c %s state/jarvis.log)" -gt {MAX_LOG_BYTES} ] && mv -f state/jarvis.log state/jarvis.log.1; '
    "echo $$ > state/jarvis.pid; exec .venv/bin/python -m jarvis >> state/jarvis.log 2>&1"
)
STOP = f'if {IS_ALIVE}; then kill "$(cat state/jarvis.pid)"; fi; rm -f state/jarvis.pid'

GREEN, GRAY, RED = "#2ecc71", "#7f8c8d", "#e74c3c"


def wsl(script: str, *, wait: bool = True, timeout: float = 15):
    cmd = ["wsl.exe", "-d", DISTRO, "--cd", REPO, "--", "bash", "-c", script]
    if not wait:
        return subprocess.Popen(cmd, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(cmd, creationflags=NO_WINDOW, capture_output=True, timeout=timeout)


def dot(color: str) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor("#1b1b1b"))
    painter.drawEllipse(6, 6, 52, 52)
    painter.end()
    return QIcon(pixmap)


class Tray:
    def __init__(self, app: QApplication):
        self.app = app
        self.wanted = False  # the user wants the bot up; set by Start, cleared by Stop
        self.launcher: subprocess.Popen | None = None
        self.restarts: list[float] = []
        self.gave_up = False
        self.alive = False

        self.icons = {"on": dot(GREEN), "off": dot(GRAY), "bad": dot(RED)}
        self.tray = QSystemTrayIcon(self.icons["off"])
        self.status_item = QAction("Verificando…")
        self.status_item.setEnabled(False)
        menu = QMenu()
        menu.addAction(self.status_item)
        menu.addSeparator()
        for label, handler in (("Iniciar", self.start), ("Parar", self.stop), ("Reiniciar", self.restart)):
            action = QAction(label)
            action.triggered.connect(handler)
            menu.addAction(action)
        menu.addSeparator()
        log = QAction("Ver log")
        log.triggered.connect(lambda: os.startfile(LOG_WIN))
        menu.addAction(log)
        quit_action = QAction("Sair (e parar o bot)")
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_click)
        self.panel = self.build_panel()
        self.tray.show()

        self.timer = QTimer()
        self.timer.timeout.connect(self.check)
        self.timer.start(CHECK_EVERY_MS)
        self.check()
        if self.alive:
            self.wanted = True  # adopt a bot that is already running
        else:
            self.start()

    def build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setWindowTitle("Jarvis")
        panel.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(panel)
        self.panel_status = QLabel("Verificando…")
        self.panel_status.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.panel_status)
        row = QHBoxLayout()
        for label, handler in (("Iniciar", self.start), ("Parar", self.stop), ("Reiniciar", self.restart)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        log = QPushButton("Ver log")
        log.clicked.connect(lambda: os.startfile(LOG_WIN))
        quit_button = QPushButton("Sair (e parar o bot)")
        quit_button.clicked.connect(self.quit)
        row.addWidget(log)
        row.addWidget(quit_button)
        layout.addLayout(row)
        return panel

    def on_click(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):  # left click
            if self.panel.isVisible():
                self.panel.hide()
                return
            screen = self.app.primaryScreen().availableGeometry()
            self.panel.adjustSize()
            self.panel.move(screen.right() - self.panel.width() - 12, screen.bottom() - self.panel.height() - 12)
            self.panel.show()
            self.panel.raise_()
            self.panel.activateWindow()

    def is_alive(self) -> bool:
        try:
            return wsl(IS_ALIVE).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return self.alive

    def render(self) -> None:
        if self.alive:
            state, text = "on", "Jarvis no ar"
        elif self.gave_up:
            state, text = "bad", "Jarvis caiu — reinício automático desistiu"
        elif self.wanted:
            state, text = "bad", "Jarvis fora do ar (reiniciando)"
        else:
            state, text = "off", "Jarvis parado"
        self.tray.setIcon(self.icons[state])
        self.tray.setToolTip(text)
        self.status_item.setText(text)
        self.panel_status.setText(text)

    def check(self) -> None:
        self.alive = self.is_alive()
        if self.alive:
            self.gave_up = False
        elif self.wanted and not self.gave_up:
            self.auto_restart()
        self.render()

    def auto_restart(self) -> None:
        now = time.monotonic()
        self.restarts = [t for t in self.restarts if now - t < RESTART_WINDOW_S]
        if len(self.restarts) >= MAX_RESTARTS:
            self.gave_up = True
            self.tray.showMessage("Jarvis", "O bot caiu várias vezes seguidas. Veja o log.", QSystemTrayIcon.Critical)
            return
        self.restarts.append(now)
        self.tray.showMessage("Jarvis", "O bot caiu e foi reiniciado.", QSystemTrayIcon.Warning)
        QTimer.singleShot(RESTART_DELAY_S * 1000, self.launch)

    def launch(self) -> None:
        if self.wanted and not self.is_alive():
            self.launcher = wsl(START, wait=False)

    def start(self) -> None:
        self.wanted, self.gave_up = True, False
        self.launch()
        QTimer.singleShot(2000, self.check)

    def stop(self) -> None:
        self.wanted = False
        wsl(STOP)
        self.check()

    def restart(self) -> None:
        self.stop()
        self.start()

    def quit(self) -> None:
        self.wanted = False
        self.timer.stop()
        wsl(STOP)
        self.tray.hide()
        self.app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock_dir = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation))
    lock = QLockFile(str(lock_dir / "jarvis_tray.lock"))
    if not lock.tryLock(100):
        return 0  # already running
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 1
    tray = Tray(app)
    if "--show" in sys.argv:
        tray.on_click(QSystemTrayIcon.Trigger)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
