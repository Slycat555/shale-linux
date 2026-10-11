"""Root helper for the Shale updater.

Updates Arch packages and system Flatpaks, printing JSON-lines progress:
    {"type": "step", "text": "...", "detail": "...", "progress": 0.4}
    {"type": "done", "restart": true, "changed": true}
    {"type": "error", "text": "..."}
"""

import json
import os
import re
import subprocess
import sys

KERNEL_PKGS = ("linux", "linux-lts", "linux-zen", "nvidia-open", "mesa", "systemd")


def emit(kind, text="", **extra):
    print(json.dumps({"type": kind, "text": text, **extra}), flush=True)


def stream(cmd, on_line):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env={**os.environ, "LC_ALL": "C"})
    buf = b""
    while True:
        chunk = proc.stdout.read1(4096)
        if not chunk:
            break
        buf += chunk
        *lines, buf = re.split(rb"[\r\n]", buf)
        for raw in lines:
            line = raw.decode(errors="replace").strip()
            if line:
                on_line(line)
    return proc.wait()


def clear_stale_lock():
    lock = "/var/lib/pacman/db.lck"
    if os.path.exists(lock):
        running = subprocess.run(["pgrep", "-x", "pacman"], capture_output=True).returncode == 0
        if running:
            raise RuntimeError("Another update or installation is already running. "
                               "Please try again in a few minutes.")
        os.remove(lock)


def main():
    if os.geteuid() != 0:
        emit("error", "The update helper must run as root.")
        sys.exit(1)
    state = {"restart": False, "changed": False, "total": 0}
    try:
        clear_stale_lock()
        emit("step", "Checking for updates…", progress=0.02)
        stream(["pacman", "-Sy", "--needed", "--noconfirm", "archlinux-keyring"],
               lambda l: None)

        def on_pacman(line):
            m = re.match(r"^Packages \((\d+)\)", line)
            if m:
                state["total"] = int(m.group(1))
                state["changed"] = True
                emit("step", f"Downloading {state['total']} updates…", progress=0.10)
                return
            m = re.search(r"\(\s*(\d+)/(\d+)\) (upgrading|installing|reinstalling) (\S+)", line)
            if m:
                done, total, pkg = int(m.group(1)), int(m.group(2)), m.group(4)
                if pkg.rstrip(".") in KERNEL_PKGS:
                    state["restart"] = True
                emit("step", "Installing updates…", detail=pkg.rstrip("."),
                     progress=0.45 + 0.40 * done / total)
                return
            if re.search(r"^\s*(upgrading|installing) (\S+)", line):
                pkg = line.split()[1].rstrip(".")
                if pkg in KERNEL_PKGS:
                    state["restart"] = True
                emit("step", "Installing updates…", detail=pkg)
                return
            if "downloading" in line or line.endswith(".pkg.tar.zst"):
                emit("step", "Downloading updates…", detail=line.split()[0])

        rc = stream(["pacman", "-Su", "--noconfirm"], on_pacman)
        if rc != 0:
            raise RuntimeError("System packages could not be updated. Check your internet "
                               "connection and try again.")

        emit("step", "Updating apps…", progress=0.88)

        def on_flatpak(line):
            if re.match(r"^\s*\d+\.\s", line) or "Updating" in line:
                state["changed"] = True
                emit("step", "Updating apps…", detail=line.split("\t")[0][:60])

        stream(["flatpak", "update", "--system", "-y", "--noninteractive"], on_flatpak)
        stream(["flatpak", "uninstall", "--system", "--unused", "-y", "--noninteractive"],
               lambda l: None)
        emit("step", "Cleaning up…", progress=0.97)
        stream(["paccache", "-rk2"], lambda l: None)
        emit("done", restart=state["restart"], changed=state["changed"])
    except Exception as e:  # noqa: BLE001 - shown to the user
        emit("error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
