# Shale Linux

A calm, ready-to-use desktop built on Arch Linux, made for people who are new to Linux.

Boot the USB stick, click through a short installer and you get a complete desktop. You never need a terminal.

## What you get

| | |
|---|---|
| **Desktop** | KDE Plasma 6 (Wayland) with the Shale Dark theme (#1e1e1e) and Shale wallpaper on the desktop, lock screen and login screen |
| **Panel** | Solid (non-floating) bottom panel with Bazaar, Firefox, Files and LibreOffice pinned |
| **Graphics** | AMD by default (Mesa + RADV Vulkan, 32-bit libraries for games). Intel and NVIDIA are detected and offered automatically. |
| **Audio** | PipeWire (with PulseAudio, ALSA and JACK compatibility) |
| **Bluetooth** | Enabled and switched on automatically |
| **Apps** | Flatpak + Flathub out of the box, plus **[Bazaar](https://github.com/kolunmi/bazaar)** (app store), **LibreOffice**, **VLC**, **Gwenview** and **Firefox** |
| **Updates** | **Software Update** updates the system and all apps with one click and a progress bar. Admin users don't need a password. |
| **Boot** | Silent: no boot menu, no scrolling text, no Arch logo. Just the computer maker's logo and a spinner. |
| **Extras** | zram swap, printing, firmware updates (fwupd), optional full-disk encryption |

Under the hood it's plain Arch Linux, using the official Arch repositories. The Arch Wiki applies to everything.

## Installing

1. Download the latest ISO from [Releases](../../releases) (or the newest build under [Actions](../../actions)).
2. Write it to a USB stick (8 GB or larger) with [Fedora Media Writer](https://flathub.org/apps/org.fedoraproject.MediaWriter) or [balenaEtcher](https://etcher.balena.io/).
3. Boot from the USB stick. Shale starts straight into the live desktop and opens the installer.
4. Pick **Install Shale**, then follow the steps: keyboard → Wi-Fi → disk → location → your account.

> ⚠ The installer uses the **whole disk** you choose and erases everything on it.

Bazaar and Firefox are copied from the USB stick. Everything else is downloaded fresh while installing, so an internet connection is required.

## How it's put together

```
build.sh                      builds the ISO
src/shale/                    Shale's own apps (Python + Qt)
  installer.py                the installer you see
  install_backend.py          does the installing (runs as root via pkexec)
  updater.py, update_helper.py  Software Update and its root helper
  theme.py                    shared look for both apps
  data.py                     package lists and defaults
system/                       files for the live USB *and* every installed system:
                              theme, wallpaper, panel layout, boot splash, updater
iso/                          archiso profile (based on Arch's releng); live-only bits
tools/                        scripts that generated the color scheme, wallpaper and boot logo
```

The installer backend reads the user's choices as JSON on stdin and reports progress as JSON lines. It:

- partitions the disk (GPT, ext4, optional LUKS2)
- runs `pacstrap`
- sets up locale, keyboard, user, SDDM and Plymouth
- installs a hidden-menu bootloader: systemd-boot on UEFI, GRUB on BIOS
- copies the `system/` files and the Flatpaks from the USB stick

`shale-firstboot.service` reinstalls any missing Flatpaks once the new system is online.

## Building the ISO

On Arch Linux:

```sh
sudo pacman -S archiso flatpak
sudo ./build.sh
```

The ISO appears in `out/`. On any other distro, use a privileged Arch container:

```sh
sudo podman run --rm --privileged -v "$PWD":/work -w /work archlinux:latest \
    bash -c 'pacman -Syu --noconfirm archiso flatpak python && ./build.sh'
```

GitHub Actions builds the ISO on every push to `main`. Pushing a tag like `v2026.10` publishes a release. The ISO is larger than GitHub's 2 GiB limit, so the release splits it into parts; instructions for joining them are in the release notes.

## License

GPL-3.0-or-later. The archiso profile is derived from [archiso](https://gitlab.archlinux.org/archlinux/archiso) (GPL-3.0).
Shale Linux is not affiliated with or endorsed by Arch Linux.
