#!/usr/bin/env bash
# Builds the Shale Linux ISO. Must run as root on Arch Linux (or in an Arch container
# started with --privileged) with `archiso` and `flatpak` installed.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

WORK=${WORK:-build/work}
OUT=${OUT:-out}
PROFILE=build/profile
A="$PROFILE/airootfs"

if [[ $EUID -ne 0 ]]; then
    echo "Please run as root: sudo ./build.sh" >&2
    exit 1
fi

rm -rf "$PROFILE" "$WORK"
mkdir -p build
cp -a iso "$PROFILE"

# 1. Files shared by the live system and every installed system.
cp -a system/. "$A/"
install -d "$A/usr/lib/shale/shale"
cp src/shale/*.py src/shale/logo.svg "$A/usr/lib/shale/shale/"
install -Dm644 src/shale/logo.svg "$A/usr/share/pixmaps/shale-logo.svg"

# The installer copies everything in this manifest to the new system.
# (The installer itself is left out; it is only needed on the USB stick.)
install -d "$A/usr/share/shale"
{
    (cd system && find . \( -type f -o -type l \) | sed 's|^\.||')
    for f in src/shale/*.py src/shale/logo.svg; do
        case "$(basename "$f")" in installer.py|install_backend.py) continue ;; esac
        echo "/usr/lib/shale/shale/$(basename "$f")"
    done
    echo /usr/share/pixmaps/shale-logo.svg
} | sort > "$A/usr/share/shale/overlay-files"

# 2. Live-only: start the installer when the live desktop appears.
install -Dm644 "$A/usr/share/applications/shale-installer.desktop" \
    "$A/etc/xdg/autostart/shale-installer.desktop"

# 3. Pre-install the default Flatpaks so they work offline, in the live session and
#    after installing (the installer copies /var/lib/flatpak).
#    mkarchiso copies airootfs with `cp --no-preserve=mode`, which would strip the
#    executable bits from every runtime (bwrap then fails with "execvp ldconfig:
#    Permission denied"). So they are installed outside airootfs and shipped as a tar,
#    which the 00-shale-flatpak.hook pacman hook unpacks inside the pacstrap chroot.
mapfile -t FLATPAKS < <(python3 -c 'import sys; sys.path.insert(0, "src"); from shale import data; print("\n".join(data.FLATPAKS))')
FLATPAK_STAGE=build/flatpak
rm -rf "$FLATPAK_STAGE"
export FLATPAK_SYSTEM_DIR="$PWD/$FLATPAK_STAGE"
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --system -y --noninteractive flathub "${FLATPAKS[@]}"
unset FLATPAK_SYSTEM_DIR
install -d "$A/var/lib/shale"
tar -cf "$A/var/lib/shale/flatpak.tar" --numeric-owner -C "$FLATPAK_STAGE" .

mkarchiso -v -r -w "$WORK" -o "$OUT" "$PROFILE"
echo
echo "Done: $(ls -1t "$OUT"/*.iso | head -n1)"
