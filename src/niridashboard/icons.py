"""Resolve installed desktop application logos, including Flatpak exports."""
import configparser
import os
from pathlib import Path
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


class Icons:
    def __init__(self):
        self.entries = {}
        self.cache = {}
        seen = set()
        roots = [Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))]
        roots += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")]
        roots += [Path.home() / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share")]
        QIcon.setThemeSearchPaths(QIcon.themeSearchPaths() + [str(p / "icons") for p in roots])
        if not QIcon.themeName():
            QIcon.setThemeName("Adwaita")
        QIcon.setFallbackThemeName("hicolor")
        for root in roots:
            for file in sorted((root / "applications").glob("**/*.desktop")):
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(file, encoding="utf-8")
                    entry = parser["Desktop Entry"]
                    desktop_id = str(file.relative_to(root / "applications")).replace("/", "-")[:-8]
                    if desktop_id in seen:
                        continue
                    seen.add(desktop_id)
                    if entry.get("Hidden", "false").lower() == "true":
                        continue
                    icon = entry.get("Icon", "")
                    label = entry.get("Name", file.stem)
                    for key in (desktop_id, file.stem, entry.get("StartupWMClass", "")):
                        if key:
                            self.entries.setdefault(key.lower(), (label, icon))
                except (OSError, UnicodeError, configparser.Error, KeyError):
                    continue

    def resolve(self, app_id):
        app_id = app_id or "Unknown application"
        if app_id in self.cache:
            return self.cache[app_id]
        label, name = self.entries.get(app_id.lower(), (app_id.rsplit(".", 1)[-1], app_id))
        icon = QIcon(name) if Path(name).is_absolute() else QIcon.fromTheme(name)
        if icon.isNull():
            icon = QIcon.fromTheme(app_id.lower())
        if icon.isNull():
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor("#32445d"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(2, 2, 60, 60), 16, 16)
            painter.setPen(QColor("#d6e5fc"))
            painter.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, label[:2].upper())
            painter.end()
            icon = QIcon(pixmap)
        self.cache[app_id] = label, icon
        return label, icon
