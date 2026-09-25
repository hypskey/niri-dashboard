"""Resident floating presentation of the existing graph; no layer-shell."""
import os
import sys
import threading
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from .main import GraphWindow
from .appearance import DashboardSettings
from .hints import NumericSelector
from . import niri


def overlay_size(bounds, logical, settings=None):
    """Keep the scene's existing padding, native scale, and a visible desktop rim."""
    settings = settings or DashboardSettings()
    max_width = max(200, round(logical["width"] * settings.overlay_max_width_percent / 100))
    max_height = max(150, round(logical["height"] * settings.overlay_max_height_percent / 100))
    scale = min(1.0, max(1, max_width - 8) / max(1, bounds.width()),
                max(1, max_height - 8) / max(1, bounds.height()))
    return (min(max_width, max(settings.overlay_min_width, round(bounds.width() * scale) + 8)),
            min(max_height, max(settings.overlay_min_height, round(bounds.height() * scale) + 8)))


class OverlayWindow(GraphWindow):
    def __init__(self, controller):
        self.background_opacity = controller.appearance.settings.overlay_opacity
        super().__init__(controller, translucent=self.background_opacity < 1)
        self.view.background_grid = False
        self.view.numeric_selection_enabled = True
        self.setWindowTitle(niri.OVERLAY_TITLE)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        if self.background_opacity < 1:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("niridashboard-overlay-window")
        self.setMinimumSize(200, 150)
        root = QWidget()
        root.setObjectName("niridashboard-overlay-root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            f"color: {controller.appearance.palette.error_text}; "
            f"padding: {controller.appearance.settings.scaled(10)}px;")
        self.error.hide()
        layout.addWidget(self.error)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(root)
        self.phase = "hidden"
        self.desired = False
        self.context = None
        self.window_id = None
        self.placement_pending = False
        self.cancelled = threading.Event()
        self.generation = 0
        self.opened_at = None
        self.map_requested_at = None
        self.last_open_ms = None
        self.timings_ms = {}
        self.failure = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fail("Overlay mapping timed out. Check the Niri rule and connection."))
        self.map_measure_timer = QTimer(self)
        self.map_measure_timer.setSingleShot(True)
        self.map_measure_timer.timeout.connect(self._measure_mapping)
        self.numeric = NumericSelector(parent=self)
        self.numeric.selected.connect(lambda window_id: self.command("focus", window_id))
        self.view.numeric_pressed.connect(self.handle_numeric)
        self.view.escape_pressed.connect(self.handle_escape)
        controller.attach(self)
        controller.raw_state.connect(self.observe_raw)

    def receive_appearance(self):
        super().receive_appearance()
        colors = self.controller.appearance.palette
        padding = self.controller.appearance.settings.scaled(10)
        if self.background_opacity < 1:
            # Paint the translucent color exactly once, beneath all child widgets.
            self.setStyleSheet("#niridashboard-overlay-window, #niridashboard-overlay-root { background: transparent; border: 0px; }")
            for widget in (self, self.centralWidget(), self.view, self.view.viewport(), self.error):
                widget.setAutoFillBackground(False)
                widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
                palette = widget.palette()
                palette.setColor(palette.ColorRole.Window, Qt.GlobalColor.transparent)
                palette.setColor(palette.ColorRole.Base, Qt.GlobalColor.transparent)
                widget.setPalette(palette)
            self.error.setStyleSheet(
                f"color: {colors.error_text}; background: transparent; "
                f"padding: {padding}px;")
            self.update()
            return
        self.setStyleSheet(
            f"#niridashboard-overlay-window, #niridashboard-overlay-root {{ "
            f"background-color: {colors.dashboard_background}; border: 0px; }}")
        for widget in (self, self.centralWidget(), self.view, self.view.viewport()):
            palette = widget.palette()
            palette.setColor(palette.ColorRole.Window, QColor(colors.dashboard_background))
            palette.setColor(palette.ColorRole.Base, QColor(colors.dashboard_background))
            widget.setPalette(palette)
            widget.setAutoFillBackground(True)
        self.error.setStyleSheet(
            f"color: {colors.error_text}; padding: {padding}px;")

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.background_opacity < 1:
            color = QColor(self.controller.appearance.palette.dashboard_background)
            color.setAlphaF(self.background_opacity)
            painter = QPainter(self)
            painter.fillRect(event.rect(), color)
            painter.end()

    def handle_escape(self):
        if not self.numeric.cancel_pending():
            self.dismiss()

    def handle_numeric(self, digit):
        if self.phase == "visible":
            self.numeric.press(digit)

    def toggle(self, ipc_latency_ms=0):
        self.desired = not self.desired
        if self.desired and self.phase == "hidden":
            self.begin_open(ipc_latency_ms)
        elif not self.desired and self.phase not in ("hidden", "closing"):
            self.begin_hide()
        return self.phase

    def dismiss(self):
        self.desired = False
        if self.phase not in ("hidden", "closing"):
            self.begin_hide()

    def begin_open(self, ipc_latency_ms=0):
        self.phase = "capturing"
        self.context = None
        self.window_id = None
        self.placement_pending = False
        self.failure = None
        self.last_open_ms = None
        self.generation += 1
        generation = self.generation
        self.cancelled = threading.Event()
        self.opened_at = time.monotonic()
        self.timings_ms = {"ipc_request_to_receipt": round(float(ipc_latency_ms), 3)}
        self.controller.set_transition(True)
        self.timeout.start(5000)
        capture_started = time.perf_counter()
        cached = self.controller.backend.data if self.controller.backend.demo else self.controller.raw
        if cached is not None:
            try:
                context = niri.overlay_context(cached, target_output=None if self.controller.backend.demo else "DP-3")
                self.timings_ms["state_capture"] = round((time.perf_counter() - capture_started) * 1000, 3)
                self.captured(generation, True, context)
                return
            except RuntimeError:
                pass
        def capture():
            started = time.perf_counter()
            context = niri.overlay_context(self.controller.backend.data) if self.controller.backend.demo else niri.capture_overlay_context(target_output="DP-3")
            return context, round((time.perf_counter() - started) * 1000, 3)
        self.controller.task(capture, lambda ok, value: self.captured(generation, ok, value))

    def captured(self, generation, success, context):
        if generation != self.generation or self.phase != "capturing" or not self.desired:
            return
        if not success:
            self.fail(context)
            return
        if isinstance(context, tuple) and len(context) == 2 and isinstance(context[1], (int, float)):
            context, capture_ms = context
            self.timings_ms["state_capture"] = capture_ms
        self.context = context
        prepare_started = time.perf_counter()
        screen = next((screen for screen in QApplication.screens() if screen.name() == context["output"]), None)
        if screen is None and self.controller.backend.demo:
            screen = QApplication.primaryScreen()
        if screen is None:
            self.fail(f"Qt could not find focused output {context['output']}.")
            return
        # Create the native handle without mapping, so the output hint is set first.
        self.winId()
        handle = self.windowHandle()
        handle.setScreen(screen)
        logical = context["logical"]
        # Render only changed cached state before measuring; warm toggles reuse the scene.
        state = self.controller.latest
        if state is not None and state != self.last_state:
            self.last_state = state
            self.pending = None
            self.view.render(state)
        context["overlay_size"] = overlay_size(self.view.sceneRect(), logical, self.controller.appearance.settings)
        # Requested presentation enlargement; leave the TOML sizing calculation alone.
        width, height = context["overlay_size"]
        context["overlay_size"] = (min(round(width * 1.2), round(logical["width"] * .96)),
                                   min(round(height * 1.2), round(logical["height"] * .96)))
        self.resize(*context["overlay_size"])
        self.view.auto_fit = True
        self.error.hide()
        self.phase = "mapping"
        map_call_started = time.perf_counter()
        self.map_requested_at = time.monotonic()
        self.show()
        self.view.show()
        self.timings_ms["overlay_prepare"] = round((map_call_started - prepare_started) * 1000, 3)
        self.timings_ms["qt_map_request"] = round((time.perf_counter() - map_call_started) * 1000, 3)
        self.map_measure_timer.start(8)
        self.phase = "visible"
        self.controller.set_transition(False)
        graph_started = time.perf_counter()
        self.pending = self.controller.latest
        self.apply_pending()
        self.view.fit_graph()
        self.timings_ms["graph_update_layout"] = round((time.perf_counter() - graph_started) * 1000, 3)
        self.activateWindow()
        self.view.setFocus()
        if not self.controller.backend.demo:
            # Show cached state immediately; this wakes the same worker to reconcile fresh state.
            self.controller.task(lambda: None, lambda ok, value: None)
        elif self.last_open_ms is None:
            self.timings_ms["qt_mapping"] = round((time.monotonic() - self.map_requested_at) * 1000, 3)
            self.last_open_ms = round((time.monotonic() - self.opened_at) * 1000, 1)
            self.timings_ms["visible_from_toggle"] = self.last_open_ms

    def _measure_mapping(self):
        if self.phase not in ("mapping", "visible") or not self.desired or self.map_requested_at is None:
            return
        mapped_at = time.monotonic()
        if self.windowHandle() and self.windowHandle().isExposed():
            self.timings_ms["qt_mapping"] = round((mapped_at - self.map_requested_at) * 1000, 3)
            self.last_open_ms = round((mapped_at - self.opened_at) * 1000, 1)
            self.timings_ms["visible_from_toggle"] = self.last_open_ms
        elif mapped_at - self.map_requested_at < 1.5:
            self.map_measure_timer.start(8)

    def observe_raw(self, data):
        if self.phase not in ("mapping", "visible") or self.placement_pending:
            return
        overlay = next((w for w in data["windows"] if niri.is_overlay(w) and w.get("pid") == os.getpid()), None)
        if overlay is None:
            return
        self.window_id = overlay["id"]
        self.placement_pending = True
        discovered_ms = round((time.monotonic() - self.map_requested_at) * 1000, 3)
        self.timings_ms["niri_window_id_discovery"] = discovered_ms
        self.map_measure_timer.stop()
        self.timings_ms.setdefault("qt_mapping", discovered_ms)
        if self.last_open_ms is None:
            self.last_open_ms = round((time.monotonic() - self.opened_at) * 1000, 1)
            self.timings_ms["visible_from_toggle"] = self.last_open_ms
        generation = self.generation

        # TEMP TEST: do not reposition the overlay after Niri maps it.
        self.placed(generation, True, {"placement": 0, "focus": 0})

    def placed(self, generation, success, value):
        if generation != self.generation or self.phase not in ("mapping", "visible") or not self.desired:
            return
        self.placement_pending = False
        if not success:
            self.fail(value)
            return
        self.timings_ms["niri_placement"] = value.get("placement", 0)
        self.timings_ms["niri_focus"] = value.get("focus", 0)
        self.timeout.stop()
        if "qt_mapping" not in self.timings_ms:
            self.timings_ms["qt_mapping"] = round((time.monotonic() - self.opened_at) * 1000, 3)

    def begin_hide(self, selected=None):
        self.numeric.cancel_pending()
        self.timeout.stop()
        self.map_measure_timer.stop()
        self.cancelled.set()
        old_phase = self.phase
        self.phase = "closing"
        self.generation += 1
        self.controller.set_transition(True)
        self.view.cancel_drag()
        self.view.panning = False
        self.hide()
        raw = self.controller.raw or {"windows": []}
        focused = next((w for w in raw["windows"] if w.get("is_focused")), None)
        # Respect an intentional focus change outside the overlay. A move in flight
        # must finish before restoration; its own focus changes are temporary.
        restore = (focused is None or niri.is_overlay(focused) or self.controller.action_origin is self)
        if old_phase == "capturing":
            restore = False
        context = self.context
        def finish():
            if self.controller.backend.demo:
                if selected is not None:
                    self.controller.backend.demo_action("focus", [selected])
            elif selected is not None:
                if any(w["id"] == selected for w in niri.get_windows()):
                    niri.focus_window(selected)
                else:
                    niri.restore_overlay_focus(context, restore)
            else:
                niri.restore_overlay_focus(context, restore)
        self.controller.task(finish, self.hidden)

    def hidden(self, success, message):
        self.phase = "hidden"
        self.window_id = None
        self.context = None
        self.controller.set_transition(False)
        if not success:
            self.failure = str(message)
            print(f"Overlay focus restoration: {message}", file=sys.stderr)
        if self.desired and not self.controller.stopping:
            self.begin_open()

    def command(self, kind, *args):
        if self.phase != "visible" or self.controller.busy or not self.controller.connected:
            return
        if kind == "focus":
            self.desired = False
            self.begin_hide(selected=args[0])
        else:
            super().command(kind, *args)

    def apply_pending(self):
        if getattr(self, "phase", "hidden") == "visible":
            super().apply_pending()
            self.numeric.update(self.view.hint_assignments.by_window)

    def receive_health(self, connected, message):
        super().receive_health(connected, message)
        if not connected and getattr(self, "phase", "hidden") not in ("hidden", "closing"):
            self.fail(message)

    def fail(self, message):
        self.failure = str(message)
        print(f"Overlay: {message}", file=sys.stderr)
        self.dismiss()

    def closeEvent(self, event):
        event.ignore()
        self.dismiss()

    def shutdown(self):
        self.timeout.stop()
        self.desired = False
        if self.phase not in ("hidden", "closing"):
            self.begin_hide()
