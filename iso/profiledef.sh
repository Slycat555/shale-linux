#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="shalelinux"
iso_label="SHALE_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="Shale Linux"
iso_application="Shale Linux Live/Install"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86,arm64' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.gnupg"]="0:0:700"
  ["/etc/sudoers.d/10-live"]="0:0:440"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/livecd-sound"]="0:0:755"
  ["/usr/local/bin/shale-live-setup"]="0:0:755"
  ["/usr/bin/shale-installer"]="0:0:755"
  ["/usr/bin/shale-update"]="0:0:755"
  ["/usr/lib/shale/shale-install-backend"]="0:0:755"
  ["/usr/lib/shale/shale-update-helper"]="0:0:755"
  ["/usr/lib/shale/shale-firstboot"]="0:0:755"
  ["/usr/lib/shale/shale-user-setup"]="0:0:755"
  ["/usr/lib/shale/shale-login-wallpaper"]="0:0:755"
  ["/usr/lib/shale/shale-match-theme"]="0:0:755"
  ["/usr/lib/shale/shale-theme-watcher"]="0:0:755"
  ["/usr/bin/timeshift"]="0:0:755"
  ["/usr/bin/timeshift-gtk"]="0:0:755"
  ["/usr/bin/timeshift-launcher"]="0:0:755"
)
