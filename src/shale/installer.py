"""Shale Linux installer (frontend).

Runs as the live user. A short, friendly wizard collects a few choices, then the
root backend (install_backend.py) is started through pkexec and its progress shown.
"""

import json
import re
import subprocess
import sys
import threading
import urllib.request
import zoneinfo
from datetime import datetime

from PySide6.QtCore import QObject, QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QRadioButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import data, theme
from .theme import button, label

BACKEND = "/usr/lib/shale/shale-install-backend"
MIN_DISK_BYTES = 30 * 1000 ** 3

SLIDES = [
    ("shale-software", "system-software-install", "Software Manager",
     "Find and install thousands of free apps with one click: games, music, "
     "photo editors, chat apps and more."),
    ("libreoffice-startcenter", "x-office-document", "LibreOffice",
     "Write documents, build spreadsheets and give presentations. It opens and saves "
     "Microsoft Office files too."),
    ("vlc", "multimedia-video-player", "VLC media player",
     "Plays almost any video or music file you throw at it, with no extra downloads."),
    ("org.kde.gwenview", "image-x-generic", "Gwenview",
     "Browse, view and touch up your photos."),
    ("chromium", "internet-web-browser", "Chromium",
     "A fast, secure web browser."),
    ("shale-update", "system-software-update", "Easy updates",
     "Open Software Update from the app menu to keep everything current, "
     "with one click."),
    ("preferences-system-bluetooth", "bluetooth", "Bluetooth built in",
     "Connect headphones, mice, keyboards and game controllers from the panel."),
    ("shale-game-panel", "input-gaming", "Game Panel",
     "Get Steam from the Software Manager, then switch on Game Panel for smooth, "
     "steady gameplay in every game."),
]

# Default keyboard for each language (index into data.KEYBOARDS by label).
LOCALE_KEYBOARD = {
    "en_GB": "English (UK)", "de": "German", "fr_FR": "French",
    "fr_CA": "French (Canada)", "es_ES": "Spanish", "es_MX": "Spanish (Latin American)",
    "it": "Italian", "pt_BR": "Portuguese (Brazil)", "pt_PT": "Portuguese",
    "pl": "Polish", "sv": "Swedish", "nb": "Norwegian", "da": "Danish", "fi": "Finnish",
    "cs": "Czech", "hu": "Hungarian", "tr": "Turkish", "ru": "Russian",
    "uk": "Ukrainian", "el": "Greek", "ja": "Japanese", "ko": "Korean",
}


# ---------------------------------------------------------------- helpers

class Bg(QObject):
    """Runs a function on a thread and delivers its result on the GUI thread."""
    done = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def start(self):
        def work():
            try:
                res = self.fn()
            except Exception:  # noqa: BLE001
                res = None
            self.done.emit(res)
        threading.Thread(target=work, daemon=True).start()
        return self


def icon(*names):
    for n in names:
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return QIcon(theme.LOGO)


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def human_size(n):
    gb = n / 1000 ** 3
    return f"{gb / 1000:.1f} TB" if gb >= 1000 else f"{gb:.0f} GB"


def live_disk():
    """The disk the live system was booted from, so it is never offered."""
    src = sh(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"]).strip()
    if src:
        return sh(["lsblk", "-npo", "PKNAME", src]).strip() or src
    return None


def list_disks():
    out = sh(["lsblk", "-J", "-b", "-d", "-o", "PATH,SIZE,MODEL,TYPE,RM,TRAN,ROTA"])
    skip = live_disk()
    disks = []
    for d in json.loads(out or '{"blockdevices": []}')["blockdevices"]:
        if d["type"] == "disk" and d["path"] != skip and not d["path"].startswith("/dev/zram"):
            disks.append(d)
    return disks


def detect_gpu():
    gpus = " ".join(l for l in sh(["lspci", "-nn"]).splitlines()
                    if re.search(r"VGA|3D|Display", l))
    if "[1002:" in gpus:
        return "amd"
    if "[10de:" in gpus:
        return "nvidia"
    if "[8086:" in gpus:
        return "intel"
    return "generic" if gpus else "amd"


def detect_cpu():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return "intel" if "GenuineIntel" in f.read() else "amd"
    except OSError:
        return "amd"


def geoip_timezone():
    with urllib.request.urlopen("https://geoip.kde.org/v1/calamares", timeout=5) as r:
        tz = json.load(r).get("time_zone")
    return tz if tz in zoneinfo.available_timezones() else None


def online():
    try:
        urllib.request.urlopen("https://archlinux.org", timeout=4)
        return True
    except Exception:  # noqa: BLE001
        return False


def wifi_networks():
    out = sh(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi",
              "list", "--rescan", "auto"])
    nets = {}
    for line in out.splitlines():
        parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]
        if len(parts) < 4 or not parts[1]:
            continue
        inuse, ssid, signal, sec = parts[0] == "*", parts[1], int(parts[2] or 0), parts[3]
        if ssid not in nets or nets[ssid]["signal"] < signal:
            nets[ssid] = {"ssid": ssid, "signal": signal, "secure": bool(sec.strip()),
                          "active": inuse}
    return sorted(nets.values(), key=lambda n: (-n["active"], -n["signal"]))


