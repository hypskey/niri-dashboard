"""Resolve installed desktop application logos, including Flatpak exports."""
import configparser
import os
from pathlib import Path
import re
from .browser_bridge import site_for_hostname
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QImageReader, QPainter, QPixmap

_THEME_DIRECTORY_CACHE = None
_ICON_ASSET_CACHE = {}

SITE_ICON_NAMES = {
    "chatgpt": ("chatgpt", "openai"),
    "youtube": ("youtube",),
    "google_calendar": ("google-calendar", "google_calendar"),
    "gmail": ("gmail", "google-mail", "mail-google"),
    "github": ("github",),
    "reddit": ("reddit", "reddit-alien"),
}
BROWSER_MARKERS = ("firefox", "chrome", "chromium", "zen", "brave", "edge", "vivaldi",
                   "opera", "librewolf", "floorp", "waterfox", "browser")


def site_for_title(title):
    """Return a known website key based on its browser tab title, if any."""
    value = (title or "").casefold()
    if re.search(r"\bchatgpt\b", value):
        return "chatgpt"
    if re.search(r"\byoutube\b", value):
        return "youtube"
    if (re.search(r"\bgoogle\s+calendar\b", value) or value.strip() == "calendar"
            or re.match(r"^calendar\s*[-–—|]", value.strip())):
        return "google_calendar"
    for site in ("gmail", "github", "reddit"):
        if re.search(rf"\b{site}\b", value):
            return site
    return None


def is_browser_app(app_id):
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", (app_id or "").casefold())))
    return any(marker in tokens for marker in BROWSER_MARKERS)


