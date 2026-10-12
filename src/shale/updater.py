"""Shale Update: a small window that updates the whole system with one click."""

import json
import subprocess
import sys

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from . import theme

HELPER = "/usr/lib/shale/shale-update-helper"


class Updater(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shale Update")
        self.setWindowIcon(QIcon.fromTheme("shale-update", QIcon(theme.LOGO)))
        self.setFixedSize(520, 280)

        logo = QLabel()
        logo.setPixmap(QIcon.fromTheme("shale-update", QIcon(theme.LOGO)).pixmap(56, 56))
        self.title = theme.label("Software Update", wrap=False)
        self.title.setStyleSheet("font-size: 17pt; font-weight: 600;")
        self.status = theme.label("Keep your computer safe and up to date.", "subtitle")
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        head_text.addWidget(self.title)
        head_text.addWidget(self.status)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(logo, 0, Qt.AlignTop)
        head.addLayout(head_text, 1)

        self.bar = QProgressBar(maximum=1000)
        self.bar.setStyleSheet("QProgressBar::chunk { background: #cfcfcf; }")
        self.bar.setVisible(False)
        self.detail = theme.label("", "muted", wrap=False)
        self.detail.setVisible(False)

        self.secondary = theme.button("Close")
        self.secondary.clicked.connect(self.close)
        self.primary = theme.button("Update now", "primary")
        self.primary.setDefault(True)
        self.primary.setFocus()
        self.primary.clicked.connect(self.start)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.secondary)
        buttons.addWidget(self.primary)

        box = QVBoxLayout(self)
        box.setContentsMargins(28, 28, 28, 24)
        box.addLayout(head)
        box.addStretch()
        box.addWidget(self.bar)
        box.addWidget(self.detail)
        box.addStretch()
        box.addLayout(buttons)

        self.proc = None
        self.buf = b""
        self.result = None
        self.busy = False

    def start(self):
        self.busy = True
        self.result = None
        self.primary.setVisible(False)
        self.secondary.setVisible(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)  # pulsing until the first real progress arrives
        self.detail.setVisible(True)
        self.detail.setText("")
        self.status.setText("Checking for updates…")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(self.read)
        self.proc.finished.connect(self.finished)
        self.proc.start("pkexec", [HELPER])

    def read(self):
        self.buf += bytes(self.proc.readAll())
        *lines, self.buf = self.buf.split(b"\n")
        for raw in lines:
            try:
                msg = json.loads(raw.decode(errors="replace"))
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "step":
                self.status.setText(msg["text"])
                if "progress" in msg:
                    self.bar.setRange(0, 1000)
                    self.bar.setValue(int(msg["progress"] * 1000))
                if msg.get("detail"):
                    self.detail.setText(msg["detail"])
            elif kind in ("done", "error"):
                self.result = msg

    def finished(self, code, _status):
        # Apps installed just for this user are updated without admin rights.
        subprocess.run(["flatpak", "update", "--user", "-y", "--noninteractive"],
                       capture_output=True)
        self.busy = False
        self.bar.setRange(0, 1000)
        self.detail.setVisible(False)
        self.secondary.setVisible(True)
        self.primary.setVisible(True)
        if self.primary.receivers("2clicked()"):
            self.primary.clicked.disconnect()
        msg = self.result or {}
        if msg.get("type") == "done":
            self.bar.setValue(1000)
            if msg.get("restart"):
                self.status.setText("Updates are installed. Restart to finish.")
                self.primary.setText("Restart now")
                self.primary.clicked.connect(
                    lambda: subprocess.Popen(["dbus-send", "--session", "--type=method_call",
                                              "--dest=org.kde.LogoutPrompt", "/LogoutPrompt",
                                              "org.kde.LogoutPrompt.promptReboot"]))
                self.secondary.setText("Later")
            else:
                self.status.setText("Your computer is up to date." if not msg.get("changed")
                                    else "All updates are installed.")
                self.primary.setText("Done")
                self.primary.clicked.connect(self.close)
                self.secondary.setVisible(False)
        elif code in (126, 127) and not msg:
            # pkexec: the password dialog was cancelled.
            self.bar.setVisible(False)
            self.status.setText("Update cancelled.")
            self.primary.setText("Update now")
            self.primary.clicked.connect(self.start)
        else:
            self.bar.setVisible(False)
            self.status.setText(msg.get("text") or "Something went wrong while updating.")
            self.status.setProperty("role", "error")
            self.status.style().polish(self.status)
            self.primary.setText("Try again")
            self.primary.clicked.connect(self.start)

    def closeEvent(self, ev):
        if self.busy:
            ev.ignore()
            self.status.setText("Please wait until the update finishes.")
            return
        ev.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("shale-update")
    app.setDesktopFileName("shale-update")
    theme.apply(app)
    w = Updater()
    w.show()
    if "--now" in sys.argv:
        w.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