class Card(QFrame):
    """A big clickable tile with an icon, a title and a short description."""
    clicked = Signal()

    def __init__(self, ic, title, desc, icon_size=48, horizontal=False):
        super().__init__()
        self.setProperty("role", "card")
        self.setCursor(Qt.PointingHandCursor)
        pic = QLabel()
        pic.setPixmap(ic.pixmap(icon_size, icon_size))
        t = label(title)
        t.setStyleSheet("font-size: 13pt; font-weight: 600;")
        d = label(desc, "muted")
        if horizontal:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(18, 14, 18, 14)
            lay.setSpacing(16)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(t)
            text.addWidget(d)
            lay.addWidget(pic)
            lay.addLayout(text, 1)
        else:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(24, 24, 24, 24)
            lay.setSpacing(8)
            lay.addWidget(pic)
            lay.addSpacing(6)
            lay.addWidget(t)
            lay.addWidget(d)
            lay.addStretch()

    def set_selected(self, on):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()


# ---------------------------------------------------------------- pages

class Page(QWidget):
    changed = Signal()
    step = None          # name shown in the step dots, None = not counted
    footer = True

    def __init__(self, wiz, title="", subtitle=""):
        super().__init__()
        self.wiz = wiz
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(64, 20, 64, 8)
        self.box.setSpacing(16)
        if title:
            self.box.addWidget(label(title, "title"))
        if subtitle:
            self.sub = label(subtitle, "subtitle")
            self.box.addWidget(self.sub)
            self.box.addSpacing(8)

    def complete(self):
        return True

    def enter(self):
        pass

    def leave(self):
        pass

    def skip(self):
        return False


class WelcomePage(Page):
    footer = False

    def __init__(self, wiz):
        super().__init__(wiz)
        self.box.addStretch(2)
        logo = QLabel(alignment=Qt.AlignCenter)
        logo.setPixmap(QIcon(theme.LOGO).pixmap(104, 104))
        self.box.addWidget(logo)
        t = label(f"Welcome to {data.DISTRO_NAME}", "title")
        t.setAlignment(Qt.AlignCenter)
        self.box.addWidget(t)
        s = label("Fast, simple and yours. Try it out, or install it in a few easy steps.",
                  "subtitle")
        s.setAlignment(Qt.AlignCenter)
        self.box.addWidget(s)

        lang_row = QHBoxLayout()
        lang_row.addStretch()
        lang_row.addWidget(label("Language", "muted", wrap=False))
        self.lang = QComboBox()
        self.lang.setMinimumWidth(280)
        for text, loc in data.LANGUAGES:
            self.lang.addItem(text, loc)
        lang_row.addWidget(self.lang)
        lang_row.addStretch()
        self.box.addSpacing(6)
        self.box.addLayout(lang_row)
        self.box.addSpacing(18)

        cards = QHBoxLayout()
        cards.setSpacing(20)
        cards.addStretch()
        self.try_card = Card(icon("media-playback-start", "view-preview"), "Try Shale",
                             "Look around first. Nothing on your computer will change.")
        self.inst_card = Card(icon("system-software-install", "run-install"),
                              "Install Shale",
                              "Put Shale on this computer. It takes about 15 minutes.")
        for c in (self.try_card, self.inst_card):
            c.setFixedSize(300, 190)
            cards.addWidget(c)
        cards.addStretch()
        self.inst_card.set_selected(True)
        self.try_card.clicked.connect(wiz.showMinimized)
        self.inst_card.clicked.connect(wiz.forward)
        self.box.addLayout(cards)
        self.box.addStretch(3)

    def leave(self):
        self.wiz.cfg["locale"] = self.lang.currentData()
        self.wiz.cfg["locale_label"] = self.lang.currentText()


