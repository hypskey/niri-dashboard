"""Noctalia color provider and centralized non-color dashboard settings."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from PySide6.QtCore import QObject, QFileSystemWatcher, QTimer, Signal
from PySide6.QtGui import QColor


@dataclass(frozen=True)
class Palette:
    dashboard_background: str
    primary_text: str
    secondary_text: str
    output_label: str
    workspace_number: str
    application_title: str
    window_title: str
    node_background: str
    node_border: str
    focused_background: str
    focused_border: str
    focused_text: str
    pipe_colors: tuple[str, ...]
    neutral_pipe: str
    focused_route: str
    hint_background: str
    hint_border: str
    hint_text: str
    error_background: str
    error_text: str


DEFAULT_PALETTE = Palette(
    dashboard_background="#f5f2ed", primary_text="#434853", secondary_text="#737681",
    output_label="#a9cdbf", workspace_number="#a9cdbf", application_title="#434853",
    window_title="#737681", node_background="#fffcf8", node_border="#d2ccc4",
    focused_background="#cdd8ff", focused_border="#1e2e5a", focused_text="#1e2e5a",
    pipe_colors=("#a9cdbf", "#b9b6dd", "#dfbca7", "#d7b4c9"),
    neutral_pipe="#d0d4dc", focused_route="#5fae76",
    hint_background="#cdd8ff", hint_border="#1e2e5a", hint_text="#1e2e5a",
    error_background="#f1deda", error_text="#8c4a4a",
)


@dataclass(frozen=True)
class DashboardSettings:
    font_family: str = "Sans Serif"
    normal_text_size: int = 10
    output_label_size: int = 15
    workspace_number_size: int = 11
    application_title_size: int = 9
    window_title_size: int = 8
    hint_badge_font_size: int = 9
    icon_size: int = 38
    node_width: int = 108
    node_height: int = 100
    workspace_step: int = 136
    workspace_row: int = 144
    branch_gap: int = 60
    graph_padding: int = 32
    overlay_max_width_percent: int = 86
    overlay_max_height_percent: int = 86
    overlay_min_width: int = 360
    overlay_min_height: int = 220
    overlay_opacity: float = 1.0
    background_opacity: float = 1.0
    focus_path_glow: bool = True
    focus_path_flow: bool = True
    focus_path_flow_speed: float = 1.0

    @classmethod
    def load(cls, path=None):
        path = Path(path or default_config_path())
        try:
            with path.open("rb") as stream:
                parsed = tomllib.load(stream)
            if not isinstance(parsed, dict):
                return cls()
        except (OSError, tomllib.TOMLDecodeError, UnicodeError):
            return cls()
        font = parsed.get("font", {})
        graph = parsed.get("graph", {})
        if not isinstance(font, dict):
            font = {}
        if not isinstance(graph, dict):
            graph = {}
        defaults = cls()
        family = font.get("family", defaults.font_family)
        if not isinstance(family, str) or not family.strip() or len(family) > 128:
            family = defaults.font_family

        def integer(table, key, default, low, high):
            value = table.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                return default
            return value

        overlay = parsed.get("overlay", {})
        if not isinstance(overlay, dict):
            overlay = {}
        appearance = parsed.get("appearance", {})
        if not isinstance(appearance, dict):
            appearance = {}
        focus_path = parsed.get("focus_path", {})
        if not isinstance(focus_path, dict):
            focus_path = {}
        glow = focus_path.get("glow", defaults.focus_path_glow)
        flow = focus_path.get("flow", defaults.focus_path_flow)
        flow_speed = focus_path.get("flow_speed", defaults.focus_path_flow_speed)
        if isinstance(flow_speed, bool) or not isinstance(flow_speed, (int, float)) or not .1 <= flow_speed <= 5:
            flow_speed = defaults.focus_path_flow_speed

        opacity = overlay.get("opacity", defaults.overlay_opacity)
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0 <= opacity <= 1:
            opacity = defaults.overlay_opacity
        background_opacity = appearance.get("background_opacity", defaults.background_opacity)
        if isinstance(background_opacity, bool) or not isinstance(background_opacity, (int, float)):
            background_opacity = defaults.background_opacity
        background_opacity = max(0.0, min(1.0, float(background_opacity)))

        icon_size = integer(graph, "icon_size", defaults.icon_size, 16, 64)
        node_width = max(icon_size + 24, integer(graph, "node_width", defaults.node_width, 80, 240))
        node_height = max(icon_size + 54, integer(graph, "node_height", defaults.node_height, 72, 200))
        workspace_step = max(node_width + 28, integer(graph, "workspace_step", defaults.workspace_step, 100, 320))
        workspace_row = max(node_height + 44, integer(graph, "workspace_row", defaults.workspace_row, 110, 320))

        return cls(
            font_family=family.strip(),
            normal_text_size=integer(font, "normal_text_size", defaults.normal_text_size, 6, 28),
            output_label_size=integer(font, "output_label_size", defaults.output_label_size, 6, 36),
            workspace_number_size=integer(font, "workspace_number_size", defaults.workspace_number_size, 6, 28),
            application_title_size=integer(font, "application_title_size", defaults.application_title_size, 6, 28),
            window_title_size=integer(font, "window_title_size", defaults.window_title_size, 6, 24),
            hint_badge_font_size=integer(font, "hint_badge_font_size", defaults.hint_badge_font_size, 6, 24),
            icon_size=icon_size,
            node_width=node_width,
            node_height=node_height,
            workspace_step=workspace_step,
            workspace_row=workspace_row,
            branch_gap=integer(graph, "branch_gap", defaults.branch_gap, 24, 200),
            graph_padding=integer(graph, "graph_padding", defaults.graph_padding, 0, 160),
            overlay_max_width_percent=integer(overlay, "max_width_percent", defaults.overlay_max_width_percent, 10, 100),
            overlay_max_height_percent=integer(overlay, "max_height_percent", defaults.overlay_max_height_percent, 10, 100),
            overlay_min_width=integer(overlay, "min_width", defaults.overlay_min_width, 200, 7680),
            overlay_min_height=integer(overlay, "min_height", defaults.overlay_min_height, 150, 4320),
            overlay_opacity=float(opacity),
            background_opacity=background_opacity,
            focus_path_glow=glow if isinstance(glow, bool) else defaults.focus_path_glow,
            focus_path_flow=flow if isinstance(flow, bool) else defaults.focus_path_flow,
            focus_path_flow_speed=float(flow_speed),
        )


def default_theme_path():
    return Path.home() / ".config/gtk-4.0/noctalia.css"


def default_config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "niridashboard/config.toml"


def _resolve_colors(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    definitions = dict(re.findall(r"@define-color\s+([\w-]+)\s+([^;]+);", text))
    resolved = {}
    visiting = set()

    def resolve(name):
        if name in resolved:
            return resolved[name]
        if name in visiting or name not in definitions:
            return None
        visiting.add(name)
        raw = definitions[name].strip()
        alias = re.fullmatch(r"@([\w-]+)", raw)
        value = resolve(alias.group(1)) if alias else raw
        visiting.discard(name)
        if value:
            color = QColor(value)
            if color.isValid():
                value = color.name(QColor.NameFormat.HexArgb if color.alpha() != 255 else QColor.NameFormat.HexRgb)
                resolved[name] = value
                return value
        return None

    for name in definitions:
        resolve(name)
    return resolved


def parse_noctalia_css(text):
    """Map GTK @define-color tokens to graph roles; bad/missing colors fall back."""
    values = _resolve_colors(text)
    if not values:
        return DEFAULT_PALETTE

    def token(name, fallback):
        value = values.get(name)
        if not value or not QColor(value).isValid():
            return fallback
        color = QColor(value)
        color.setAlpha(255)
        return color.name(QColor.NameFormat.HexRgb)

    accent = token("accent_bg_color", DEFAULT_PALETTE.output_label)
    accent_fg = token("accent_fg_color", DEFAULT_PALETTE.focused_text)
    selected_bg = token("theme_selected_bg_color", accent)
    selected_fg = token("theme_selected_fg_color", accent_fg)
    primary = token("window_fg_color", DEFAULT_PALETTE.primary_text)
    secondary = token("theme_unfocused_fg_color", token("view_fg_color", DEFAULT_PALETTE.secondary_text))
    neutral_pipe = QColor(token("theme_unfocused_fg_color", DEFAULT_PALETTE.neutral_pipe)).darker(155)
    return Palette(
        dashboard_background=token("window_bg_color", DEFAULT_PALETTE.dashboard_background),
        primary_text=primary,
        secondary_text=secondary,
        output_label=accent,
        workspace_number=accent,
        application_title=token("view_fg_color", primary),
        window_title=secondary,
        node_background=token("card_bg_color", token("view_bg_color", DEFAULT_PALETTE.node_background)),
        node_border=token("accent_bg_color", DEFAULT_PALETTE.node_border),
        focused_background=selected_bg,
        focused_border=selected_fg,
        focused_text=selected_fg,
        pipe_colors=(accent,
                     token("success_color", primary),
                     token("warning_color", token("destructive_bg_color", accent)),
                     token("destructive_bg_color", accent)),
        neutral_pipe=neutral_pipe.name(QColor.NameFormat.HexRgb),
        focused_route=accent,
        hint_background=token("accent_bg_color", selected_bg),
        hint_border=token("accent_fg_color", selected_fg),
        hint_text=token("accent_fg_color", selected_fg),
        error_background=token("error_bg_color", DEFAULT_PALETTE.error_background),
        error_text=token("error_fg_color", DEFAULT_PALETTE.error_text),
    )


class AppearanceProvider(QObject):
    """One palette/settings source shared by all views; colors reload by file watch."""
    changed = Signal()

    def __init__(self, theme_path=None, config_path=None, parent=None):
        super().__init__(parent)
        self.theme_path = Path(theme_path or default_theme_path())
        self.config_path = Path(config_path or default_config_path())
        self.palette = DEFAULT_PALETTE
        self.settings = DashboardSettings.load(self.config_path)
        self.watcher = QFileSystemWatcher(self)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(80)
        self.debounce.timeout.connect(self.reload_theme)
        self.watcher.fileChanged.connect(lambda _path: self.debounce.start())
        self.watcher.directoryChanged.connect(lambda _path: self.debounce.start())
        self._reattach()
        self.reload_theme()

    def _reattach(self):
        watched = set(self.watcher.files()) | set(self.watcher.directories())
        if watched:
            self.watcher.removePaths(list(watched))
        parent = str(self.theme_path.parent)
        if self.theme_path.parent.is_dir():
            self.watcher.addPath(parent)
        if self.theme_path.is_file():
            self.watcher.addPath(str(self.theme_path))

    def reload_theme(self):
        try:
            parsed = parse_noctalia_css(self.theme_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            parsed = DEFAULT_PALETTE
        self._reattach()
        if parsed != self.palette:
            self.palette = parsed
            self.changed.emit()
