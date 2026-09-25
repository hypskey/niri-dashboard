"""Compact, low-overhead Linux system status panel for the dashboard."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .appearance import DEFAULT_PALETTE, DashboardSettings


@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: float | None = None
    ram_percent: float | None = None
    cpu_temperature: float | None = None


class LinuxSystemMetrics:
    """Read CPU, memory and temperature from standard Linux kernel files."""

    def __init__(self, proc_root="/proc", sys_root="/sys"):
        self.proc_root = Path(proc_root)
        self.sys_root = Path(sys_root)
        self.previous_cpu = None
        self.temperature_paths = self._discover_temperature_paths()

    @staticmethod
    def _read_text(path):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    def cpu_percent(self):
        try:
            fields = (self.proc_root / "stat").read_text(
                encoding="utf-8", errors="replace").splitlines()[0].split()
            if not fields or fields[0] != "cpu":
                return None
            values = [int(value) for value in fields[1:]]
            if len(values) < 4:
                return None
        except (OSError, ValueError, IndexError):
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        current = (total, idle)
        previous, self.previous_cpu = self.previous_cpu, current
        if previous is None:
            return None
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0,
                            100.0 * (total_delta - idle_delta) / total_delta))

    def ram_percent(self):
        try:
            values = {}
            for line in (self.proc_root / "meminfo").read_text(
                    encoding="utf-8", errors="replace").splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    values[key] = int(value.split()[0])
            total = values["MemTotal"]
            available = values["MemAvailable"]
            if total <= 0:
                return None
        except (OSError, ValueError, KeyError, IndexError):
            return None
        return max(0.0, min(100.0, 100.0 * (total - available) / total))

    def _discover_temperature_paths(self):
        candidates = []
        hwmon_root = self.sys_root / "class/hwmon"
        try:
            hwmons = sorted(hwmon_root.glob("hwmon*"))
        except OSError:
            hwmons = []
        for hwmon in hwmons:
            sensor_name = self._read_text(hwmon / "name").lower()
            try:
                inputs = sorted(hwmon.glob("temp*_input"))
            except OSError:
                inputs = []
            for path in inputs:
                label = self._read_text(
                    path.with_name(path.name.replace("_input", "_label"))).lower()
                identity = f"{sensor_name} {label}"
                if any(token in identity for token in
                       ("package id", "tctl", "tdie", "cpu", "coretemp",
                        "k10temp", "zenpower")):
                    priority = 0 if any(token in identity for token in
                                        ("package id", "tctl", "tdie")) else 1
                    candidates.append((priority, str(path), path))

        thermal_root = self.sys_root / "class/thermal"
        try:
            zones = sorted(thermal_root.glob("thermal_zone*"))
        except OSError:
            zones = []
        for zone in zones:
            kind = self._read_text(zone / "type").lower()
            if any(token in kind for token in
                   ("x86_pkg_temp", "cpu", "soc", "acpitz")):
                path = zone / "temp"
                candidates.append((2, str(path), path))
        return [path for _priority, _name, path in sorted(candidates)]

    def cpu_temperature(self):
        for path in self.temperature_paths:
            try:
                value = float(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            if abs(value) >= 1000:
                value /= 1000.0
            if -20 <= value <= 150:
                return value
        return None

    def snapshot(self):
        return SystemSnapshot(self.cpu_percent(), self.ram_percent(),
                              self.cpu_temperature())


class SystemStatusWidget(QWidget):
    """A small Noctalia-colored clock and system telemetry HUD."""

    WIDTH = 304
    HEIGHT = 88
    METRICS_INTERVAL_MS = 2000
    CLOCK_INTERVAL_MS = 1000
    ANCHOR_MARGIN = 14

    def __init__(self, palette=None, settings=None, metrics=None, clock=None,
                 parent=None):
        super().__init__(parent)
        self.colors = palette or DEFAULT_PALETTE
        self.settings = settings or DashboardSettings()
        self.metrics = metrics or LinuxSystemMetrics()
        self.clock = clock or datetime.now
        self.snapshot = SystemSnapshot()
        self.time_text = "--:--"
        self.seconds_text = "--"
        self.date_text = "--- · -- --- ----"
        self._apply_scale()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self.anchor_parent = parent
        if self.anchor_parent is not None:
            self.anchor_parent.installEventFilter(self)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(self.CLOCK_INTERVAL_MS)
        self.clock_timer.timeout.connect(self.refresh_clock)
        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(self.METRICS_INTERVAL_MS)
        self.metrics_timer.timeout.connect(self.refresh_metrics)
        self.refresh_clock()
        self.refresh_metrics()
        self.clock_timer.start()
        self.metrics_timer.start()
        self.reposition()

    def sizeHint(self):
        return QSize(self.settings.scaled(self.WIDTH),
                     self.settings.scaled(self.HEIGHT))

    def _apply_scale(self):
        self.setFixedSize(self.settings.scaled(self.WIDTH),
                          self.settings.scaled(self.HEIGHT))

    def set_appearance(self, palette, settings):
        self.colors = palette
        self.settings = settings
        self._apply_scale()
        self.setStyleSheet("background: transparent; border: none;")
        self.reposition()
        self.update()

    def eventFilter(self, watched, event):
        if (watched is self.anchor_parent and
                event.type() in (QEvent.Type.Resize, QEvent.Type.Show)):
            self.reposition()
        return super().eventFilter(watched, event)

    def reposition(self):
        if self.anchor_parent is None:
            return
        margin = self.settings.scaled(self.ANCHOR_MARGIN)
        self.move(margin,
                  max(margin,
                      self.anchor_parent.height() - self.height() -
                      margin))
        self.raise_()

    def refresh_clock(self):
        now = self.clock()
        self.time_text = now.strftime("%H:%M")
        self.seconds_text = now.strftime("%S")
        self.date_text = now.strftime("%a · %d %b %Y").upper()
        self.update()

    def refresh_metrics(self):
        self.snapshot = self.metrics.snapshot()
        self.update()

    @staticmethod
    def _value_text(value, temperature=False):
        if value is None:
            return "—"
        suffix = "°" if temperature else "%"
        return f"{round(value):d}{suffix}"

    @staticmethod
    def _fraction(value, temperature=False):
        if value is None:
            return 0.0
        if temperature:
            return max(0.0, min(1.0, (value - 25.0) / 75.0))
        return max(0.0, min(1.0, value / 100.0))

    def _font(self, pixels, weight=QFont.Weight.Normal, monospace=False):
        family = "monospace" if monospace else self.settings.font_family
        result = QFont(family)
        result.setPixelSize(pixels)
        result.setWeight(weight)
        if monospace:
            result.setStyleHint(QFont.StyleHint.Monospace)
        return result

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.settings.global_scale, self.settings.global_scale)
        accent = QColor(self.colors.focused_route)
        primary = QColor(self.colors.primary_text)
        secondary = QColor(self.colors.secondary_text)

        painter.setPen(primary)
        painter.setFont(self._font(25, QFont.Weight.DemiBold, True))
        painter.drawText(QRectF(8, 9, 84, 31),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.time_text)
        painter.setPen(accent)
        painter.setFont(self._font(10, QFont.Weight.DemiBold, True))
        painter.drawText(QRectF(90, 13, 23, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.seconds_text)
        painter.setPen(secondary)
        painter.setFont(self._font(9, QFont.Weight.Medium, True))
        painter.drawText(QRectF(8, 48, 108, 18),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.date_text)
        accent_rule = QColor(accent)
        accent_rule.setAlpha(180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent_rule)
        painter.drawRoundedRect(QRectF(8, 72, 42, 2), 1, 1)

        divider = QColor(self.colors.neutral_pipe)
        divider.setAlpha(90)
        painter.setPen(QPen(divider, 1))
        painter.drawLine(122, 12, 122, self.height() - 12)

        metrics = (
            ("CPU", self.snapshot.cpu_percent, False),
            ("RAM", self.snapshot.ram_percent, False),
            ("TMP", self.snapshot.cpu_temperature, True),
        )
        label_font = self._font(9, QFont.Weight.DemiBold, True)
        value_font = self._font(10, QFont.Weight.DemiBold, True)
        for row, (label, value, temperature) in enumerate(metrics):
            top = 8 + row * 24
            painter.setFont(label_font)
            painter.setPen(secondary)
            painter.drawText(QRectF(134, top, 32, 15),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             label)
            painter.setFont(value_font)
            painter.setPen(primary if value is not None else secondary)
            painter.drawText(QRectF(242, top, 42, 15),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             self._value_text(value, temperature))
            track = QRectF(170, top + 7, 64, 3)
            track_color = QColor(self.colors.neutral_pipe)
            track_color.setAlpha(65)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track_color)
            painter.drawRoundedRect(track, 1.5, 1.5)
            fraction = self._fraction(value, temperature)
            if fraction:
                fill = QColor(accent)
                fill.setAlpha(210)
                painter.setBrush(fill)
                painter.drawRoundedRect(
                    QRectF(track.left(), track.top(), track.width() * fraction,
                           track.height()), 1.5, 1.5)
        painter.end()