class Icons:
    def __init__(self, appearance=None):
        self.appearance = appearance
        self.entries = {}
        self.cache = {}
        self.pixmaps = {}
        self.site_icons = {}
        self.fallback_apps = set()
        self.theme_directories = None
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

    def _theme_icon_path(self, name, target_pixels):
        """Prefer vector assets, then the sharpest available theme raster."""
        if not name:
            return None
        if Path(name).is_absolute() and Path(name).is_file():
            return name
        if Path(name).suffix.lower() in (".svg", ".svgz", ".png", ".webp", ".xpm"):
            name = Path(name).stem
        cache_key = (name, target_pixels, QIcon.themeName())
        if cache_key in _ICON_ASSET_CACHE:
            return _ICON_ASSET_CACHE[cache_key]
        if self.theme_directories is None:
            self.theme_directories = self._load_theme_directories()
        vectors, rasters = [], []
        for directory in self.theme_directories:
            for suffix in (".svg", ".svgz"):
                candidate = directory / (name + suffix)
                if candidate.is_file():
                    vectors.append(candidate)
            for suffix in (".png", ".webp", ".xpm"):
                candidate = directory / (name + suffix)
                if candidate.is_file():
                    size = QImageReader(str(candidate)).size()
                    pixels = min(size.width(), size.height()) if size.isValid() else 0
                    rasters.append((candidate, pixels))
        if vectors:
            _ICON_ASSET_CACHE[cache_key] = str(vectors[0])
            return _ICON_ASSET_CACHE[cache_key]
        if rasters:
            large_enough = [pair for pair in rasters if pair[1] >= target_pixels * 2]
            pool = large_enough or rasters
            chosen = min(pool, key=lambda pair: (abs(pair[1] - target_pixels * 2), -pair[1]))
            _ICON_ASSET_CACHE[cache_key] = str(chosen[0])
            return _ICON_ASSET_CACHE[cache_key]
        _ICON_ASSET_CACHE[cache_key] = None
        return None

    def _load_theme_directories(self):
        global _THEME_DIRECTORY_CACHE
        if _THEME_DIRECTORY_CACHE is not None:
            return _THEME_DIRECTORY_CACHE
        result = []
        visited = set()
        queue = [QIcon.themeName(), QIcon.fallbackThemeName() or "hicolor"]
        roots = [Path(root) for root in QIcon.themeSearchPaths()]
        while queue:
            theme = queue.pop(0)
            if not theme or theme in visited:
                continue
            visited.add(theme)
            for root in roots:
                theme_root = root / theme
                index = theme_root / "index.theme"
                try:
                    parser = configparser.ConfigParser(interpolation=None, strict=False)
                    parser.read(index, encoding="utf-8")
                    metadata = parser["Icon Theme"]
                    directories = [part.strip() for part in metadata.get("Directories", "").split(",")]
                    directories += [part.strip() for part in metadata.get("ScaledDirectories", "").split(",")]
                    result.extend(theme_root / part for part in directories if part)
                    inherits = [part.strip() for part in metadata.get("Inherits", "").split(",") if part.strip()]
                    queue.extend(inherits)
                except (OSError, UnicodeError, configparser.Error, KeyError):
                    continue
        _THEME_DIRECTORY_CACHE = tuple(directory for directory in result if directory.is_dir())
        return _THEME_DIRECTORY_CACHE

    def refresh_theme(self):
        self.pixmaps.clear()
        self.site_icons.clear()
        for app_id in self.fallback_apps:
            self.cache.pop(app_id, None)
        self.fallback_apps.clear()

    def resolve(self, app_id):
        app_id = app_id or "Unknown application"
        if app_id in self.cache:
            return self.cache[app_id]
        label, name = self.entries.get(app_id.lower(), (app_id.rsplit(".", 1)[-1], app_id))
        target = self.appearance.settings.icon_size if self.appearance else 38
        icon_path = self._theme_icon_path(name, target)
        icon = QIcon(icon_path) if icon_path else (QIcon(name) if Path(name).is_absolute() else QIcon.fromTheme(name))
        if icon.isNull():
            themed = QIcon.fromTheme(app_id.lower())
            icon_path = self._theme_icon_path(app_id.lower(), target)
            icon = QIcon(icon_path) if icon_path else themed
        if icon.isNull():
            palette = self.appearance.palette if self.appearance else None
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(palette.node_background if palette else "#32445d"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(2, 2, 60, 60), 16, 16)
            painter.setPen(QColor(palette.primary_text if palette else "#d6e5fc"))
            family = self.appearance.settings.font_family if self.appearance else "Sans Serif"
            painter.setFont(QFont(family, 22, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, label[:2].upper())
            painter.end()
            icon = QIcon(pixmap)
            self.fallback_apps.add(app_id)
        self.cache[app_id] = label, icon
        return label, icon

    def _site_icon(self, site):
        if site not in self.site_icons:
            target = self.appearance.settings.icon_size if self.appearance else 38
            icon = None
            for name in SITE_ICON_NAMES[site]:
                path = self._theme_icon_path(name, target)
                candidate = QIcon(path) if path else QIcon.fromTheme(name)
                if not candidate.isNull():
                    icon = candidate
                    break
            self.site_icons[site] = icon
        return self.site_icons[site]

    def resolve_for_window(self, app_id, title, hostname=None):
        label, app_icon = self.resolve(app_id)
        if is_browser_app(app_id):
            site = site_for_hostname(hostname) if hostname is not None else site_for_title(title)
            if site:
                return label, self._site_icon(site) or app_icon
        return label, app_icon

    def rendered(self, app_id, size, title=None, hostname=None):
        """Return a cached, smoothly downsampled icon without changing its ratio."""
        app_id = app_id or "Unknown application"
        site = None
        if is_browser_app(app_id):
            site = site_for_hostname(hostname) if hostname is not None else site_for_title(title)
        key = (app_id, site, size)
        if key not in self.pixmaps:
            _label, icon = self.resolve_for_window(app_id, title, hostname)
            source = icon.pixmap(QSize(size * 2, size * 2))
            if not source.isNull():
                ratio = source.devicePixelRatio()
                target = QSize(round(size * ratio), round(size * ratio))
                pixmap = source.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                pixmap.setDevicePixelRatio(ratio)
                self.pixmaps[key] = pixmap
            else:
                self.pixmaps[key] = source
        return self.pixmaps[key]
