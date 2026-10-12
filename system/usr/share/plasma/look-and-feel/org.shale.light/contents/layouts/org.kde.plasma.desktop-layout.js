// Shale Linux default desktop: Shale wallpaper and a solid (non-floating) bottom
// panel with Bazaar, Chromium, Files, Calculator and LibreOffice Writer pinned.

var desktopsArray = desktopsForActivity(currentActivity());
for (var j = 0; j < desktopsArray.length; j++) {
    var d = desktopsArray[j];
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", "file:///usr/share/wallpapers/Shale/");
}

var panel = new Panel;
var panelScreen = panel.screen;
panel.location = "bottom";
panel.floating = false;
panel.height = 2 * Math.ceil(gridUnit * 2.5 / 2);

var kickoff = panel.addWidget("org.kde.plasma.kickoff");
kickoff.currentConfigGroup = ["General"];
kickoff.writeConfig("icon", "/usr/share/pixmaps/shale-logo.svg");
kickoff.writeConfig("favorites", [
    "preferred://browser",
    "org.kde.dolphin.desktop",
    "org.kde.konsole.desktop",
    "org.kde.kalk.desktop",
    "io.github.kolunmi.Bazaar.desktop",
    "org.localsend.localsend_app.desktop",
    "libreoffice-writer.desktop",
    "systemsettings.desktop",
    "shale-update.desktop",
    "timeshift-gtk.desktop"
].join(","));
panel.addWidget("org.kde.plasma.pager");

var tasks = panel.addWidget("org.kde.plasma.icontasks");
tasks.currentConfigGroup = ["General"];
tasks.writeConfig("launchers", [
    "applications:io.github.kolunmi.Bazaar.desktop",
    "applications:chromium.desktop",
    "applications:org.kde.dolphin.desktop",
    "applications:org.kde.kalk.desktop",
    "applications:libreoffice-writer.desktop"
].join(","));

panel.addWidget("org.kde.plasma.marginsseparator");

var langIds = ["as", "bn", "bo", "brx", "doi", "gu", "hi", "ja", "kn", "ko", "kok", "ks",
               "lep", "mai", "ml", "mni", "mr", "ne", "or", "pa", "sa", "sat", "sd", "si",
               "ta", "te", "th", "ur", "vi", "zh_CN", "zh_TW"];
if (langIds.indexOf(languageId) != -1) {
    panel.addWidget("org.kde.plasma.kimpanel");
}

panel.addWidget("org.kde.plasma.systemtray");
panel.addWidget("org.kde.plasma.digitalclock");
panel.addWidget("org.kde.plasma.showdesktop");