class KeyboardPage(Page):
    step = "Keyboard"

    def __init__(self, wiz):
        super().__init__(wiz, "Keyboard layout",
                         "Choose the layout that matches your keyboard.")
        self.list = QListWidget()
        for text, layout, variant, keymap in data.KEYBOARDS:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, {"layout": layout, "variant": variant,
                                       "keymap": keymap})
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.currentRowChanged.connect(self.apply)
        self.box.addWidget(self.list, 1)
        self.test = QLineEdit(placeholderText="Type here to test your keyboard")
        self.box.addWidget(self.test)
        self.guessed = None

    def enter(self):
        loc = self.wiz.cfg.get("locale", "en_US.UTF-8").split(".")[0]
        want = LOCALE_KEYBOARD.get(loc) or LOCALE_KEYBOARD.get(loc.split("_")[0])
        if want and self.guessed != loc:
            self.guessed = loc
            for i in range(self.list.count()):
                if self.list.item(i).text() == want:
                    self.list.setCurrentRow(i)
        self.list.scrollToItem(self.list.currentItem())

    def apply(self):
        # Switch the live session's layout so the test field matches.
        kb = self.list.currentItem().data(Qt.UserRole)
        for key, val in (("Use", "true"), ("LayoutList", kb["layout"]),
                         ("VariantList", kb["variant"])):
            sh(["kwriteconfig6", "--file", "kxkbrc", "--group", "Layout", "--key", key, val])
        sh(["dbus-send", "--session", "--type=signal", "/Layouts",
            "org.kde.keyboard.reloadConfig"])

    def leave(self):
        item = self.list.currentItem()
        self.wiz.cfg["keyboard"] = item.data(Qt.UserRole)
        self.wiz.cfg["keyboard_label"] = item.text()


