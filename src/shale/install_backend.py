"""Shale Linux install backend.

Runs as root. Reads a JSON config on stdin and prints JSON-lines progress
messages on stdout:

    {"type": "step", "text": "...", "progress": 0.42}
    {"type": "log", "text": "..."}
    {"type": "error", "text": "..."}
    {"type": "done"}

Usage: shale-install-backend < config.json
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from . import data

TARGET = "/mnt/shale-target"
LOG_PATH = "/tmp/shale-install.log"
OVERLAY_MANIFEST = "/usr/share/shale/overlay-files"

REQUIRED_KEYS = ["disk", "locale", "timezone", "keyboard", "gpu", "cpu",
                 "fullname", "username", "password", "hostname"]


class InstallError(Exception):
    pass


class Installer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.uefi = cfg.get("force_uefi", os.path.isdir("/sys/firmware/efi"))
        self.logfile = open(LOG_PATH, "a", encoding="utf-8")
        self.root_dev = None
        self.luks_uuid = None

    # ---- output helpers -------------------------------------------------

    def emit(self, kind, text="", progress=None):
        msg = {"type": kind, "text": text}
        if progress is not None:
            msg["progress"] = round(progress, 4)
        print(json.dumps(msg), flush=True)
        if text:
            self.logfile.write(f"[{kind}] {text}\n")
            self.logfile.flush()

    def step(self, text, progress):
        self.emit("step", text, progress)

    def log(self, text):
        self.emit("log", text)

    def run(self, cmd, input=None, check=True, on_line=None, quiet=False):
        """Run a command, streaming its output to the log."""
        if not quiet:
            self.log("$ " + " ".join(cmd))
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={**os.environ, "LC_ALL": "C"})
        if input is not None:
            proc.stdin.write(input.encode())
            proc.stdin.close()
        out = []
        buf = b""
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode(errors="replace").rstrip()
                if not line:
                    continue
                out.append(line)
                if not quiet:
                    self.log(line)
                if on_line:
                    on_line(line)
        if buf.strip():
            line = buf.decode(errors="replace").rstrip()
            out.append(line)
            if not quiet:
                self.log(line)
        rc = proc.wait()
        if check and rc != 0:
            raise InstallError(f"Command failed ({rc}): {' '.join(cmd)}")
        return "\n".join(out)

    def chroot(self, cmd, **kw):
        return self.run(["arch-chroot", TARGET] + cmd, **kw)

    def write(self, path, content, mode=0o644):
        full = TARGET + path
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(full, mode)

    # ---- install steps --------------------------------------------------

    def install(self):
        self.validate()
        self.step("Preparing the disk", 0.02)
        self.partition()
        self.step("Setting up the internet mirrors", 0.08)
        self.prepare_pacman()
        self.step("Downloading packages", 0.10)
        self.pacstrap()
        self.step("Configuring your system", 0.78)
        self.configure_base()
        self.create_user()
        self.configure_desktop()
        self.step("Setting up startup", 0.84)
        self.configure_boot()
        self.step("Enabling services", 0.90)
        self.enable_services()
        self.step("Adding your apps", 0.92)
        self.install_flatpaks()
        self.step("Finishing up", 0.98)
        self.finish()
        self.step("Done", 1.0)
        self.emit("done")

    def validate(self):
        missing = [k for k in REQUIRED_KEYS if not self.cfg.get(k)]
        if missing:
            raise InstallError("Missing settings: " + ", ".join(missing))
        if os.geteuid() != 0:
            raise InstallError("The installer backend must run as root.")
        disk = self.cfg["disk"]
        if not disk.startswith("/dev/") or not os.path.exists(disk):
            raise InstallError(f"Disk {disk} does not exist.")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.cfg["username"]):
            raise InstallError("Invalid username.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", self.cfg["hostname"]):
            raise InstallError("Invalid computer name.")
        # Never touch the disk the live system runs from.
        mounts = self.run(["lsblk", "-nrpo", "MOUNTPOINTS", disk], quiet=True)
        for mp in mounts.split():
            if mp == "/" or mp.startswith("/run/archiso"):
                raise InstallError(f"{disk} holds the running live system.")
        self.log(f"Boot mode: {'UEFI' if self.uefi else 'BIOS'}")

    def part(self, n):
        disk = self.cfg["disk"]
        sep = "p" if disk[-1].isdigit() else ""
        return f"{disk}{sep}{n}"

    def partition(self):
        disk = self.cfg["disk"]
        # Release anything still using the disk (e.g. a previous attempt).
        if os.path.ismount(TARGET):
            self.run(["umount", "-R", TARGET], check=False)
        if os.path.exists("/dev/mapper/cryptroot"):
            self.run(["cryptsetup", "close", "cryptroot"], check=False)
        self.run(["swapoff", "-a"], check=False)
        for p in self.run(["lsblk", "-nrpo", "NAME", disk], quiet=True).split()[1:]:
            self.run(["umount", p], check=False, quiet=True)

        self.run(["wipefs", "-af", disk])
        self.run(["sgdisk", "--zap-all", disk])
        if self.uefi:
            self.run(["sgdisk", "-n", "1:0:+1G", "-t", "1:ef00", "-c", "1:EFI",
                      "-n", "2:0:0", "-t", "2:8304", "-c", f"2:{data.DISTRO_NAME}",
                      disk])
            boot, root = self.part(1), self.part(2)
        else:
            self.run(["sgdisk", "-n", "1:0:+1M", "-t", "1:ef02", "-c", "1:BIOS",
                      "-n", "2:0:+1G", "-t", "2:8300", "-c", "2:boot",
                      "-n", "3:0:0", "-t", "3:8304", "-c", f"3:{data.DISTRO_NAME}",
                      disk])
            boot, root = self.part(2), self.part(3)
        self.run(["partprobe", disk], check=False)
        self.run(["udevadm", "settle"], check=False)
        for p in (boot, root):
            for _ in range(20):
                if os.path.exists(p):
                    break
                time.sleep(0.5)
            self.run(["wipefs", "-af", p])

        self.root_dev = root
        if self.cfg.get("encrypt"):
            self.step("Encrypting the disk", 0.04)
            pw = self.cfg["encrypt_password"]
            self.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode",
                      "--key-file=-", root], input=pw)
            self.run(["cryptsetup", "open", "--key-file=-", root, "cryptroot"], input=pw)
            self.luks_uuid = self.run(["blkid", "-s", "UUID", "-o", "value", root],
                                      quiet=True).strip()
            self.root_dev = "/dev/mapper/cryptroot"

        self.run(["mkfs.ext4", "-F", "-L", "shale", self.root_dev])
        if self.uefi:
            self.run(["mkfs.fat", "-F", "32", "-n", "EFI", boot])
        else:
            self.run(["mkfs.ext4", "-F", "-L", "boot", boot])

        os.makedirs(TARGET, exist_ok=True)
        self.run(["mount", self.root_dev, TARGET])
        os.makedirs(TARGET + "/boot", exist_ok=True)
        if self.uefi:
            self.run(["mount", "-o", "fmask=0077,dmask=0077", boot, TARGET + "/boot"])
        else:
            self.run(["mount", boot, TARGET + "/boot"])

    def prepare_pacman(self):
        self.run(["reflector", "--protocol", "https", "--age", "24", "--latest", "20",
                  "--sort", "score", "--save", "/etc/pacman.d/mirrorlist"], check=False)
        # pacman.conf for the install, with multilib (32-bit) enabled for games/Steam.
        with open("/etc/pacman.conf", encoding="utf-8") as f:
            conf = f.read()
        if not re.search(r"^\[multilib\]", conf, re.M):
            conf = re.sub(r"^#\[multilib\]\n#Include", "[multilib]\nInclude", conf, flags=re.M)
        if not re.search(r"^\[multilib\]", conf, re.M):
            conf += "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n"
        fd, self.pacman_conf = tempfile.mkstemp(prefix="shale-pacman-", suffix=".conf")
        with os.fdopen(fd, "w") as f:
            f.write(conf)
        # An older ISO may not know the newest signing keys.
        self.run(["pacman", "--config", self.pacman_conf, "-Sy", "--noconfirm",
                  "--needed", "archlinux-keyring"], check=False)

    def package_list(self):
        pkgs = list(data.BASE_PACKAGES) + list(data.KDE_PACKAGES) + list(data.APP_PACKAGES)
        pkgs += self.libreoffice_langpack()
        pkgs += data.GPU_PACKAGES.get(self.cfg["gpu"], data.GPU_PACKAGES["amd"])
        ucode = data.CPU_UCODE.get(self.cfg["cpu"])
        if ucode:
            pkgs.append(ucode)
        pkgs += ["efibootmgr"] if self.uefi else ["grub"]
        pkgs += self.cfg.get("extra_packages", [])
        return list(dict.fromkeys(pkgs))

    def libreoffice_langpack(self):
        """LibreOffice in the user's language, e.g. libreoffice-fresh-de."""
        loc = self.cfg["locale"].split(".")[0]          # de_DE
        lang = loc.split("_")[0]
        for cand in (loc.replace("_", "-").lower(), lang):  # pt-br, then pt
            if cand in ("en-us", "en"):
                return []
            pkg = f"libreoffice-fresh-{cand}"
            if subprocess.run(["pacman", "--config", self.pacman_conf, "-Si", pkg],
                              capture_output=True).returncode == 0:
                return [pkg]
        return []

    def pacstrap(self):
        pkgs = self.package_list()
        state = {"total": len(pkgs) * 3, "dl": 0, "inst": 0}

        def on_line(line):
            m = re.search(r"^Packages \((\d+)\)", line)
            if m:
                state["total"] = int(m.group(1))
                return
            total = max(state["total"], 1)
            m = re.search(r"\(\s*(\d+)/(\d+)\) installing (\S+)", line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                self.step(f"Installing {m.group(3)}", 0.45 + 0.32 * done / total)
                return
            if re.search(r"^\s*installing \S+", line):
                state["inst"] += 1
                self.step("Installing " + line.split()[1].rstrip("."),
                          0.45 + 0.32 * min(state["inst"] / total, 1))
                return
            if re.search(r"(downloading|\.pkg\.tar\.zst)", line) and "sig" not in line:
                state["dl"] += 1
                self.step("Downloading packages",
                          0.10 + 0.35 * min(state["dl"] / total, 1))

        self.run(["pacstrap", "-K", "-C", self.pacman_conf, TARGET] + pkgs,
                 on_line=on_line)

    def configure_base(self):
        c = self.cfg
        fstab = self.run(["genfstab", "-U", TARGET], quiet=True)
        with open(TARGET + "/etc/fstab", "a", encoding="utf-8") as f:
            f.write(fstab + "\n")

        # Enable multilib on the installed system too.
        with open(TARGET + "/etc/pacman.conf", encoding="utf-8") as f:
            conf = f.read()
        conf = re.sub(r"^#\[multilib\]\n#Include", "[multilib]\nInclude", conf, flags=re.M)
        conf = re.sub(r"^#Color$", "Color", conf, flags=re.M)
        self.write("/etc/pacman.conf", conf)
        shutil.copy("/etc/pacman.d/mirrorlist", TARGET + "/etc/pacman.d/mirrorlist")

        tz = c["timezone"]
        if not os.path.exists(f"{TARGET}/usr/share/zoneinfo/{tz}"):
            tz = "UTC"
        self.chroot(["ln", "-sf", f"/usr/share/zoneinfo/{tz}", "/etc/localtime"])
        self.chroot(["hwclock", "--systohc"], check=False)

        locales = dict.fromkeys([c["locale"], "en_US.UTF-8"])
        with open(TARGET + "/etc/locale.gen", encoding="utf-8") as f:
            gen = f.read()
        for loc in locales:
            gen = re.sub(rf"^#\s*{re.escape(loc)} UTF-8", f"{loc} UTF-8", gen, flags=re.M)
        self.write("/etc/locale.gen", gen)
        self.chroot(["locale-gen"])
        self.write("/etc/locale.conf", f"LANG={c['locale']}\n")

        kb = c["keyboard"]
        self.write("/etc/vconsole.conf", f"KEYMAP={kb['keymap']}\n")
        variant = f'    Option "XkbVariant" "{kb["variant"]}"\n' if kb.get("variant") else ""
        self.write("/etc/X11/xorg.conf.d/00-keyboard.conf",
                   'Section "InputClass"\n'
                   '    Identifier "system-keyboard"\n'
                   '    MatchIsKeyboard "on"\n'
                   f'    Option "XkbLayout" "{kb["layout"]}"\n'
                   f"{variant}"
                   "EndSection\n")
        kxkb = ("[Layout]\nUse=true\n"
                f"LayoutList={kb['layout']}\nVariantList={kb.get('variant', '')}\n")
        self.write("/etc/skel/.config/kxkbrc", kxkb)

        host = c["hostname"]
        self.write("/etc/hostname", host + "\n")
        self.write("/etc/hosts", "127.0.0.1 localhost\n::1 localhost\n"
                                 f"127.0.1.1 {host}.localdomain {host}\n")

        self.write("/etc/systemd/zram-generator.conf",
                   "[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\n")
        self.write("/etc/sudoers.d/10-wheel", "%wheel ALL=(ALL:ALL) ALL\n", 0o440)
        self.write("/etc/shale-release",
                   f'NAME="{data.DISTRO_NAME}"\nINSTALL_DATE="{time.strftime("%Y-%m-%d")}"\n')

    def create_user(self):
        c = self.cfg
        user = c["username"]
        self.chroot(["useradd", "-m", "-G", "wheel", "-s", "/bin/bash",
                     "-c", c["fullname"], user])
        self.chroot(["chpasswd"], input=f"{user}:{c['password']}\n", quiet=True)
        self.chroot(["passwd", "-l", "root"])

    def configure_desktop(self):
        c = self.cfg
        sddm = ("[General]\nDisplayServer=wayland\n"
                "GreeterEnvironment=QT_WAYLAND_SHELL_INTEGRATION=layer-shell\n\n"
                "[Wayland]\nCompositorCommand=kwin_wayland --drm --no-lockscreen "
                "--no-global-shortcuts --locale1\n\n"
                "[Theme]\nCurrent=breeze\nCursorTheme=Breeze_Light\n")
        if c.get("autologin"):
            sddm += f"\n[Autologin]\nUser={c['username']}\nSession=plasma\n"
        self.write("/etc/sddm.conf.d/10-shale.conf", sddm)
        self.write("/etc/plymouth/plymouthd.conf", "[Daemon]\nTheme=shale\n")

        # Bluetooth adapters switch on automatically.
        bt = TARGET + "/etc/bluetooth/main.conf"
        if os.path.exists(bt):
            with open(bt, encoding="utf-8") as f:
                conf = f.read()
            self.write("/etc/bluetooth/main.conf",
                       re.sub(r"^#?AutoEnable=.*$", "AutoEnable=true", conf, flags=re.M))

        # Shale's own files (theme, wallpaper, panel layout, updater...) are listed in a
        # manifest on the live system; copy each one to the new system.
        with open(OVERLAY_MANIFEST, encoding="utf-8") as f:
            for path in filter(None, (l.strip() for l in f)):
                dest = TARGET + path
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(path, dest, follow_symlinks=False)
        # From now on the shale-os-release pacman hook keeps this in place.
        shutil.copy2("/usr/share/shale/os-release", TARGET + "/usr/lib/os-release")
        self.configure_snapshots()

    def configure_snapshots(self):
        """Shale Snapshots: daily and boot snapshots of the system (not /home) on the
        root disk, so a bad update can be rolled back."""
        with open("/etc/timeshift/default.json", encoding="utf-8") as f:
            conf = json.load(f)
        conf.update({
            "backup_device_uuid": self.run(["blkid", "-s", "UUID", "-o", "value", self.root_dev],
                                           quiet=True).strip(),
            "parent_device_uuid": self.luks_uuid or "",
            "do_first_run": "false",
            "schedule_daily": "true", "count_daily": "5",
            "schedule_boot": "true", "count_boot": "3",
        })
        self.write("/etc/timeshift/timeshift.json", json.dumps(conf, indent=2) + "\n")
        cron = ("SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin\n"
                'MAILTO=""\n\n')
        self.write("/etc/cron.d/timeshift-hourly", cron + "0 * * * * root timeshift --check --scripted\n")
        self.write("/etc/cron.d/timeshift-boot",
                   cron + "@reboot root sleep 10m && timeshift --create --scripted --tags B\n")

    def configure_boot(self):
        hooks = ["base", "systemd", "plymouth", "autodetect", "microcode", "modconf",
                 "kms", "keyboard", "sd-vconsole", "block"]
        if self.luks_uuid:
            hooks.append("sd-encrypt")
        hooks += ["filesystems", "fsck"]
        conf = f"HOOKS=({' '.join(hooks)})\n"
        if self.cfg["gpu"] == "nvidia":
            # NVIDIA must not be in the initramfs together with kms; drop kms.
            conf = conf.replace(" kms", "")
        self.write("/etc/mkinitcpio.conf.d/10-shale.conf", conf)
        self.chroot(["mkinitcpio", "-P"])

        root_uuid = self.run(["blkid", "-s", "UUID", "-o", "value", self.root_dev],
                             quiet=True).strip()
        root_opt = f"root=UUID={root_uuid}"
        if self.luks_uuid:
            root_opt = f"rd.luks.name={self.luks_uuid}=cryptroot root=/dev/mapper/cryptroot"
        extra = " nvidia_drm.modeset=1" if self.cfg["gpu"] == "nvidia" else ""
        opts = f"{root_opt} rw {data.QUIET_CMDLINE}{extra}"

        if self.uefi:
            cmd = ["bootctl", "install", "--esp-path=/boot"]
            if self.cfg.get("no_nvram"):
                cmd.append("--no-variables")
            self.chroot(cmd)
            self.write("/boot/loader/loader.conf",
                       "default shale.conf\ntimeout 0\nconsole-mode keep\neditor no\n"
                       "auto-entries no\nauto-firmware no\n")
            self.write("/boot/loader/entries/shale.conf",
                       f"title   {data.DISTRO_NAME}\nlinux   /vmlinuz-linux\n"
                       f"initrd  /initramfs-linux.img\noptions {opts}\n")
            if os.path.exists(TARGET + "/boot/initramfs-linux-fallback.img"):
                self.write("/boot/loader/entries/shale-fallback.conf",
                           f"title   {data.DISTRO_NAME} (safe mode)\nlinux   /vmlinuz-linux\n"
                           f"initrd  /initramfs-linux-fallback.img\noptions {opts}\n")
        else:
            with open(TARGET + "/etc/default/grub", encoding="utf-8") as f:
                grub = f.read()
            # grub-mkconfig adds root= itself; only the LUKS mapping is needed.
            cmdline = (f"rd.luks.name={self.luks_uuid}=cryptroot" if self.luks_uuid
                       else "") + extra
            settings = {
                "GRUB_CMDLINE_LINUX_DEFAULT": f'"{data.QUIET_CMDLINE}"',
                "GRUB_CMDLINE_LINUX": f'"{cmdline.strip()}"',
                "GRUB_DISTRIBUTOR": f'"{data.DISTRO_NAME}"',
                "GRUB_TIMEOUT": "0",
                "GRUB_TIMEOUT_STYLE": "hidden",
                "GRUB_RECORDFAIL_TIMEOUT": "0",
            }
            for key, val in settings.items():
                if re.search(rf"^#?{key}=", grub, flags=re.M):
                    grub = re.sub(rf"^#?{key}=.*$", f"{key}={val}", grub, flags=re.M)
                else:
                    grub += f"{key}={val}\n"
            self.write("/etc/default/grub", grub)
            self.chroot(["grub-install", "--target=i386-pc", self.cfg["disk"]])
            self.chroot(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])

    def enable_services(self):
        services = list(data.SERVICES)
        if self.uefi:
            services.append("systemd-boot-update.service")
        for svc in services:
            self.chroot(["systemctl", "enable", svc], check=False)

    def install_flatpaks(self):
        """Copy the Flatpaks bundled on the USB stick; download only as a fallback.

        shale-firstboot retries anything still missing once the new system is online.
        """
        if os.path.isdir("/var/lib/flatpak/repo"):
            self.run(["rsync", "-aHAX", "/var/lib/flatpak/", TARGET + "/var/lib/flatpak/"])
        self.chroot(["flatpak", "remote-add", "--system", "--if-not-exists",
                     "flathub", data.FLATHUB_REPO], check=False)
        for i, app in enumerate(data.FLATPAKS):
            if self._has_flatpak(app):
                continue
            self.step(f"Downloading {app.split('.')[-1]}",
                      0.92 + 0.05 * i / len(data.FLATPAKS))
            self.chroot(["flatpak", "install", "--system", "-y", "--noninteractive",
                         "flathub", app], check=False)

    def _has_flatpak(self, app):
        return os.path.isdir(f"{TARGET}/var/lib/flatpak/app/{app}")

    def finish(self):
        try:
            shutil.copy(LOG_PATH, TARGET + "/var/log/shale-install.log")
        except OSError:
            pass
        self.run(["sync"])
        self.run(["umount", "-R", TARGET], check=False)
        if self.luks_uuid:
            self.run(["cryptsetup", "close", "cryptroot"], check=False)


def main():
    cfg = json.load(sys.stdin)
    inst = Installer(cfg)
    try:
        inst.install()
    except Exception as e:  # noqa: BLE001 - report every failure to the GUI
        inst.emit("error", str(e))
        if os.path.ismount(TARGET):
            subprocess.run(["umount", "-R", TARGET], check=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
