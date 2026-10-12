"""Static data shared by the installer frontend and backend."""

DISTRO_NAME = "Shale Linux"
DISTRO_ID = "shale"

FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Flatpaks from Flathub. They are pre-installed on the ISO (see build.sh) and copied
# to the new system, so they work without an internet connection.
FLATPAKS = [
    "io.github.kolunmi.Bazaar",  # app store
    "org.localsend.localsend_app",  # send files to nearby phones and computers
]

# Kernel options for a quiet, logo-free boot straight into the desktop.
QUIET_CMDLINE = ("quiet splash loglevel=3 rd.udev.log_level=3 systemd.show_status=auto "
                 "vt.global_cursor_default=0")

BASE_PACKAGES = [
    "base", "linux", "linux-firmware", "sof-firmware",
    "sudo", "nano", "man-db", "bash-completion", "less",
    "networkmanager", "plymouth", "zram-generator",
    "e2fsprogs", "dosfstools", "exfatprogs", "ntfs-3g", "cryptsetup",
    "pacman-contrib", "reflector", "fwupd", "power-profiles-daemon",
    "xdg-user-dirs", "fastfetch", "7zip", "unzip", "zip", "curl", "rsync",
    # Shale's own tools (updater) are written in Python + Qt
    "python", "pyside6", "qt6-svg",
    # Audio
    "pipewire", "pipewire-alsa", "pipewire-pulse", "pipewire-jack", "wireplumber",
    # Bluetooth & printing
    "bluez", "bluez-utils", "cups",
    # Flatpak
    "flatpak",
    # Shale Snapshots (Timeshift fork) and its scheduler
    "cronie", "vte3", "libgee", "json-glib", "psmisc",
    # Fonts
    "noto-fonts", "noto-fonts-emoji", "ttf-ibm-plex", "noto-fonts-cjk", "ttf-liberation",
]

KDE_PACKAGES = [
    "plasma-desktop", "plasma-nm", "plasma-pa", "powerdevil", "bluedevil",
    "kscreen", "kde-gtk-config", "breeze-gtk", "sddm", "sddm-kcm",
    "systemsettings", "kinfocenter", "plasma-systemmonitor", "plasma-disks",
    "kdeplasma-addons", "print-manager", "flatpak-kcm", "kwallet-pam",
    "xdg-desktop-portal-kde", "xdg-desktop-portal-gtk",
    "dolphin", "konsole", "kio-extras", "kio-admin", "kate", "ark", "gwenview",
    "okular", "spectacle", "kalk", "partitionmanager", "filelight",
    "ffmpegthumbs", "kdegraphics-thumbnailers",
]

# Everyday apps (also on the live USB).
APP_PACKAGES = ["chromium", "vlc", "vlc-plugins-all", "libreoffice-fresh"]

GPU_PACKAGES = {
    "amd": ["mesa", "lib32-mesa", "vulkan-radeon", "lib32-vulkan-radeon"],
    "intel": ["mesa", "lib32-mesa", "vulkan-intel", "lib32-vulkan-intel",
              "intel-media-driver"],
    "nvidia": ["nvidia-open", "nvidia-utils", "lib32-nvidia-utils",
               "nvidia-settings"],
    "generic": ["mesa", "lib32-mesa"],
}

GPU_LABELS = {
    "amd": "AMD Radeon (recommended)",
    "intel": "Intel graphics",
    "nvidia": "NVIDIA GeForce (proprietary driver)",
    "generic": "Other / virtual machine",
}

CPU_UCODE = {"amd": "amd-ucode", "intel": "intel-ucode"}

SERVICES = [
    "NetworkManager.service", "sddm.service", "bluetooth.service",
    "cups.socket", "fstrim.timer", "paccache.timer",
    "systemd-timesyncd.service", "power-profiles-daemon.service",
    "shale-firstboot.service", "cronie.service",
]

# (label, locale)
LANGUAGES = [
    ("English (United States)", "en_US.UTF-8"),
    ("English (United Kingdom)", "en_GB.UTF-8"),
    ("English (Canada)", "en_CA.UTF-8"),
    ("English (Australia)", "en_AU.UTF-8"),
    ("Deutsch", "de_DE.UTF-8"),
    ("Français", "fr_FR.UTF-8"),
    ("Français (Canada)", "fr_CA.UTF-8"),
    ("Español (España)", "es_ES.UTF-8"),
    ("Español (México)", "es_MX.UTF-8"),
    ("Italiano", "it_IT.UTF-8"),
    ("Português (Brasil)", "pt_BR.UTF-8"),
    ("Português (Portugal)", "pt_PT.UTF-8"),
    ("Nederlands", "nl_NL.UTF-8"),
    ("Polski", "pl_PL.UTF-8"),
    ("Svenska", "sv_SE.UTF-8"),
    ("Norsk bokmål", "nb_NO.UTF-8"),
    ("Dansk", "da_DK.UTF-8"),
    ("Suomi", "fi_FI.UTF-8"),
    ("Čeština", "cs_CZ.UTF-8"),
    ("Magyar", "hu_HU.UTF-8"),
    ("Türkçe", "tr_TR.UTF-8"),
    ("Русский", "ru_RU.UTF-8"),
    ("Українська", "uk_UA.UTF-8"),
    ("Ελληνικά", "el_GR.UTF-8"),
    ("日本語", "ja_JP.UTF-8"),
    ("한국어", "ko_KR.UTF-8"),
    ("中文 (简体)", "zh_CN.UTF-8"),
    ("中文 (繁體)", "zh_TW.UTF-8"),
]

# (label, xkb layout, xkb variant, console keymap)
KEYBOARDS = [
    ("English (US)", "us", "", "us"),
    ("English (US, international with dead keys)", "us", "intl", "us-acentos"),
    ("English (UK)", "gb", "", "uk"),
    ("German", "de", "", "de-latin1"),
    ("Swiss German", "ch", "", "de_CH-latin1"),
    ("French", "fr", "", "fr-latin1"),
    ("French (Canada)", "ca", "", "cf"),
    ("Belgian", "be", "", "be-latin1"),
    ("Spanish", "es", "", "es"),
    ("Spanish (Latin American)", "latam", "", "la-latin1"),
    ("Italian", "it", "", "it"),
    ("Portuguese", "pt", "", "pt-latin1"),
    ("Portuguese (Brazil)", "br", "", "br-abnt2"),
    ("Dutch", "nl", "", "nl"),
    ("Polish", "pl", "", "pl2"),
    ("Swedish", "se", "", "sv-latin1"),
    ("Norwegian", "no", "", "no-latin1"),
    ("Danish", "dk", "", "dk-latin1"),
    ("Finnish", "fi", "", "fi"),
    ("Czech", "cz", "", "cz-qwertz"),
    ("Hungarian", "hu", "", "hu"),
    ("Turkish", "tr", "", "trq"),
    ("Russian", "ru", "", "ru"),
    ("Ukrainian", "ua", "", "ua"),
    ("Greek", "gr", "", "gr"),
    ("Japanese", "jp", "", "jp106"),
    ("Korean", "kr", "", "us"),
]
