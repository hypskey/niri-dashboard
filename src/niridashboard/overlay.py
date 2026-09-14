"""Resident floating presentation of the existing graph; no layer-shell."""
import os
import sys
import threading
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from .main import GraphWindow
from . import niri


class OverlayWindow(GraphWindow):
    def __init__(self, controller):
        super().__init__(controller, translucent=True)
        self.setWindowTitle(niri.OVERLAY_TITLE)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setObjectName("niridashboard-overlay-window")
        self.setStyleSheet("#niridashboard-overlay-window, #niridashboard-overlay-root { background-color: transparent; border: 0px; }")
        self.setMinimumSize(200, 150)
        root = QWidget()
        root.setObjectName("niridashboard-overlay-root")
        root.setAutoFillBackground(False)
        root.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        root.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        root.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        palette = root.palette()
        palette.setColor(palette.ColorRole.Window, Qt.GlobalColor.transparent)
        root.setPalette(palette)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #8c4a4a; padding: 10px;")
        self.error.hide()
        layout.addWidget(self.error)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(root)
        self.phase = "hidden"
        self.desired = False
        self.context = None
        self.window_id = None
        self.cancelled = threading.Event()
        self.generation = 0
        self.opened_at = None
        self.last_open_ms = None
        self.failure = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fail("Overlay mapping timed out. Check the Niri rule and connection."))
        self.escape = QShortcut(QKeySequence("Escape"), self)
        self.escape.activated.connect(self.dismiss)
        self.view.escape_pressed.connect(self.dismiss)
        controller.attach(self)
        controller.raw_state.connect(self.observe_raw)

    def toggle(self):
        self.desired = not self.desired
        if self.desired and self.phase == "hidden":
            self.begin_open()
        elif not self.desired and self.phase not in ("hidden", "closing"):
            self.begin_hide()
        return self.phase

    def dismiss(self):
        self.desired = False
        if self.phase not in ("hidden", "closing"):
            self.begin_hide()

    def begin_open(self):
        self.phase = "capturing"
        self.context = None
        self.window_id = None
        self.failure = None
        self.generation += 1
        generation = self.generation
        self.cancelled = threading.Event()
        self.opened_at = time.monotonic()
        self.controller.set_transition(True)
        self.timeout.start(5000)
        capture = (lambda: niri.overlay_context(self.controller.backend.data)) if self.controller.backend.demo else niri.capture_overlay_context
        self.controller.task(capture, lambda ok, value: self.captured(generation, ok, value))

    def captured(self, generation, success, context):
        if generation != self.generation or self.phase != "capturing" or not self.desired:
            return
        if not success:
            self.fail(context)
            return
        self.context = context
        screen = next((screen for screen in QApplication.screens() if screen.name() == context["output"]), None)
        if screen is None and self.controller.backend.demo:
            screen = QApplication.primaryScreen()
        if screen is None:
            self.fail(f"Qt could not find focused output {context['output']}.")
            return
        # Create the native handle without mapping, so the output hint is set first.
        self.winId()
        self.windowHandle().setScreen(screen)
        logical = context["logical"]
        self.resize(round(logical["width"] * .9), round(logical["height"] * .9))
        self.view.auto_fit = True
        self.view.hide()  # The initial mapping is transparent until placement completes.
        self.error.hide()
        self.phase = "mapping"
        self.show()
        if self.controller.backend.demo:
            self.placed(generation, True, None)
        else:
            # Wake the existing worker immediately; don't wait for its polling interval.
            self.controller.task(lambda: None, lambda ok, value: None)

    def observe_raw(self, data):
        if self.phase != "mapping":
            return
        overlay = next((w for w in data["windows"] if niri.is_overlay(w) and w.get("pid") == os.getpid()), None)
        if overlay is None:
            return
        self.window_id = overlay["id"]
        self.phase = "placing"
        generation, context, cancelled, wid = self.generation, self.context, self.cancelled, self.window_id
        self.controller.task(lambda: niri.place_overlay(wid, context, cancelled, os.getpid()),
                             lambda ok, value: self.placed(generation, ok, value))

    def placed(self, generation, success, value):
        if generation != self.generation or self.phase not in ("mapping", "placing") or not self.desired:
            return
        if not success:
            self.fail(value)
            return
        self.timeout.stop()
        self.phase = "visible"
        self.view.show()
        self.controller.set_transition(False)
        self.pending = self.controller.latest
        self.apply_pending()
        self.view.fit_graph()
        self.activateWindow()
        self.view.setFocus()
        self.last_open_ms = round((time.monotonic() - self.opened_at) * 1000, 1)

    def begin_hide(self, selected=None):
        self.timeout.stop()
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
