"""One live model and serialized action worker shared by all presentations."""
from PySide6.QtCore import QObject, Signal, QTimer
from .backend import Backend
from .icons import Icons
from .browser_tabs import BrowserTabs
from .appearance import AppearanceProvider
from . import niri


class DashboardController(QObject):
    state = Signal(object)
    raw_state = Signal(object)
    health = Signal(bool, str)
    busy_changed = Signal(bool)
    stopped = Signal()
    appearance_changed = Signal()

    def __init__(self, demo=False, start_backend=True):
        super().__init__()
        self.backend = Backend(demo)
        self.appearance = AppearanceProvider()
        self.icons = Icons(self.appearance)
        self.appearance.changed.connect(self._appearance_changed)
        self.latest = None
        self.raw = None
        self.browser_tabs = BrowserTabs(self, enabled=not demo)
        self.browser_tabs.changed.connect(self._publish_state)
        self.connected = False
        self.health_message = "Starting…"
        self.action_origin = None
        self.transition = False
        self.stopping = False
        self.backend.state.connect(self.receive_state)
        self.backend.health.connect(self.receive_health)
        self.backend.finished_action.connect(self.action_finished)
        self.backend.task_finished.connect(self.task_finished)
        if start_backend:
            self.backend.start()

    def _appearance_changed(self):
        self.icons.refresh_theme()
        self.appearance_changed.emit()

    @property
    def busy(self):
        return self.action_origin is not None or self.transition or self.stopping

    def attach(self, window):
        self.state.connect(window.receive_state)
        self.health.connect(window.receive_health)
        self.busy_changed.connect(window.receive_busy)
        window.receive_health(self.connected, self.health_message)
        window.receive_busy(self.busy)
        window.receive_appearance()
        if self.latest is not None:
            window.receive_state(self.latest)

    def receive_state(self, data):
        self.raw = data
        self._publish_state()
        self.raw_state.emit(data)

    def _publish_state(self):
        if self.raw is None:
            return
        filtered = dict(self.raw, windows=[self.browser_tabs.decorate(w)
                        for w in self.raw["windows"] if not niri.is_overlay(w)])
        if filtered != self.latest:
            self.latest = filtered
            self.state.emit(filtered)

    def receive_health(self, connected, message):
        self.connected, self.health_message = connected, message
        self.health.emit(connected, message)

    def set_transition(self, value):
        self.transition = value
        self.busy_changed.emit(self.busy)

    def action(self, origin, kind, *args):
        if not self.connected or self.busy:
            return False
        self.action_origin = origin
        self.busy_changed.emit(True)
        origin.action_started(kind)
        self.backend.submit(kind, *args)
        return True

    def action_finished(self, success, message):
        origin, self.action_origin = self.action_origin, None
        self.busy_changed.emit(self.busy)
        if origin is not None:
            origin.action_finished(success, message)

    def task(self, function, callback):
        """Internal work only; never accepts executable content from the IPC client."""
        self.backend.submit("_task", callback, function)

    def task_finished(self, callback, success, result):
        if not self.stopping:
            callback(success, result)

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        self.busy_changed.emit(True)
        self.browser_tabs.close()
        self.backend.stop()
        self._await_stop()

    def _await_stop(self):
        if self.backend.isRunning():
            QTimer.singleShot(50, self._await_stop)
        else:
            self.stopped.emit()
