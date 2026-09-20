"""Resolve installed desktop application logos, including Flatpak exports."""
import configparser
import os
from pathlib import Path
import re
from .browser_bridge import site_for_hostname
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QImageReader, QPainter, QPixmap
from .appearance import DEFAULT_PALETTE
from .icon_catalog import DEFAULT_CATALOG

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
        self.catalog_icons = {}
        self.catalog_asset_versions = {}
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
        self.catalog_icons.clear()
        self.catalog_asset_versions.clear()
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

    def catalog_icon(self, icon_id):
        """Return bundled catalog artwork before considering an icon-theme fallback."""
        entry = DEFAULT_CATALOG.get(icon_id)
        if entry is None:
            return None
        version = None
        if entry.asset_path and entry.asset_path.is_file():
            try:
                details = entry.asset_path.stat()
                version = details.st_mtime_ns, details.st_size
            except OSError:
                pass
        if icon_id in self.catalog_icons and self.catalog_asset_versions.get(icon_id) == version:
            return self.catalog_icons[icon_id]
        self.catalog_icons.pop(icon_id, None)
        self.catalog_asset_versions[icon_id] = version
        # A manual asset can be replaced while the dashboard is running. Drop
        # only the corresponding rendered card cache so it is not kept stale.
        self.pixmaps = {key: value for key, value in self.pixmaps.items() if key[2] != icon_id}
        target = self.appearance.settings.icon_size if self.appearance else 38
        icon = None
        if entry.asset_path and entry.asset_path.is_file():
            icon = QIcon(str(entry.asset_path))
        for name in entry.icon_names:
            if icon is not None:
                break
            path = self._theme_icon_path(name, target)
            candidate = QIcon(path) if path else QIcon.fromTheme(name)
            if not candidate.isNull():
                icon = candidate
                break
        if icon is None:
            # A compact local fallback keeps every catalog item usable even when
            # the selected icon theme does not provide a brand logo.
            palette = self.appearance.palette if self.appearance else DEFAULT_PALETTE
            pixmap = QPixmap(128, 128)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(palette.focused_background))
            painter.setPen(QColor(palette.focused_border))
            painter.drawEllipse(QRectF(4, 4, 120, 120))
            painter.setPen(QColor(palette.focused_text))
            family = self.appearance.settings.font_family if self.appearance else "Sans Serif"
            painter.setFont(QFont(family, 42, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, 128, 128), Qt.AlignmentFlag.AlignCenter, entry.name[0])
            painter.end()
            icon = QIcon(pixmap)
        self.catalog_icons[icon_id] = icon
        return icon

    @staticmethod
    def _opaque_bounds(image):
        """Return the smallest rectangle containing non-transparent pixels."""
        left, top = image.width(), image.height()
        right = bottom = -1
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha():
                    left, right = min(left, x), max(right, x)
                    top, bottom = min(top, y), max(bottom, y)
        if right < left or bottom < top:
            return None
        return image.rect().adjusted(left, top, -(image.width() - right - 1),
                                     -(image.height() - bottom - 1))

    def normalized_pixmap(self, icon, size):
        """Center an icon's visible artwork in a square slot without distortion."""
        density = 4
        physical_size = size * density
        source = icon.pixmap(QSize(physical_size, physical_size))
        if source.isNull():
            return source
        bounds = self._opaque_bounds(source.toImage())
        if bounds:
            source = source.copy(bounds)
        artwork = source.scaled(QSize(physical_size, physical_size),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        result = QPixmap(physical_size, physical_size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap((physical_size - artwork.width()) // 2,
                           (physical_size - artwork.height()) // 2, artwork)
        painter.end()
        result.setDevicePixelRatio(density)
        return result

    def catalog_icon_for_size(self, icon_id, size):
        """Return a catalog icon normalized for a picker or card square slot."""
        icon = self.catalog_icon(icon_id)
        return QIcon(self.normalized_pixmap(icon, size)) if icon else QIcon()

    def resolve_for_window(self, app_id, title, hostname=None, icon_override=None):
        label, app_icon = self.resolve(app_id)
        manual = self.catalog_icon(icon_override) if icon_override else None
        if manual is not None:
            return label, manual
        if is_browser_app(app_id):
            site = site_for_hostname(hostname) if hostname is not None else site_for_title(title)
            if site:
                return label, self._site_icon(site) or app_icon
        return label, app_icon

    def rendered(self, app_id, size, title=None, hostname=None, icon_override=None):
        """Return a cached, smoothly downsampled icon without changing its ratio."""
        app_id = app_id or "Unknown application"
        site = None
        if is_browser_app(app_id):
            site = site_for_hostname(hostname) if hostname is not None else site_for_title(title)
        key = (app_id, site, icon_override, size)
        if icon_override:
            self.catalog_icon(icon_override)
        if key not in self.pixmaps:
            _label, icon = self.resolve_for_window(app_id, title, hostname, icon_override)
            self.pixmaps[key] = self.normalized_pixmap(icon, size)
        return self.pixmaps[key]
