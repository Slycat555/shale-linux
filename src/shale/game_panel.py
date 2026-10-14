#!/usr/bin/env python3
"""Game Panel — turn gamescope on globally or per game for your Steam library.

How it works: each game's Steam launch option is set once to
    <data>/gp-run <appid> %command%
That wrapper reads a small profile Game Panel writes for every game, so flipping
a toggle here takes effect on the next launch without restarting Steam.
"""
import configparser
import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import (Property, QEasingCurve, QPoint, QProcess, QPropertyAnimation, QRect, QRectF,
                            QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QComboBox, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

APP_NAME = "Game Panel"
HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "game-panel"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "game-panel"
FLATPAK_ID = "com.valvesoftware.Steam"
CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{name}"

TOOL_RE = re.compile(r"^Proton\b|Steam Linux Runtime|Steamworks Common|Steamworks Shared|"
                     r"BattlEye Runtime|EasyAntiCheat Runtime|^SteamVR|Redistributable", re.I)

DEFAULT_SETTINGS = {
    "output_w": 0, "output_h": 0,   # 0 = native display
    "game_w": 0, "game_h": 0,       # 0 = same as output
    "refresh": 0,                   # 0 = native
    "display": "fullscreen",        # fullscreen | borderless | windowed
    "scaler": "auto",               # auto | fit | fill | stretch | integer
    "filter": "linear",             # linear | fsr | nis | nearest | pixel
    "sharpness": 5,
    "fps_limit": 0,
    "adaptive_sync": False,
    "hdr": False,
    "mangohud": False,
    "grab_cursor": False,
    "extra": "",
}


# ─────────────────────────────── VDF (Steam KeyValues text) ───────────────────────────────
# Nodes are lists of [key, value, *conditionals] so files round-trip exactly
# (order, duplicate keys and escapes preserved). Strings stay in escaped form.

_TOKEN = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])|(//[^\n]*)|([^\s{}"]+)')


def vdf_parse(text):
    root, stack, key, last = [], None, None, None
    stack = [root]
    for m in _TOKEN.finditer(text):
        quoted, brace, comment, bare = m.groups()
        if comment is not None:
            continue
        if brace == "{":
            node = []
            stack[-1].append([key, node])
            stack.append(node)
            key = last = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = last = None
        else:
            tok = quoted if quoted is not None else bare
            if key is None and bare is not None and bare.startswith("[") and last is not None:
                last.append(bare)
            elif key is None:
                key = tok
            else:
                last = [key, tok]
                stack[-1].append(last)
                key = None
    return root


def vdf_dump(node, depth=0):
    ind, out = "\t" * depth, []
    for pair in node:
        k, v = pair[0], pair[1]
        if isinstance(v, list):
            out.append(f'{ind}"{k}"\n{ind}{{\n{vdf_dump(v, depth + 1)}{ind}}}\n')
        else:
            cond = "".join(" " + c for c in pair[2:])
            out.append(f'{ind}"{k}"\t\t"{v}"{cond}\n')
    return "".join(out)


def vdf_find(node, key):
    key = key.lower()
    for pair in node:
        if str(pair[0]).lower() == key:
            return pair
    return None


def vdf_path(node, keys, create=False):
    for k in keys:
        pair = vdf_find(node, k)
        if pair is None or not isinstance(pair[1], list):
            if not create:
                return None
            pair = [k, []]
            node.append(pair)
        node = pair[1]
    return node


def vdf_get(node, key, default=""):
    pair = vdf_find(node, key)
    return pair[1] if pair is not None and not isinstance(pair[1], list) else default


def vdf_unescape(s):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def vdf_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def read_vdf(path):
    return vdf_parse(Path(path).read_text(encoding="utf-8", errors="replace"))


# ─────────────────────────────────────── Steam ───────────────────────────────────────

class Steam:
    def __init__(self, root=None):
        self.root = Path(root) if root else None
        self.flatpak = self.root is not None and FLATPAK_ID in str(self.root)
        # Must live somewhere the (possibly sandboxed) Steam can read.
        self.data_dir = (self.root.parent if self.root else HOME / ".local/share") / "game-panel"

    @property
    def found(self):
        return self.root is not None

    @property
    def label(self):
        return "Flatpak Steam" if self.flatpak else "Steam"

    @staticmethod
    def installs():
        """Every Steam installation on this computer, native and Flatpak."""
        found = []
        for p in (HOME / ".local/share/Steam", HOME / ".steam/steam", HOME / ".steam/root",
                  HOME / ".var/app" / FLATPAK_ID / ".local/share/Steam"):
            if (p / "steamapps/libraryfolders.vdf").exists() and p.resolve() not in found:
                found.append(p.resolve())
        return found

    @classmethod
    def pick(cls, preferred=None):
        """The installation to manage: the one chosen before, else the one that's running,
        else the one used most recently."""
        installs = cls.installs()
        if preferred and Path(preferred) in installs:
            return cls(preferred)
        running = [r for r in installs if cls(r).running()]
        if running:
            return cls(running[0])

        def last_used(root):
            cfgs = list(root.glob("userdata/*/config/localconfig.vdf"))
            return max((c.stat().st_mtime for c in cfgs), default=0)
        return cls(max(installs, key=last_used, default=None))

    def libraries(self):
        libs = [self.root]
        try:
            tree = vdf_path(read_vdf(self.root / "steamapps/libraryfolders.vdf"), ["libraryfolders"]) or []
            for pair in tree:
                if isinstance(pair[1], list):
                    p = Path(vdf_unescape(vdf_get(pair[1], "path")))
                    if p.exists() and p.resolve() not in libs:
                        libs.append(p.resolve())
        except OSError:
            pass
        return libs

    def games(self):
        seen, games = set(), []
        for lib in self.libraries():
            for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
                try:
                    st = vdf_path(read_vdf(acf), ["AppState"]) or []
                except OSError:
                    continue
                appid = vdf_get(st, "appid")
                name = vdf_unescape(vdf_get(st, "name")) or f"App {appid}"
                if not appid or appid in seen or TOOL_RE.search(name):
                    continue
                seen.add(appid)
                games.append({"appid": appid, "name": name, "library": str(lib)})
        return sorted(games, key=lambda g: g["name"].lower())

    def localconfigs(self):
        if not self.found:
            return []
        files = list((self.root / "userdata").glob("*/config/localconfig.vdf"))
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    def launch_options(self):
        """Launch options for the most recently used Steam account."""
        cfgs = self.localconfigs()
        if not cfgs:
            return {}
        apps = vdf_path(read_vdf(cfgs[0]), ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps"]) or []
        return {p[0]: vdf_unescape(vdf_get(p[1], "LaunchOptions"))
                for p in apps if isinstance(p[1], list)}

    def set_launch_options(self, mapping):
        """mapping: appid -> launch option string ('' removes it). Steam must be closed."""
        for cfg in self.localconfigs():
            text = cfg.read_text(encoding="utf-8", errors="replace")
            pristine = cfg.with_name("localconfig.vdf.gamepanel-orig.bak")
            if not pristine.exists():
                shutil.copy2(cfg, pristine)
            shutil.copy2(cfg, cfg.with_name("localconfig.vdf.gamepanel.bak"))
            tree = vdf_parse(text)
            apps = vdf_path(tree, ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps"], create=True)
            for appid, value in mapping.items():
                app = vdf_path(apps, [appid], create=True)
                pair = vdf_find(app, "LaunchOptions")
                if value:
                    if pair is None:
                        app.append(["LaunchOptions", vdf_escape(value)])
                    else:
                        pair[1] = vdf_escape(value)
                elif pair is not None:
                    app.remove(pair)
            tmp = cfg.with_suffix(".vdf.gamepanel-tmp")
            tmp.write_text(vdf_dump(tree), encoding="utf-8")
            os.replace(tmp, cfg)

    def running(self):
        # This installation's client binary itself, not helpers under ubuntu12_32/steam-runtime/.
        if not self.found:
            return False
        pattern = re.escape(str(self.root)) + "/ubuntu12_32/steam( |$)"
        return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0

    def _cmd(self):
        return ["flatpak", "run", FLATPAK_ID] if self.flatpak else ["steam"]

    def shutdown(self):
        subprocess.Popen(self._cmd() + ["-shutdown"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    def launch(self):
        subprocess.Popen(self._cmd() + ["-silent"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    def gamescope_available(self):
        if self.flatpak:
            r = subprocess.run(["flatpak", "list", "--columns=application"], capture_output=True, text=True)
            return "org.freedesktop.Platform.VulkanLayer.gamescope" in r.stdout
        return shutil.which("gamescope") is not None

    def local_art(self, appid, kind):
        # Newer Steam clients call the cover library_capsule.jpg and the header library_header.jpg.
        names = {"capsule": ["library_600x900.jpg", "library_600x900_2x.jpg", "library_capsule.jpg"],
                 "hero": ["library_hero.jpg"], "logo": ["logo.png"],
                 "header": ["header.jpg", "library_header.jpg"]}[kind]
        if self.found:
            grid = {"capsule": f"{appid}p", "hero": f"{appid}_hero", "logo": f"{appid}_logo", "header": appid}[kind]
            for g in (self.root / "userdata").glob("*/config/grid"):
                for ext in ("png", "jpg", "jpeg", "webp"):
                    if (g / f"{grid}.{ext}").exists():
                        return g / f"{grid}.{ext}"
            cache = self.root / "appcache/librarycache"
            for n in names:
                if (cache / f"{appid}_{n}").exists():
                    return cache / f"{appid}_{n}"
                if (cache / appid).is_dir():
                    hit = next((cache / appid).rglob(n), None)
                    if hit:
                        return hit
        cached = CACHE_DIR / f"{appid}_{names[0]}"
        return cached if cached.exists() else None


def detect_display():
    """(width, height, refresh) of the current mode, best effort."""
    try:
        env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
        out = subprocess.run(["kscreen-doctor", "-o"], capture_output=True, text=True, timeout=3, env=env).stdout
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        m = re.search(r"(\d+)x(\d+)@([\d.]+)\*", out)
        if m:
            return int(m[1]), int(m[2]), round(float(m[3]))
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        out = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"(\d+)x(\d+)\s+.*?([\d.]+)\*", out)
        if m:
            return int(m[1]), int(m[2]), round(float(m[3]))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return 1920, 1080, 60


# ─────────────────────────────── Config & launch profiles ───────────────────────────────

WRAPPER = r'''#!/usr/bin/env bash
# Game Panel launch wrapper. Generated by Game Panel; edits will be overwritten.
appid="$1"; shift
dir="$(dirname "$(readlink -f "$0")")"
GP_GAMESCOPE=(); GP_ENV=(); GP_WRAP=(); GP_ARGS=()
# Flatpak Steam's gamescope extension
[ -d /usr/lib/extensions/vulkan/gamescope/bin ] && PATH="$PATH:/usr/lib/extensions/vulkan/gamescope/bin"
profile="$dir/profiles/$appid.sh"
[ -f "$profile" ] || profile="$dir/profiles/default.sh"
[ -f "$profile" ] && . "$profile"
if [ ${#GP_GAMESCOPE[@]} -gt 0 ] && ! command -v gamescope >/dev/null 2>&1; then
    echo "Game Panel: gamescope not found, launching without it" >&2
    GP_GAMESCOPE=()
fi
# The environment goes after gamescope's "--" so only the game gets it: MANGOHUD=1 on
# gamescope itself loads MangoHud into the compositor and breaks the game's swapchain.
exec "${GP_GAMESCOPE[@]}" env "${GP_ENV[@]}" "${GP_WRAP[@]}" "$@" "${GP_ARGS[@]}"
'''


def split(s):
    try:
        return shlex.split(s or "")
    except ValueError:
        return (s or "").split()


def parse_launch_options(lo):
    """Turn existing Steam launch options into a Game Panel game entry."""
    entry = {"mode": "global", "custom": False, "settings": dict(DEFAULT_SETTINGS),
             "env": "", "wrappers": "", "args": "", "original": lo}
    toks = split(lo)
    if not toks:
        return entry
    if "%command%" not in toks:
        entry["args"] = lo
        return entry
    i = toks.index("%command%")
    pre, post = toks[:i], toks[i + 1:]
    gs = None
    if "gamescope" in pre:
        j = pre.index("gamescope")
        after = pre[j + 1:]
        k = after.index("--") if "--" in after else len(after)
        gs, pre = after[:k], pre[:j] + after[k + 1:]
    env, wrappers = [], []
    for t in pre:
        if t == "env":
            continue
        (env if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) else wrappers).append(t)
    if gs is not None:
        s, extra, it = dict(DEFAULT_SETTINGS), [], iter(gs)
        s["display"] = "windowed"
        nums = {"-W": "output_w", "--output-width": "output_w", "-H": "output_h", "--output-height": "output_h",
                "-w": "game_w", "--nested-width": "game_w", "-h": "game_h", "--nested-height": "game_h",
                "-r": "refresh", "--nested-refresh": "refresh", "--framerate-limit": "fps_limit",
                "--sharpness": "sharpness", "--fsr-sharpness": "sharpness"}
        for t in it:
            if t in nums:
                v = next(it, "0")
                s[nums[t]] = int(float(v)) if re.match(r"^[\d.]+$", v) else 0
            elif t in ("-f", "--fullscreen"):
                s["display"] = "fullscreen"
            elif t in ("-b", "--borderless"):
                s["display"] = "borderless"
            elif t in ("-S", "--scaler"):
                s["scaler"] = next(it, "auto")
            elif t in ("-F", "--filter"):
                s["filter"] = next(it, "linear")
            elif t in ("-U", "--fsr-upscaling"):
                s["filter"] = "fsr"
            elif t in ("-Y", "--nis-upscaling"):
                s["filter"] = "nis"
            elif t == "--adaptive-sync":
                s["adaptive_sync"] = True
            elif t == "--hdr-enabled":
                s["hdr"] = True
            elif t == "--force-grab-cursor":
                s["grab_cursor"] = True
            elif t == "--mangoapp":
                s["mangohud"] = True
            else:
                extra.append(t)
        if "MANGOHUD=1" in env:
            env.remove("MANGOHUD=1")
            s["mangohud"] = True
        s["extra"] = shlex.join(extra)
        entry.update(mode="on", custom=True, settings=s)
    entry["env"] = shlex.join(env)
    entry["wrappers"] = shlex.join(wrappers)
    entry["args"] = shlex.join(post)
    return entry


class Store:
    def __init__(self, steam):
        self.steam = steam
        self.path = CONFIG_DIR / "config.json"
        data = {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            pass
        self.global_enabled = data.get("global_enabled", False)
        self.native = list(detect_display())
        self.global_settings = {**DEFAULT_SETTINGS, **data.get("global", {})}
        self.games = data.get("games", {})
        # Only set when picked in the header; otherwise the running/most recent Steam is used.
        self.chosen_root = data.get("steam_root")
        for g in self.games.values():
            g["settings"] = {**DEFAULT_SETTINGS, **g.get("settings", {})}

    def game(self, appid):
        return self.games.setdefault(appid, parse_launch_options(""))

    def effective(self, appid):
        g = self.game(appid)
        on = self.global_enabled if g["mode"] == "global" else g["mode"] == "on"
        return on, (g["settings"] if g["custom"] else self.global_settings)

    def gamescope_args(self, s):
        nw, nh, nr = self.native
        ow, oh = s["output_w"] or nw, s["output_h"] or nh
        gw, gh = s["game_w"] or ow, s["game_h"] or oh
        a = ["gamescope", "-W", str(ow), "-H", str(oh), "-w", str(gw), "-h", str(gh)]
        if s["refresh"] or nr:
            a += ["-r", str(s["refresh"] or nr)]
        a += {"fullscreen": ["-f"], "borderless": ["-b"]}.get(s["display"], [])
        if s["scaler"] != "auto":
            a += ["-S", s["scaler"]]
        if s["filter"] != "linear":
            a += ["-F", s["filter"]]
            if s["filter"] in ("fsr", "nis"):
                a += ["--sharpness", str(s["sharpness"])]
        if s["adaptive_sync"]:
            a.append("--adaptive-sync")
        if s["hdr"]:
            a.append("--hdr-enabled")
        if s["grab_cursor"]:
            a.append("--force-grab-cursor")
        return a + split(s["extra"]) + ["--"]

    def profile_for(self, s):
        """(gamescope, env) for a set of gamescope settings."""
        env = []
        # The FPS cap uses MangoHud's limiter (loaded hidden when the overlay is off);
        # gamescope's --framerate-limit only divides the refresh rate.
        if s["mangohud"] or s["fps_limit"]:
            env.append("MANGOHUD=1")
        if s["fps_limit"]:
            opts = ["read_cfg", f"fps_limit={s['fps_limit']}"] + ([] if s["mangohud"] else ["no_display"])
            env.append("MANGOHUD_CONFIG=" + ",".join(opts))
        if s["hdr"]:
            env.append("DXVK_HDR=1")
        return self.gamescope_args(s), env

    def profile(self, appid):
        """(gamescope, env, wrappers, args) the wrapper will use for this game."""
        g = self.game(appid)
        on, s = self.effective(appid)
        env = [t for t in split(g["env"]) if "=" in t]
        gamescope = []
        if on:
            gamescope, extra_env = self.profile_for(s)
            env += extra_env
        return gamescope, env, split(g["wrappers"]), split(g["args"])

    def hook(self, appid):
        return f"{shlex.quote(str(self.steam.data_dir / 'gp-run'))} {appid} %command%"

    def preview(self, appid):
        gamescope, env, wrappers, args = self.profile(appid)
        parts = gamescope + (["env"] + env if env else []) + wrappers + ["%command%"] + args
        return " ".join(shlex.quote(p) if p != "%command%" else p for p in parts)

    def save(self, appids):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {"global_enabled": self.global_enabled, "native": self.native,
                "steam_root": self.chosen_root,
                "global": self.global_settings, "games": self.games}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)

        prof_dir = self.steam.data_dir / "profiles"
        prof_dir.mkdir(parents=True, exist_ok=True)
        wrapper = self.steam.data_dir / "gp-run"
        if not wrapper.exists() or wrapper.read_text() != WRAPPER:
            wrapper.write_text(WRAPPER)
        wrapper.chmod(0o755)

        def write(name, gamescope, env, wrappers, args):
            q = lambda xs: " ".join(shlex.quote(x) for x in xs)
            (prof_dir / name).write_text(
                "# Generated by Game Panel; edits will be overwritten.\n"
                f"GP_GAMESCOPE=({q(gamescope)})\nGP_ENV=({q(env)})\nGP_WRAP=({q(wrappers)})\n"
                f"GP_ARGS=({q(args)})\n")

        for appid in appids:
            write(f"{appid}.sh", *self.profile(appid))
        s = self.global_settings
        write("default.sh", *self.profile_for(s) if self.global_enabled else ([], []), [], [])


# ─────────────────────────────────────── Theme ───────────────────────────────────────
# Game Panel wears Shale's own look: it loads the same theme module Shale Update uses
# (/usr/lib/shale/shale/theme.py), which builds its colours from the KDE colour scheme in
# kdeglobals. Like shale-theme-watcher, we listen for KDE's notifyChange signal and re-read
# the theme, so switching colour schemes recolours the window straight away.

SHALE_LIB = "/usr/lib/shale"


def _kde_color(group, key, default):
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str
    home = os.environ.get("XDG_CONFIG_HOME") or str(HOME / ".config")
    try:
        cfg.read(["/etc/xdg/kdeglobals", os.path.join(home, "kdedefaults", "kdeglobals"),
                  os.path.join(home, "kdeglobals")], encoding="utf-8")
        r, g, b = (int(v) for v in cfg.get(group, key).split(",")[:3])
        return QColor(r, g, b).name()
    except (configparser.Error, ValueError, UnicodeDecodeError):
        return default


def rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


class Theme:
    def __init__(self):
        self.mod = None
        self.load()

    def load(self):
        try:
            if SHALE_LIB not in sys.path:
                sys.path.insert(0, SHALE_LIB)
            from shale import theme as shale_theme
            # theme.py reads kdeglobals when imported, so reload it to pick up a new scheme.
            self.mod = importlib.reload(shale_theme)
        except Exception:
            self.mod = None
        defaults = {"BG": "#1e1e1e", "SURFACE": "#262626", "SURFACE_HOVER": "#2e2e2e", "BORDER": "#363636",
                    "SCROLL_HANDLE": "#444444", "INDICATOR_BORDER": "#5a5a5a", "LOG_BG": "#161616",
                    "TEXT": "#ececec", "MUTED": "#9a9a9a", "DISABLED": "#5e5e5e", "LOG_TEXT": "#b6b6b6",
                    "ACCENT": "#3584e4", "ACCENT_TEXT": "#ffffff", "ACCENT_HOVER": "#4990e6",
                    "DANGER": "#e5534b", "DARK": True}
        for name, default in defaults.items():
            setattr(self, name, getattr(self.mod, name, default))
        self.POSITIVE = _kde_color("Colors:Window", "ForegroundPositive", "#27ae60")
        self.NEUTRAL = _kde_color("Colors:Window", "ForegroundNeutral", "#f67400")
        self.VISITED = _kde_color("Colors:Window", "ForegroundVisited", "#9b59b6")

    def apply(self, app):
        if self.mod:
            self.mod.apply(app)
            base = self.mod.QSS
        else:
            app.setStyle("Fusion")
            pal = QPalette()
            for role, col in ((QPalette.Window, self.BG), (QPalette.Base, self.SURFACE),
                              (QPalette.Text, self.TEXT), (QPalette.WindowText, self.TEXT),
                              (QPalette.Button, self.SURFACE), (QPalette.ButtonText, self.TEXT),
                              (QPalette.Highlight, self.ACCENT), (QPalette.HighlightedText, self.ACCENT_TEXT)):
                pal.setColor(role, QColor(col))
            app.setPalette(pal)
            base = f"QWidget {{ background: {self.BG}; color: {self.TEXT}; font-size: 11pt; }}"
        app.setStyleSheet(base + self.extra_qss())

    def extra_qss(self):
        """Game Panel's own widgets, in the same flat Shale style."""
        t = self
        inputs = "QLineEdit, QComboBox, QSpinBox"
        in_panel = ", ".join(f'QFrame[role="panel"] {w}' for w in ("QLineEdit", "QComboBox", "QSpinBox"))
        return f"""
QLabel[role="title"] {{ font-size: 17pt; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[role="gameTitle"] {{ font-size: 16pt; font-weight: 600; }}
QLabel[role="cardTitle"] {{ font-weight: 600; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame[role="panel"] QWidget, QFrame[role="card"] QWidget, QFrame[role="banner"] QWidget {{ background: transparent; }}
QSpinBox {{ background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: 8px;
    padding: 8px 12px; selection-background-color: {t.ACCENT}; }}
QSpinBox:focus {{ border: 1px solid {t.ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
{in_panel} {{ background: {t.BG}; border: 1px solid {t.BORDER}; border-radius: 8px; padding: 6px 10px; }}
{", ".join(f'QFrame[role="panel"] {w}:focus' for w in ("QLineEdit", "QComboBox", "QSpinBox"))} {{ border: 1px solid {t.ACCENT}; }}
QFrame[role="panel"] QSpinBox QLineEdit, QSpinBox QLineEdit {{ background: transparent; border: none; padding: 0; }}
QFrame[role="banner"] QPushButton[role="primary"] {{ background: {t.ACCENT}; color: {t.ACCENT_TEXT}; }}
QFrame[role="banner"] QPushButton[role="primary"]:hover {{ background: {t.ACCENT_HOVER}; }}
QFrame[role="panel"] QPushButton {{ background: {t.BG}; padding: 7px 16px; }}
QFrame[role="panel"] QPushButton:hover {{ background: {t.SURFACE_HOVER}; }}
QPushButton[role="seg"] {{ border-radius: 0; padding: 7px 10px; }}
QPushButton[role="seg"][pos="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton[role="seg"][pos="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QFrame[role="panel"] QPushButton[role="seg"]:checked {{ background: {t.ACCENT}; color: {t.ACCENT_TEXT};
    border-color: {t.ACCENT}; font-weight: 600; }}
QPushButton[role="primary"] {{ padding: 8px 20px; }}
QToolButton {{ background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: 8px; padding: 8px 14px; }}
QToolButton:hover {{ background: {t.SURFACE_HOVER}; }}
QToolButton::menu-indicator {{ image: none; }}
QMenu {{ background: {t.SURFACE}; border: 1px solid {t.BORDER}; padding: 4px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.ACCENT}; color: {t.ACCENT_TEXT}; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t.TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QFrame[role="line"] {{ background: {t.BORDER}; border: none; }}
QLabel[role="preview"] {{ background: {t.LOG_BG}; border: 1px solid {t.BORDER}; border-radius: 8px;
    padding: 10px; color: {t.LOG_TEXT}; font-family: monospace; font-size: 9pt; }}
QFrame[role="panel"] QLabel[role="preview"] {{ background: {t.LOG_BG}; }}
"""


T = Theme()


# ─────────────────────────────────────── Widgets ───────────────────────────────────────

class Switch(QAbstractButton):
    def __init__(self, parent=None, big=False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(*((54, 30) if big else (42, 24)))
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_quiet(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._anim.stop()
        self.offset = 1.0 if on else 0.0

    def _get(self):
        return self._offset

    def _set(self, v):
        self._offset = v
        self.update()

    offset = Property(float, _get, _set)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        off, on = QColor(T.INDICATOR_BORDER), QColor(T.ACCENT)
        t = self._offset
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * t
        p.setBrush(QColor("#ffffff" if T.DARK or t < 0.5 else T.ACCENT_TEXT))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class Chip(QLabel):
    def set(self, text, color):
        self.setText(text)
        self.setStyleSheet(f"background: {rgba(color, 40)}; color: {color};"
                           "border-radius: 9px; padding: 2px 8px; font-size: 8pt; font-weight: 700;")


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=16):
        super().__init__(parent)
        self._items, self._sp = [], spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        for it in self._items:
            if it.widget() and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and line > 0:
                x, y, line = r.x(), y + line + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


def cover(pix, w, h):
    """Scale-and-crop a pixmap to fill w×h."""
    s = pix.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)


class ArtManager:
    """Finds game art locally, falling back to Steam's CDN (cached on disk)."""

    def __init__(self, steam):
        self.steam = steam
        self.net = QNetworkAccessManager()
        self.mem, self.waiting, self.failed = {}, {}, set()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get(self, appid, kind, cb):
        key = (appid, kind)
        if key in self.mem:
            cb(self.mem[key])
            return
        path = self.steam.local_art(appid, kind)
        if path:
            pix = QPixmap(str(path))
            if not pix.isNull():
                self.mem[key] = pix
                cb(pix)
                return
        if key in self.failed:
            cb(None)
            return
        if key in self.waiting:
            self.waiting[key].append(cb)
            return
        self.waiting[key] = [cb]
        name = {"capsule": "library_600x900.jpg", "hero": "library_hero.jpg",
                "logo": "logo.png", "header": "header.jpg"}[kind]
        req = QNetworkRequest(QUrl(CDN.format(appid=appid, name=name)))
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        reply = self.net.get(req)
        reply.finished.connect(lambda: self._done(reply, key, name))

    def _done(self, reply, key, name):
        pix = None
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll().data()
            p = QPixmap()
            if data and p.loadFromData(data):
                pix = p
                (CACHE_DIR / f"{key[0]}_{name}").write_bytes(data)
        reply.deleteLater()
        if pix is None:
            self.failed.add(key)
        else:
            self.mem[key] = pix
        for cb in self.waiting.pop(key, []):
            cb(pix)


class CapsuleArt(QWidget):
    def __init__(self, name, w, h, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.name, self.pix, self.dim = name, None, False

    def set_pixmap(self, pix):
        self.pix = cover(pix, self.width() * 2, self.height() * 2) if pix else None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.setClipPath(path)
        if self.pix:
            p.drawPixmap(self.rect(), self.pix)
        else:
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, QColor(T.SURFACE_HOVER))
            g.setColorAt(1, QColor(T.BG))
            p.fillRect(r, g)
            f = QFont(self.font())
            f.setPointSize(13)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(T.TEXT))
            p.drawText(r.adjusted(14, 14, -14, -14), Qt.AlignCenter | Qt.TextWordWrap, self.name)
        if self.dim:
            p.fillRect(r, QColor(0, 0, 0, 90))


class GameCard(QFrame):
    clicked = Signal(str)
    toggled = Signal(str, bool)
    W, H = 176, 264

    def __init__(self, game, art, parent=None):
        super().__init__(parent)
        self.appid, self.name = game["appid"], game["name"]
        self.selected = False
        self.setProperty("role", "card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(self.W + 12)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 8)
        lay.setSpacing(8)
        self.art = CapsuleArt(self.name, self.W, self.H)
        lay.addWidget(self.art)
        title = QLabel(QFontMetrics(self.font()).elidedText(self.name, Qt.ElideRight, self.W))
        title.setProperty("role", "cardTitle")
        lay.addWidget(title)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.chip = Chip()
        row.addWidget(self.chip)
        row.addStretch()
        self.switch = Switch()
        self.switch.toggled.connect(lambda on: self.toggled.emit(self.appid, on))
        row.addWidget(self.switch)
        lay.addLayout(row)
        art.get(self.appid, "capsule", self._art)
        self._style()

    def _art(self, pix):
        if pix is None:
            self.art.set_pixmap(None)
        else:
            self.art.set_pixmap(pix)

    def _style(self):
        self.setProperty("selected", "true" if self.selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_selected(self, on):
        self.selected = on
        self._style()

    def update_state(self, on, mode, custom, linked):
        self.switch.set_quiet(on)
        self.art.dim = not on
        self.art.update()
        if not linked:
            self.chip.set("NOT LINKED", T.NEUTRAL)
        elif mode == "global":
            self.chip.set("GLOBAL", T.MUTED)
        elif on and custom:
            self.chip.set("CUSTOM", T.VISITED)
        elif on:
            self.chip.set("ALWAYS ON", T.ACCENT)
        else:
            self.chip.set("ALWAYS OFF", T.MUTED)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.appid)


class ResPicker(QWidget):
    changed = Signal()
    PRESETS = [(3840, 2160), (3440, 1440), (2560, 1440), (2560, 1080), (1920, 1080), (1600, 900), (1280, 800), (1280, 720)]

    def __init__(self, auto_label, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = QComboBox()
        self.combo.addItem(auto_label, "0x0")
        for w, h in self.PRESETS:
            self.combo.addItem(f"{w} × {h}", f"{w}x{h}")
        self.combo.addItem("Custom…", "custom")
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(8)
        self.w, self.h = QSpinBox(), QSpinBox()
        for s in (self.w, self.h):
            s.setRange(320, 15360)
            s.setFixedWidth(64)
            s.valueChanged.connect(self.changed)
        self.x = QLabel("×")
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.w)
        lay.addWidget(self.x)
        lay.addWidget(self.h)
        self.combo.currentIndexChanged.connect(self._combo)
        self._custom(False)

    def _custom(self, on):
        for wd in (self.w, self.x, self.h):
            wd.setVisible(on)

    def _combo(self):
        self._custom(self.combo.currentData() == "custom")
        self.changed.emit()

    def value(self):
        d = self.combo.currentData()
        if d == "custom":
            return self.w.value(), self.h.value()
        w, h = d.split("x")
        return int(w), int(h)

    def set_value(self, w, h):
        for wd in (self.combo, self.w, self.h):
            wd.blockSignals(True)
        i = self.combo.findData(f"{w}x{h}")
        if i < 0:
            i = self.combo.count() - 1
        self.w.setValue(w or 1920)
        self.h.setValue(h or 1080)
        self.combo.setCurrentIndex(i)
        self._custom(self.combo.currentData() == "custom")
        for wd in (self.combo, self.w, self.h):
            wd.blockSignals(False)


def combo(items):
    c = QComboBox()
    c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(8)
    for label, data in items:
        c.addItem(label, data)
    return c


class SettingsForm(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.output = ResPicker("Native display")
        self.game = ResPicker("Same as output")
        self.refresh = QSpinBox()
        self.refresh.setRange(0, 500)
        self.refresh.setSpecialValueText("Native")
        self.refresh.setToolTip("How often gamescope's own window refreshes. This doesn't cap the game; use FPS cap.")
        self.refresh.setSuffix(" Hz")
        self.display = combo([("Fullscreen", "fullscreen"), ("Borderless window", "borderless"), ("Window", "windowed")])
        self.scaler = combo([("Auto", "auto"), ("Fit", "fit"), ("Fill", "fill"), ("Stretch", "stretch"), ("Integer", "integer")])
        self.filter = combo([("Linear (none)", "linear"), ("AMD FSR", "fsr"), ("NVIDIA NIS", "nis"),
                             ("Nearest", "nearest"), ("Pixel", "pixel")])
        self.sharp = QSlider(Qt.Horizontal)
        self.sharp.setRange(0, 20)
        self.sharp_lbl = QLabel()
        self.sharp_lbl.setFixedWidth(26)
        sharp_row = QWidget()
        sr = QHBoxLayout(sharp_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(self.sharp)
        sr.addWidget(self.sharp_lbl)
        self.fps = QSpinBox()
        self.fps.setRange(0, 1000)
        self.fps.setSpecialValueText("Unlimited")
        self.fps.setToolTip("Caps the game's frame rate (uses MangoHud's limiter).")
        self.fps.setSuffix(" fps")
        self.vrr, self.hdr, self.mango, self.grab = Switch(), Switch(), Switch(), Switch()
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("e.g. --expose-wayland")

        form.addRow("Output resolution", self.output)
        form.addRow("Game resolution", self.game)
        form.addRow("FPS cap", self.fps)
        form.addRow("Display refresh rate", self.refresh)
        form.addRow("Window mode", self.display)
        form.addRow("Scaling", self.scaler)
        form.addRow("Upscaler", self.filter)
        self.sharp_label = QLabel("Sharpness")
        form.addRow(self.sharp_label, sharp_row)
        self.sharp_row = sharp_row
        form.addRow("Adaptive sync (VRR)", self.vrr)
        form.addRow("HDR", self.hdr)
        form.addRow("MangoHud overlay", self.mango)
        form.addRow("Lock cursor to game", self.grab)
        form.addRow("Extra gamescope args", self.extra)

        for s in (self.output, self.game):
            s.changed.connect(self.changed)
        for s in (self.refresh, self.fps):
            s.valueChanged.connect(self.changed)
        for c in (self.display, self.scaler, self.filter):
            c.currentIndexChanged.connect(self.changed)
        for s in (self.vrr, self.hdr, self.mango, self.grab):
            s.toggled.connect(self.changed)
        self.sharp.valueChanged.connect(self.changed)
        self.extra.textChanged.connect(self.changed)
        self.changed.connect(self._sync)

    def _sync(self):
        up = self.filter.currentData() in ("fsr", "nis")
        self.sharp_row.setVisible(up)
        self.sharp_label.setVisible(up)
        self.sharp_lbl.setText(str(self.sharp.value()))
        self.sharp.setToolTip("0 = sharpest, 20 = softest")

    def values(self):
        (ow, oh), (gw, gh) = self.output.value(), self.game.value()
        return {"output_w": ow, "output_h": oh, "game_w": gw, "game_h": gh,
                "refresh": self.refresh.value(), "display": self.display.currentData(),
                "scaler": self.scaler.currentData(), "filter": self.filter.currentData(),
                "sharpness": self.sharp.value(), "fps_limit": self.fps.value(),
                "adaptive_sync": self.vrr.isChecked(), "hdr": self.hdr.isChecked(),
                "mangohud": self.mango.isChecked(), "grab_cursor": self.grab.isChecked(),
                "extra": self.extra.text().strip()}

    def set_values(self, s):
        self.blockSignals(True)
        self.output.set_value(s["output_w"], s["output_h"])
        self.game.set_value(s["game_w"], s["game_h"])
        for w, v in ((self.refresh, s["refresh"]), (self.fps, s["fps_limit"]), (self.sharp, s["sharpness"])):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        for c, v in ((self.display, s["display"]), (self.scaler, s["scaler"]), (self.filter, s["filter"])):
            c.blockSignals(True)
            c.setCurrentIndex(max(0, c.findData(v)))
            c.blockSignals(False)
        for sw, v in ((self.vrr, s["adaptive_sync"]), (self.hdr, s["hdr"]),
                      (self.mango, s["mangohud"]), (self.grab, s["grab_cursor"])):
            sw.set_quiet(v)
        self.extra.blockSignals(True)
        self.extra.setText(s["extra"])
        self.extra.blockSignals(False)
        self.blockSignals(False)
        self._sync()


class Hero(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(190)
        self.hero = self.logo = None
        self.name = ""

    def set(self, name, hero, logo):
        self.name, self.hero, self.logo = name, hero, logo
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.setClipPath(path)
        if self.hero:
            p.drawPixmap(self.rect(), cover(self.hero, self.width(), self.height()))
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            g.setColorAt(0, QColor(T.SURFACE_HOVER))
            g.setColorAt(1, QColor(T.BG))
            p.fillRect(r, g)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0.35, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(10, 13, 18, 230))
        p.fillRect(r, g)
        if self.logo:
            box = QRectF(18, 18, r.width() * 0.6, r.height() - 36)
            lg = self.logo.scaled(int(box.width()), int(box.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(int(box.left()), int(box.bottom() - lg.height()), lg)
        else:
            f = QFont(self.font())
            f.setPointSize(18)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(r.adjusted(18, 18, -18, -18), Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap, self.name)


def section(title, subtitle=None):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setProperty("role", "section")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setProperty("role", "muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return box


def switch_row(title, subtitle, sw):
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(section(title, subtitle), 1)
    lay.addWidget(sw, 0, Qt.AlignVCenter)
    return row


def panel():
    f = QFrame()
    f.setProperty("role", "panel")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 18, 18, 18)
    lay.setSpacing(14)
    return f, lay


def scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(widget)
    return sa


# ─────────────────────────────────────── Main window ───────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme("shale-game-panel", QIcon.fromTheme("input-gaming")))
        self.resize(1440, 900)
        try:
            saved_root = json.loads((CONFIG_DIR / "config.json").read_text()).get("steam_root")
        except (OSError, ValueError):
            saved_root = None
        self.steam = Steam.pick(saved_root)
        self.store = Store(self.steam)
        self.art = ArtManager(self.steam)
        self.cards, self.games, self.current = {}, [], None
        self.launch_opts = {}
        self._loading = False
        self._save_timer = QTimer(self, singleShot=True, interval=250, timeout=self._save)
        self._poll = QTimer(self, interval=500, timeout=self._poll_steam)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)
        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_global(), 0)
        body.addWidget(self._build_library(), 1)
        body.addWidget(self._build_detail(), 0)
        outer.addLayout(body, 1)
        outer.addWidget(self._build_banner())

        if not self.steam.found:
            QMessageBox.warning(self, APP_NAME, "Couldn't find a Steam installation.")
        self.reload()
        self._watch_theme()
        root.setFocusPolicy(Qt.StrongFocus)
        root.setFocus()

    # ── theme: follow KDE colour scheme changes, the way shale-theme-watcher does ──
    def _watch_theme(self):
        self._retheme_timer = QTimer(self, singleShot=True, interval=300, timeout=self.retheme)
        self._theme_proc = QProcess(self)
        self._theme_proc.readyReadStandardOutput.connect(self._theme_signal)
        self._theme_proc.start("dbus-monitor", ["--session", "type='signal',interface='org.kde.KGlobalSettings',"
                                                "member='notifyChange'"])

    def _theme_signal(self):
        if b"notifyChange" in self._theme_proc.readAllStandardOutput().data():
            self._retheme_timer.start()

    def retheme(self):
        T.load()
        T.apply(QApplication.instance())
        self._update_gs_warn()
        self.refresh_states()
        for w in self.findChildren(QWidget):
            w.update()

    def closeEvent(self, e):
        if self._theme_proc.state() != QProcess.NotRunning:
            self._theme_proc.kill()
            self._theme_proc.waitForFinished(1000)
        super().closeEvent(e)

    # ── layout ──
    def _build_header(self):
        h = QWidget()
        lay = QHBoxLayout(h)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(QIcon.fromTheme("shale-game-panel", QIcon.fromTheme("input-gaming")).pixmap(48, 48))
        lay.addWidget(logo, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(APP_NAME)
        t.setProperty("role", "title")
        self.subtitle = QLabel()
        self.subtitle.setProperty("role", "subtitle")
        col.addWidget(t)
        col.addWidget(self.subtitle)
        lay.addLayout(col)
        lay.addStretch()
        self.gs_warn = Chip()
        lay.addWidget(self.gs_warn)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        # Both native and Flatpak Steam installed: choose which one to manage.
        self.steam_choice = QComboBox()
        for root in Steam.installs():
            self.steam_choice.addItem(Steam(root).label, str(root))
        self.steam_choice.setCurrentIndex(max(0, self.steam_choice.findData(str(self.steam.root))))
        self.steam_choice.setVisible(self.steam_choice.count() > 1)
        self.steam_choice.currentIndexChanged.connect(self._steam_changed)
        lay.addWidget(self.steam_choice)
        lay.addSpacing(8)
        refresh = QPushButton("Rescan")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.reload)
        lay.addWidget(refresh)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Open profiles folder", lambda: subprocess.Popen(
            ["xdg-open", str(self.steam.data_dir)], start_new_session=True))
        menu.addAction("Unlink all games (restore original launch options)", self.unlink_all)
        more.setMenu(menu)
        lay.addWidget(more)
        return h

    def _build_global(self):
        f, lay = panel()
        f.setFixedWidth(400)
        self.global_switch = Switch(big=True)
        self.global_switch.toggled.connect(self._global_toggled)
        lay.addWidget(switch_row("Gamescope everywhere",
                                 "Run every game inside gamescope unless a game says otherwise.",
                                 self.global_switch))
        line = QFrame()
        line.setFixedHeight(1)
        line.setProperty("role", "line")
        lay.addWidget(line)
        hdr = QHBoxLayout()
        hdr.addWidget(section("Default settings", "Used by every game without its own settings."), 1)
        det = QPushButton("Detect display")
        det.clicked.connect(self._detect)
        hdr.addWidget(det, 0, Qt.AlignTop)
        lay.addLayout(hdr)
        self.native_lbl = QLabel()
        self.native_lbl.setProperty("role", "muted")
        lay.addWidget(self.native_lbl)
        self.global_form = SettingsForm()
        self.global_form.changed.connect(self._global_changed)
        lay.addWidget(self.global_form)
        lay.addStretch()
        sa = scroll(f)
        sa.setFixedWidth(410)
        return sa

    def _build_library(self):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.setContentsMargins(4, 0, 0, 0)
        top.addWidget(section("Library"))
        self.lib_stats = QLabel()
        self.lib_stats.setProperty("role", "muted")
        top.addWidget(self.lib_stats)
        top.addStretch()
        v.addLayout(top)
        self.grid_host = QWidget()
        self.flow = FlowLayout(self.grid_host, spacing=10)
        self.empty = QLabel("No installed games found.")
        self.empty.setProperty("role", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        v.addWidget(scroll(self.grid_host), 1)
        return wrap

    def _build_detail(self):
        f, lay = panel()
        self.detail_frame = f
        self.hero = Hero()
        lay.addWidget(self.hero)
        self.d_title = QLabel()
        self.d_title.setProperty("role", "gameTitle")
        self.d_title.setWordWrap(True)
        lay.addWidget(self.d_title)

        lay.addWidget(section("Gamescope for this game"))
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        for i, (label, mode) in enumerate((("Follow global", "global"), ("Always on", "on"), ("Always off", "off"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("role", "seg")
            b.setProperty("pos", "first" if i == 0 else "last" if i == 2 else "mid")
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("mode", mode)
            self.mode_group.addButton(b)
            seg.addWidget(b)
        self.mode_group.buttonClicked.connect(self._mode_clicked)
        lay.addLayout(seg)
        self.d_state = QLabel()
        self.d_state.setProperty("role", "muted")
        self.d_state.setWordWrap(True)
        lay.addWidget(self.d_state)

        self.custom_switch = Switch()
        self.custom_switch.toggled.connect(self._custom_toggled)
        lay.addWidget(switch_row("Own gamescope settings", "Override the default settings for this game.",
                                 self.custom_switch))
        self.game_form = SettingsForm()
        self.game_form.changed.connect(self._game_changed)
        lay.addWidget(self.game_form)

        lay.addWidget(section("Launch extras", "Applied whether or not gamescope is on."))
        ex = QFormLayout()
        ex.setHorizontalSpacing(14)
        ex.setVerticalSpacing(10)
        self.env_edit, self.wrap_edit, self.args_edit = QLineEdit(), QLineEdit(), QLineEdit()
        self.env_edit.setPlaceholderText("PROTON_ENABLE_WAYLAND=1 DXVK_ASYNC=1")
        self.wrap_edit.setPlaceholderText("gamemoderun")
        self.args_edit.setPlaceholderText("-novid -skipintro")
        ex.addRow("Environment", self.env_edit)
        ex.addRow("Wrappers", self.wrap_edit)
        ex.addRow("Game arguments", self.args_edit)
        for e in (self.env_edit, self.wrap_edit, self.args_edit):
            e.textChanged.connect(self._extras_changed)
        lay.addLayout(ex)

        lay.addWidget(section("Effective launch command"))
        self.preview = QLabel()
        self.preview.setProperty("role", "preview")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.preview)
        self.d_link = QLabel()
        self.d_link.setProperty("role", "muted")
        self.d_link.setWordWrap(True)
        lay.addWidget(self.d_link)
        lay.addStretch()
        sa = scroll(f)
        sa.setFixedWidth(480)
        self.detail_scroll = sa
        return sa

    def _build_banner(self):
        b = QFrame()
        b.setProperty("role", "banner")
        lay = QHBoxLayout(b)
        lay.setContentsMargins(16, 10, 10, 10)
        self.banner_dot = QLabel("●")
        lay.addWidget(self.banner_dot)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        lay.addWidget(self.banner_text, 1)
        self.banner_btn = QPushButton()
        self.banner_btn.setProperty("role", "primary")
        self.banner_btn.setCursor(Qt.PointingHandCursor)
        self.banner_btn.clicked.connect(self.link_games)
        lay.addWidget(self.banner_btn)
        self.banner = b
        return b

    # ── data ──
    def _steam_changed(self):
        self.steam = Steam(self.steam_choice.currentData())
        self.store.steam = self.steam
        self.store.chosen_root = str(self.steam.root)
        self.art = ArtManager(self.steam)
        self.current = None
        self.reload()

    def reload(self):
        self.games = self.steam.games() if self.steam.found else []
        try:
            self.launch_opts = self.steam.launch_options()
        except OSError:
            self.launch_opts = {}
        for g in self.games:
            if g["appid"] not in self.store.games:
                lo = self.launch_opts.get(g["appid"], "")
                self.store.games[g["appid"]] = parse_launch_options("" if self._is_hook(g["appid"], lo) else lo)

        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cards = {}
        for g in self.games:
            card = GameCard(g, self.art)
            card.clicked.connect(self.select)
            card.toggled.connect(self._card_toggled)
            self.flow.addWidget(card)
            self.cards[g["appid"]] = card
        self.empty.setVisible(not self.games)

        self._loading = True
        self.global_switch.set_quiet(self.store.global_enabled)
        self.global_form.set_values(self.store.global_settings)
        self._loading = False
        self._update_native()

        if self.steam.found:
            n = len(self.steam.libraries())
            self.subtitle.setText(f"{self.steam.label} · {n} {'library' if n == 1 else 'libraries'}")
            self.subtitle.setToolTip(str(self.steam.root))
        self.has_gamescope = self.steam.found and self.steam.gamescope_available()
        self._update_gs_warn()
        ids = [g["appid"] for g in self.games]
        keep = self.current if self.current in ids else (ids[0] if ids else None)
        self.current = None
        if keep:
            self.select(keep)
        else:
            self.detail_scroll.setVisible(False)
        self._filter()
        self.refresh_states()
        self._save()

    def _update_gs_warn(self):
        if self.has_gamescope:
            self.gs_warn.hide()
        else:
            self.gs_warn.set("GAMESCOPE NOT INSTALLED", T.DANGER)
            self.gs_warn.setToolTip("flatpak install org.freedesktop.Platform.VulkanLayer.gamescope"
                                    if self.steam.flatpak else "Install the gamescope package")
            self.gs_warn.show()

    def _is_hook(self, appid, lo):
        return f"gp-run {appid} %command%" in (lo or "")

    def linked(self, appid):
        return self._is_hook(appid, self.launch_opts.get(appid, ""))

    def _update_native(self):
        w, h, r = self.store.native
        self.native_lbl.setText(f"Native display: {w} × {h} @ {r} Hz")

    # ── state refresh ──
    def refresh_states(self):
        on_count = 0
        for appid, card in self.cards.items():
            g = self.store.game(appid)
            on, _ = self.store.effective(appid)
            on_count += on
            card.update_state(on, g["mode"], g["custom"], self.linked(appid))
        n = len(self.cards)
        self.lib_stats.setText(f"  {n} {'game' if n == 1 else 'games'} · {on_count} using gamescope")
        self._refresh_detail_state()
        self._refresh_banner()

    def _refresh_banner(self, busy=None):
        unlinked = [g for g in self.games if not self.linked(g["appid"])]
        if busy:
            color, text, btn = T.ACCENT, busy, None
        elif not self.games:
            color, text, btn = T.MUTED, "No games to manage yet.", None
        elif unlinked:
            n = len(unlinked)
            color = T.NEUTRAL
            text = (f"{n} game{'s' if n != 1 else ''} not linked yet. Game Panel sets each game's Steam launch option "
                    "once, and Steam has to be closed while it does. Your current launch options are kept.")
            btn = "Close Steam && link" if self.steam.running() else "Link games"
        else:
            color = T.POSITIVE
            text = "All games are linked. Changes apply the next time you launch a game; Steam doesn't need a restart."
            btn = None
        self.banner.setStyleSheet(f"QFrame[role=\"banner\"] {{ background: {rgba(color, 22)}; border-radius: 12px;"
                                  f" border: 1px solid {rgba(color, 90)}; }}")
        self.banner_dot.setStyleSheet(f"color: {color};")
        self.banner_text.setText(text)
        self.banner_btn.setVisible(bool(btn))
        if btn:
            self.banner_btn.setText(btn)

    def _refresh_detail_state(self):
        if not self.current:
            return
        appid = self.current
        g = self.store.game(appid)
        on, _ = self.store.effective(appid)
        for b in self.mode_group.buttons():
            b.setChecked(b.property("mode") == g["mode"])
        if g["mode"] == "global":
            self.d_state.setText(f"Following the global switch, so gamescope is currently {'ON' if on else 'OFF'}.")
        else:
            self.d_state.setText(f"Gamescope is always {'ON' if on else 'OFF'} for this game, whatever the global switch says.")
        self.custom_switch.setEnabled(on)
        self.game_form.setVisible(on and g["custom"])
        self.preview.setText(self.store.preview(appid))
        if self.linked(appid):
            self.d_link.setText("✓ Linked: Steam launches this game through Game Panel.")
        else:
            orig = g.get("original") or ""
            self.d_link.setText("⚠ Not linked yet, so these settings won't apply until you link it."
                                + (f"\nCurrent Steam launch options: {orig}" if orig else ""))

    # ── selection ──
    def select(self, appid):
        if self.current in self.cards:
            self.cards[self.current].set_selected(False)
        self.current = appid
        self.cards[appid].set_selected(True)
        self.detail_scroll.setVisible(True)
        game = next(g for g in self.games if g["appid"] == appid)
        g = self.store.game(appid)
        self.d_title.setText(game["name"])
        self.hero.set(game["name"], None, None)
        parts = {}

        def got(kind):
            def cb(pix):
                if self.current != appid:
                    return
                parts[kind] = pix
                if kind == "hero" and pix is None:
                    self.art.get(appid, "header", got("header"))
                    return
                self.hero.set(game["name"], parts.get("hero") or parts.get("header"), parts.get("logo"))
            return cb

        self.art.get(appid, "hero", got("hero"))
        self.art.get(appid, "logo", got("logo"))

        self._loading = True
        self.custom_switch.set_quiet(g["custom"])
        self.game_form.set_values(g["settings"])
        for e, k in ((self.env_edit, "env"), (self.wrap_edit, "wrappers"), (self.args_edit, "args")):
            e.blockSignals(True)
            e.setText(g[k])
            e.blockSignals(False)
        self._loading = False
        self._refresh_detail_state()

    def _filter(self):
        q = self.search.text().strip().lower()
        for g in self.games:
            self.cards[g["appid"]].setVisible(q in g["name"].lower())
        self.grid_host.updateGeometry()
        self.flow.invalidate()

    # ── edits ──
    def _changed(self):
        self.refresh_states()
        self._save_timer.start()

    def _save(self):
        try:
            self.store.save([g["appid"] for g in self.games])
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't save settings:\n{e}")

    def _global_toggled(self, on):
        self.store.global_enabled = on
        self._changed()

    def _global_changed(self):
        if not self._loading:
            self.store.global_settings = self.global_form.values()
            self._changed()

    def _detect(self):
        self.store.native = list(detect_display())
        self._update_native()
        self._changed()

    def _card_toggled(self, appid, on):
        g = self.store.game(appid)
        # Matching the global state goes back to following it; otherwise set an override.
        g["mode"] = "global" if on == self.store.global_enabled else ("on" if on else "off")
        if self.current != appid:
            self.select(appid)
        self._changed()

    def _mode_clicked(self, btn):
        if self.current:
            self.store.game(self.current)["mode"] = btn.property("mode")
            self._changed()

    def _custom_toggled(self, on):
        if self._loading or not self.current:
            return
        g = self.store.game(self.current)
        g["custom"] = on
        if on and g["settings"] == DEFAULT_SETTINGS:
            g["settings"] = dict(self.store.global_settings)
            self._loading = True
            self.game_form.set_values(g["settings"])
            self._loading = False
        self._changed()

    def _game_changed(self):
        if not self._loading and self.current:
            self.store.game(self.current)["settings"] = self.game_form.values()
            self._changed()

    def _extras_changed(self):
        if not self._loading and self.current:
            g = self.store.game(self.current)
            g["env"], g["wrappers"], g["args"] = (self.env_edit.text().strip(), self.wrap_edit.text().strip(),
                                                  self.args_edit.text().strip())
            self._changed()

    # ── linking (writes Steam's localconfig.vdf; Steam must be closed) ──
    def link_games(self):
        mapping = {g["appid"]: self.store.hook(g["appid"]) for g in self.games if not self.linked(g["appid"])}
        self._write_steam(mapping, "link")

    def unlink_all(self):
        mapping = {g["appid"]: self.store.game(g["appid"]).get("original", "")
                   for g in self.games if self.linked(g["appid"])}
        if not mapping:
            QMessageBox.information(self, APP_NAME, "No games are linked.")
            return
        if QMessageBox.question(self, APP_NAME, f"Restore the original Steam launch options for "
                                f"{len(mapping)} game(s)? Game Panel toggles will stop affecting them.") != QMessageBox.Yes:
            return
        self._write_steam(mapping, "unlink")

    def _write_steam(self, mapping, verb):
        if not mapping:
            return
        self._pending, self._relaunch = mapping, self.steam.running()
        if self._relaunch:
            if QMessageBox.question(
                    self, APP_NAME, "Steam will close for a moment so Game Panel can update the launch options, "
                                    "then open again.\n\nMake sure no game is running.") != QMessageBox.Yes:
                return
            self.steam.shutdown()
            self._poll_started = time.time()
            self.banner_btn.setEnabled(False)
            self._refresh_banner(busy="Waiting for Steam to close…")
            self._poll.start()
        else:
            self._finish_write()

    def _poll_steam(self):
        if not self.steam.running():
            self._poll.stop()
            self._refresh_banner(busy="Updating launch options…")
            QTimer.singleShot(2000, self._finish_write)  # let Steam finish flushing its config
        elif time.time() - self._poll_started > 45:
            self._poll.stop()
            self.banner_btn.setEnabled(True)
            self._refresh_banner()
            QMessageBox.warning(self, APP_NAME, "Steam didn't close. Quit it from its tray menu and try again.")

    def _finish_write(self):
        self.banner_btn.setEnabled(True)
        if self.steam.running():
            QMessageBox.warning(self, APP_NAME, "Steam is running again. Close it and try again.")
            self._refresh_banner()
            return
        try:
            self._save()
            self.steam.set_launch_options(self._pending)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't update Steam's config:\n{e}")
        self.launch_opts = self.steam.launch_options()
        if self._relaunch:
            self.steam.launch()
        self.refresh_states()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("game-panel")
    T.apply(app)
    w = MainWindow()
    if "--screenshot" in sys.argv:
        out = sys.argv[sys.argv.index("--screenshot") + 1]
        QTimer.singleShot(2500, lambda: (w.grab().save(out), app.quit()))
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