class NetworkPage(Page):
    step = "Internet"

    def __init__(self, wiz):
        super().__init__(wiz, "Connect to the internet",
                         "Shale downloads the newest software while it installs. "
                         "Using a cable? Just plug it in.")
        self.status = label("")
        self.box.addWidget(self.status)
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self.selected)
        self.box.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.pw = QLineEdit(placeholderText="Wi-Fi password", echoMode=QLineEdit.Password)
        self.pw.returnPressed.connect(self.connect_wifi)
        self.connect_btn = button("Connect", "primary")
        self.connect_btn.clicked.connect(self.connect_wifi)
        row.addWidget(self.pw, 1)
        row.addWidget(self.connect_btn)
        self.box.addLayout(row)
        self.ok = False
        self.timer = QTimer(self, interval=5000, timeout=self.refresh)

    def skip(self):
        return self.wiz.is_online

    def enter(self):
        self.refresh()
        self.timer.start()

    def leave(self):
        self.timer.stop()

    def refresh(self):
        Bg(online, self).start().done.connect(self.got_online)
        Bg(wifi_networks, self).start().done.connect(self.got_networks)

    def got_online(self, ok):
        self.ok = bool(ok)
        self.wiz.is_online = self.ok
        if self.ok:
            self.status.setText("✓  You're connected. Click Continue.")
            self.status.setStyleSheet(f"color: #5cc177;")
        elif not self.status.text().startswith("Connecting"):
            self.status.setText("Pick your Wi-Fi network:")
            self.status.setStyleSheet("")
        self.changed.emit()

    def got_networks(self, nets):
        current = self.list.currentItem().data(Qt.UserRole)["ssid"] \
            if self.list.currentItem() else None
        self.list.clear()
        for n in nets or []:
            bars = "▂▄▆█"[: max(1, min(4, n["signal"] // 25 + 1))]
            text = f"{n['ssid']}    {bars}{'  🔒' if n['secure'] else ''}"
            if n["active"]:
                text += "   · Connected"
            item = QListWidgetItem(icon("network-wireless"), text)
            item.setData(Qt.UserRole, n)
            self.list.addItem(item)
            if n["ssid"] == current:
                self.list.setCurrentItem(item)
        if not nets:
            self.list.addItem("No Wi-Fi networks found. You can use a network cable instead.")

    def selected(self):
        item = self.list.currentItem()
        n = item.data(Qt.UserRole) if item else None
        self.pw.setEnabled(bool(n and n["secure"]))
        self.connect_btn.setEnabled(bool(n))

    def connect_wifi(self):
        item = self.list.currentItem()
        n = item.data(Qt.UserRole) if item else None
        if not n:
            return
        cmd = ["nmcli", "device", "wifi", "connect", n["ssid"]]
        if n["secure"]:
            cmd += ["password", self.pw.text()]
        self.status.setText(f"Connecting to {n['ssid']}…")
        self.status.setStyleSheet("")
        self.connect_btn.setEnabled(False)

        def run():
            return subprocess.run(cmd, capture_output=True, text=True).returncode == 0

        def done(ok):
            self.connect_btn.setEnabled(True)
            if not ok:
                self.status.setText("Couldn't connect. Check the password and try again.")
                self.status.setStyleSheet(f"color: {theme.DANGER};")
            self.refresh()
        Bg(run, self).start().done.connect(done)

    def complete(self):
        return self.ok


class DiskPage(Page):
    step = "Disk"

    def __init__(self, wiz):
        super().__init__(wiz, "Where should Shale go?",
                         "Pick a disk. Everything on it will be erased, including other "
                         "systems like Windows, so back up your files first.")
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(10)
        holder = QWidget()
        holder.setLayout(self.cards_box)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setWidget(holder)
        self.box.addWidget(scroll, 1)

        self.encrypt = QCheckBox("Encrypt the disk for extra security. You'll enter a "
                                 "password each time the computer starts.")
        self.encrypt.toggled.connect(self.toggle_encrypt)
        self.box.addWidget(self.encrypt)
        self.enc = QWidget()
        g = QHBoxLayout(self.enc)
        g.setContentsMargins(28, 0, 0, 0)
        self.pw1 = QLineEdit(placeholderText="Encryption password", echoMode=QLineEdit.Password)
        self.pw2 = QLineEdit(placeholderText="Repeat password", echoMode=QLineEdit.Password)
        for w in (self.pw1, self.pw2):
            w.textChanged.connect(self.changed)
            g.addWidget(w)
        self.enc.setVisible(False)
        self.box.addWidget(self.enc)
        self.cards = []
        self.chosen = None

    def toggle_encrypt(self, on):
        self.enc.setVisible(on)
        self.changed.emit()

    def enter(self):
        while self.cards_box.count():
            w = self.cards_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cards = []
        for d in list_disks():
            kind = ("USB drive" if d.get("tran") == "usb" or d.get("rm")
                    else "NVMe SSD" if d.get("tran") == "nvme"
                    else "SSD" if not d.get("rota") else "Hard drive")
            model = (d.get("model") or "Disk").strip()
            small = d["size"] < MIN_DISK_BYTES
            desc = f"{human_size(d['size'])} {kind}  ·  {d['path']}"
            if small:
                desc += "  ·  too small (needs 30 GB)"
            card = Card(icon("drive-removable-media-usb" if kind == "USB drive"
                             else "drive-harddisk"), model, desc, 40, horizontal=True)
            card.setEnabled(not small)
            card.disk = d
            card.label_text = f"{model} ({human_size(d['size'])}, {d['path']})"
            card.clicked.connect(lambda c=card: self.pick(c))
            self.cards_box.addWidget(card)
            self.cards.append(card)
        self.cards_box.addStretch()
        usable = [c for c in self.cards if c.isEnabled()]
        prev = [c for c in usable if self.chosen and c.disk["path"] == self.chosen]
        self.pick((prev or usable or [None])[0])

    def pick(self, card):
        self.chosen = card.disk["path"] if card else None
        for c in self.cards:
            c.set_selected(c is card)
        self.changed.emit()

    def complete(self):
        if not self.chosen:
            return False
        if self.encrypt.isChecked():
            return bool(self.pw1.text()) and self.pw1.text() == self.pw2.text()
        return True

    def leave(self):
        card = next((c for c in self.cards if c.disk["path"] == self.chosen), None)
        if not card:
            return
        self.wiz.cfg.update(disk=self.chosen, disk_label=card.label_text,
                            encrypt=self.encrypt.isChecked(),
                            encrypt_password=self.pw1.text() if self.encrypt.isChecked()
                            else "")


class LocationPage(Page):
    step = "Location"

    def __init__(self, wiz):
        super().__init__(wiz, "Where are you?", "This sets your clock and time zone.")
        self.zones = {}
        for tz in sorted(zoneinfo.available_timezones()):
            if "/" in tz and not tz.startswith(("Etc/", "SystemV/", "posix/", "right/")):
                region, city = tz.split("/", 1)
                self.zones.setdefault(region, []).append(city)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        self.region = QComboBox()
        self.region.addItems(sorted(self.zones))
        self.city = QComboBox()
        self.region.currentTextChanged.connect(self.fill_cities)
        self.city.currentIndexChanged.connect(self.tick)
        grid.addWidget(label("Region", "muted"), 0, 0)
        grid.addWidget(label("City", "muted"), 0, 1)
        grid.addWidget(self.region, 1, 0)
        grid.addWidget(self.city, 1, 1)
        self.box.addLayout(grid)
        self.box.addSpacing(30)
        self.clock = label("", wrap=False)
        self.clock.setAlignment(Qt.AlignCenter)
        self.clock.setStyleSheet("font-size: 44pt; font-weight: 300;")
        self.date = label("", "muted", wrap=False)
        self.date.setAlignment(Qt.AlignCenter)
        self.box.addWidget(self.clock)
        self.box.addWidget(self.date)
        self.box.addStretch()
        self.set_tz("America/New_York")
        Bg(geoip_timezone, self).start().done.connect(lambda tz: tz and self.set_tz(tz))
        self.timer = QTimer(self, interval=1000, timeout=self.tick)
        self.timer.start()

    def tz(self):
        return f"{self.region.currentText()}/{self.city.currentData()}"

    def set_tz(self, tz):
        region, city = tz.split("/", 1)
        self.region.setCurrentText(region)
        self.fill_cities(region)
        idx = self.city.findData(city)
        if idx >= 0:
            self.city.setCurrentIndex(idx)

    def fill_cities(self, region):
        self.city.blockSignals(True)
        self.city.clear()
        for c in self.zones.get(region, []):
            self.city.addItem(c.replace("_", " "), c)
        self.city.blockSignals(False)
        self.tick()

    def tick(self):
        try:
            now = datetime.now(zoneinfo.ZoneInfo(self.tz()))
        except Exception:  # noqa: BLE001
            return
        self.clock.setText(now.strftime("%H:%M"))
        self.date.setText(now.strftime("%A, %B %-d"))

    def leave(self):
        self.wiz.cfg["timezone"] = self.tz()


class UserPage(Page):
    step = "You"

    def __init__(self, wiz):
        super().__init__(wiz, "Who are you?", "Set up your account.")
        col = QVBoxLayout()
        col.setSpacing(6)
        self.name = QLineEdit(placeholderText="Your name")
        self.host = QLineEdit(placeholderText="Your computer's name")
        self.user = QLineEdit(placeholderText="Pick a username")
        self.pw1 = QLineEdit(placeholderText="Choose a password", echoMode=QLineEdit.Password)
        self.pw2 = QLineEdit(placeholderText="Confirm your password",
                             echoMode=QLineEdit.Password)
        for w, hint in ((self.name, None),
                        (self.host, "The name it uses when it talks to other computers."),
                        (self.user, None), (self.pw1, None), (self.pw2, None)):
            col.addWidget(w)
            if hint:
                col.addWidget(label(hint, "muted"))
            col.addSpacing(6)
        self.hint = label("", "error")
        col.addWidget(self.hint)
        self.ask = QRadioButton("Require my password to log in")
        self.auto = QRadioButton("Log in automatically")
        self.ask.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.ask)
        grp.addButton(self.auto)
        col.addWidget(self.ask)
        col.addWidget(self.auto)
        holder = QWidget()
        holder.setLayout(col)
        holder.setMaximumWidth(460)
        self.box.addWidget(holder)
        self.box.addStretch()
        self.user_edited = self.host_edited = False
        self.name.textChanged.connect(self.name_changed)
        self.user.textEdited.connect(lambda: setattr(self, "user_edited", True))
        self.host.textEdited.connect(lambda: setattr(self, "host_edited", True))
        for w in (self.name, self.user, self.pw1, self.pw2, self.host):
            w.textChanged.connect(self.validate)

    def name_changed(self, text):
        first = text.strip().split(" ")[0].lower() if text.strip() else ""
        user = re.sub(r"[^a-z0-9_-]", "", first)
        if user and not re.match(r"[a-z_]", user):
            user = "u" + user
        if not self.user_edited:
            self.user.setText(user[:32])
        if not self.host_edited:
            self.host.setText(f"{user or 'shale'}-pc"[:63])

    def problem(self):
        if not self.name.text().strip():
            return "Please enter your name."
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", self.host.text()):
            return "Computer names can use letters, numbers and dashes."
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.user.text()):
            return "Usernames use lowercase letters and numbers, starting with a letter."
        if self.user.text() in ("root", "live", "bin", "daemon", "nobody", "sddm"):
            return "That username is reserved. Please pick another one."
        if not self.pw1.text():
            return "Please choose a password."
        if self.pw1.text() != self.pw2.text():
            return "The passwords don't match."
        return ""

    def validate(self):
        self.hint.setText(self.problem() if self.pw2.text() else "")
        self.changed.emit()

    def complete(self):
        return not self.problem()

    def leave(self):
        self.wiz.cfg.update(fullname=self.name.text().strip(), username=self.user.text(),
                            password=self.pw1.text(), hostname=self.host.text(),
                            autologin=self.auto.isChecked())


class ReadyPage(Page):
    step = "Install"

    def __init__(self, wiz):
        super().__init__(wiz, "Ready to install",
                         "Check your choices. Click Install now when you're ready.")
        self.panel = QFrame()
        self.panel.setProperty("role", "panel")
        self.grid = QGridLayout(self.panel)
        self.grid.setContentsMargins(24, 20, 24, 20)
        self.grid.setHorizontalSpacing(32)
        self.grid.setVerticalSpacing(12)
        self.box.addWidget(self.panel)
        self.gpu = QComboBox()
        for key in ("amd", "nvidia", "intel", "generic"):
            self.gpu.addItem(data.GPU_LABELS[key], key)
        self.gpu.setCurrentIndex(self.gpu.findData(detect_gpu()))
        self.box.addWidget(label("You'll get KDE Plasma with the Software Manager, Game Panel, "
                                 "LibreOffice, VLC, Gwenview and Chromium, all ready to use.", "muted"))
        self.box.addStretch()

    def enter(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w and w is not self.gpu:
                w.deleteLater()
        c = self.wiz.cfg
        rows = [
            ("Disk", c.get("disk_label", "") + ("  ·  encrypted" if c.get("encrypt") else "")),
            ("Language", c.get("locale_label", "")),
            ("Keyboard", c.get("keyboard_label", "")),
            ("Time zone", c.get("timezone", "").replace("_", " ")),
            ("Account", f"{c.get('fullname', '')} ({c.get('username', '')})"),
        ]
        for i, (k, v) in enumerate(rows):
            self.grid.addWidget(label(k, "muted", wrap=False), i, 0)
            self.grid.addWidget(label(v), i, 1)
        self.grid.addWidget(label("Graphics", "muted", wrap=False), len(rows), 0)
        self.grid.addWidget(self.gpu, len(rows), 1)
        self.grid.setColumnStretch(1, 1)

    def leave(self):
        self.wiz.cfg["gpu"] = self.gpu.currentData()
        self.wiz.cfg["cpu"] = detect_cpu()


class InstallPage(Page):
    footer = False

    def __init__(self, wiz):
        super().__init__(wiz)
        self.box.setContentsMargins(64, 32, 64, 32)
        self.box.addStretch()
        self.slide_icon = QLabel(alignment=Qt.AlignCenter)
        self.slide_title = label("", "title")
        self.slide_title.setAlignment(Qt.AlignCenter)
        self.slide_text = label("", "subtitle")
        self.slide_text.setAlignment(Qt.AlignCenter)
        self.slide_text.setMinimumHeight(60)
        self.dots = label("", "muted")
        self.dots.setAlignment(Qt.AlignCenter)
        for w in (self.slide_icon, self.slide_title, self.slide_text, self.dots):
            self.box.addWidget(w)
        self.box.addStretch()
        self.status = label("Getting ready…", "muted")
        self.bar = QProgressBar(maximum=1000)
        self.box.addWidget(self.status)
        self.box.addWidget(self.bar)
        self.details_btn = button("Show details", "link")
        self.details_btn.clicked.connect(self.toggle_log)
        self.box.addWidget(self.details_btn, alignment=Qt.AlignLeft)
        self.log = QPlainTextEdit(readOnly=True, maximumBlockCount=5000)
        self.log.setVisible(False)
        self.log.setMinimumHeight(160)
        self.box.addWidget(self.log)
        self.slide = 0
        self.slide_timer = QTimer(self, interval=8000, timeout=self.next_slide)
        self.proc = None
        self.buf = b""
        self.error = None
        self.finished = False

    def toggle_log(self):
        on = not self.log.isVisible()
        self.log.setVisible(on)
        self.details_btn.setText("Hide details" if on else "Show details")

    def next_slide(self):
        ic, fallback, title, text = SLIDES[self.slide % len(SLIDES)]
        self.slide_icon.setPixmap(icon(ic, fallback).pixmap(112, 112))
        self.slide_title.setText(title)
        self.slide_text.setText(text)
        self.dots.setText("  ".join("●" if i == self.slide % len(SLIDES) else "○"
                                    for i in range(len(SLIDES))))
        self.slide += 1

    def enter(self):
        self.error, self.finished, self.buf = None, False, b""
        self.bar.setValue(0)
        self.log.clear()
        self.next_slide()
        self.slide_timer.start()
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(self.read)
        self.proc.finished.connect(self.done)
        self.proc.start("pkexec", [BACKEND])
        self.proc.waitForStarted()
        cfg = {k: v for k, v in self.wiz.cfg.items() if not k.endswith("_label")}
        self.proc.write(json.dumps(cfg).encode())
        self.proc.closeWriteChannel()

    def read(self):
        self.buf += bytes(self.proc.readAll())
        *lines, self.buf = self.buf.split(b"\n")
        for raw in lines:
            line = raw.decode(errors="replace")
            try:
                msg = json.loads(line)
            except ValueError:
                self.log.appendPlainText(line)
                continue
            kind = msg.get("type")
            if kind == "step":
                self.status.setText(msg["text"])
                self.bar.setValue(int(msg.get("progress", 0) * 1000))
            elif kind == "log":
                self.log.appendPlainText(msg["text"])
            elif kind == "error":
                self.error = msg["text"]
            elif kind == "done":
                self.finished = True

    def done(self, code, _status):
        self.slide_timer.stop()
        ok = code == 0 and self.finished
        self.wiz.show_result(ok, "" if ok else (
            self.error or f"The installer stopped unexpectedly (code {code})."))


class ResultPage(Page):
    footer = False

    def __init__(self, wiz):
        super().__init__(wiz)
        self.box.addStretch()
        self.pic = QLabel(alignment=Qt.AlignCenter)
        self.head = label("", "title")
        self.head.setAlignment(Qt.AlignCenter)
        self.body = label("", "subtitle")
        self.body.setAlignment(Qt.AlignCenter)
        for w in (self.pic, self.head, self.body):
            self.box.addWidget(w)
        self.box.addSpacing(20)
        row = QHBoxLayout()
        row.addStretch()
        self.secondary = button("")
        self.primary = button("", "primary")
        row.addWidget(self.secondary)
        row.addWidget(self.primary)
        row.addStretch()
        self.box.addLayout(row)
        self.box.addStretch()

    def setup(self, ok, error):
        for b in (self.primary, self.secondary):
            if b.receivers("2clicked()"):
                b.clicked.disconnect()
        if ok:
            self.pic.setPixmap(QIcon(theme.LOGO).pixmap(104, 104))
            self.head.setText("All done!")
            self.body.setText("Shale Linux is installed. Restart your computer, and remove "
                              "the USB stick when the screen goes dark.")
            self.primary.setText("Restart now")
            self.primary.clicked.connect(lambda: subprocess.Popen(["systemctl", "reboot"]))
            self.secondary.setText("Keep trying Shale")
            self.secondary.clicked.connect(self.wiz.close)
        else:
            self.pic.setPixmap(icon("dialog-warning").pixmap(88, 88))
            self.head.setText("Something went wrong")
            self.body.setText(f"{error}\n\nYour disk may have been partly changed. Check "
                              "your internet connection and try again.")
            self.primary.setText("Try again")
            self.primary.clicked.connect(self.wiz.retry)
            self.secondary.setText("Close")
            self.secondary.clicked.connect(self.wiz.close)


# ---------------------------------------------------------------- window

class Wizard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Install {data.DISTRO_NAME}")
        self.setWindowIcon(QIcon(theme.LOGO))
        self.resize(1040, 720)
        self.cfg = {}
        self.is_online = False
        Bg(online, self).start().done.connect(lambda ok: setattr(self, "is_online", bool(ok)))

        self.pages = [WelcomePage(self), KeyboardPage(self), NetworkPage(self),
                      DiskPage(self), LocationPage(self), UserPage(self), ReadyPage(self),
                      InstallPage(self), ResultPage(self)]
        self.install_idx = self.pages.index(next(p for p in self.pages
                                                 if isinstance(p, InstallPage)))
        self.result_idx = len(self.pages) - 1
        self.steps = [p.step for p in self.pages if p.step]

        # Header: brand on the left, step dots on the right.
        logo = QLabel()
        logo.setPixmap(QIcon(theme.LOGO).pixmap(26, 26))
        brand = label(data.DISTRO_NAME, wrap=False)
        brand.setStyleSheet("font-weight: 600;")
        self.dots = label("", "muted", wrap=False)
        header = QHBoxLayout()
        header.setContentsMargins(24, 16, 24, 0)
        header.addWidget(logo)
        header.addWidget(brand)
        header.addStretch()
        header.addWidget(self.dots)

        self.stack = QStackedWidget()
        for p in self.pages:
            self.stack.addWidget(p)
            p.changed.connect(self.update_buttons)

        self.back = button("Back")
        self.next = button("Continue", "primary")
        self.next.setDefault(True)
        self.back.clicked.connect(self.backward)
        self.next.clicked.connect(self.forward)
        self.footer = QWidget()
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(64, 8, 64, 28)
        foot.addStretch()
        foot.addWidget(self.back)
        foot.addWidget(self.next)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(header)
        root.addWidget(self.stack, 1)
        root.addWidget(self.footer)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self.idx = -1
        self.go(0)

    def go(self, i):
        if self.idx >= 0:
            self.pages[self.idx].leave()
        self.idx = i
        page = self.pages[i]
        self.stack.setCurrentIndex(i)
        if page.step:
            n = self.steps.index(page.step)
            self.dots.setText(f"{page.step}   " + " ".join(
                "●" if j <= n else "○" for j in range(len(self.steps))))
        else:
            self.dots.setText("")
        page.enter()
        self.update_buttons()

    def update_buttons(self):
        page = self.pages[self.idx]
        self.footer.setVisible(page.footer)
        self.back.setVisible(self.idx > 0)
        self.next.setEnabled(page.complete())
        self.next.setText("Install now" if isinstance(page, ReadyPage) else "Continue")

    def forward(self):
        if isinstance(self.pages[self.idx], ReadyPage):
            self.pages[self.idx].leave()
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Erase disk?")
            box.setText("Everything on this disk will be permanently erased:")
            box.setInformativeText(self.cfg.get("disk_label", ""))
            erase = box.addButton("Erase and install", QMessageBox.AcceptRole)
            erase.setProperty("role", "primary")
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not erase:
                return
        i = self.idx + 1
        while i < self.install_idx and self.pages[i].skip():
            i += 1
        self.go(i)

    def backward(self):
        i = self.idx - 1
        while i > 0 and self.pages[i].skip():
            i -= 1
        self.go(i)

    def show_result(self, ok, error):
        self.pages[self.result_idx].setup(ok, error)
        self.go(self.result_idx)

    def retry(self):
        self.go(self.install_idx - 1)

    def closeEvent(self, ev):
        if self.idx == self.install_idx:
            QMessageBox.information(self, "Please wait",
                                    "Shale is still being installed. Please wait until "
                                    "it finishes.")
            ev.ignore()
            return
        ev.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("shale-installer")
    app.setApplicationDisplayName(f"Install {data.DISTRO_NAME}")
    app.setDesktopFileName("shale-installer")
    theme.apply(app)
    w = Wizard()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
