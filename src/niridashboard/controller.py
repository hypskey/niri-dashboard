"""One live model and serialized action worker shared by all presentations."""
from PySide6.QtCore import QObject, Signal, QTimer
from .backend import Backend
from .icons import Icons
from .icon_overrides import IconOverrides
from .icon_usage import IconUsage
from .dashboard_nodes import dashboard_nodes
from .browser_tabs import BrowserTabs
from .attention import AttentionManager
from .appearance import AppearanceProvider
from .hints import HintAssignments
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
        self.hint_assignments = HintAssignments()
        self.icon_overrides = IconOverrides(enabled=not demo, parent=self)
        self.icon_usage = IconUsage(enabled=not demo)
        self.appearance.changed.connect(self._appearance_changed)
        self.icon_overrides.changed.connect(self._publish_state)
        self.latest = None
        self.raw = None
        self.browser_tabs = BrowserTabs(self, enabled=not demo)
        self.browser_tabs.changed.connect(self._publish_state)
        self.attention = AttentionManager(self, enabled=not demo)
        self.connected = False
        self.health_message = "Starting…"
        self.action_origin = None
        self.pending_force_close = None
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
        self.icon_overrides.prune(w["id"] for w in data["windows"] if not niri.is_overlay(w))
        self._publish_state()
        self.raw_state.emit(data)

    def _publish_state(self):
        if self.raw is None:
            return
        windows = []
        for window in self.raw["windows"]:
            if niri.is_overlay(window):
                continue
            decorated = self.browser_tabs.decorate(window)
            icon_override = self.icon_overrides.get(window["id"])
            if icon_override:
                decorated = dict(decorated, icon_override=icon_override)
            windows.append(decorated)
        filtered = dict(self.raw, windows=windows)
        self.hint_assignments.update(self._hint_order(filtered))
        self.attention.update_state(filtered, self.hint_assignments.by_window)
        if filtered != self.latest:
            self.latest = filtered
            self.state.emit(filtered)

    @staticmethod
    def _hint_order(data):
        """Match the graph's monitor/workspace/window order for every view."""
        if "outputs" not in data or "workspaces" not in data:
            return [window["id"] for window in data["windows"]]
        outputs = data["outputs"]
        names = sorted((name for name, output in outputs.items() if output.get("logical")),
                       key=lambda name: (outputs[name]["logical"].get("x", 0),
                                         outputs[name]["logical"].get("y", 0)))
        for workspace in data["workspaces"]:
            if workspace.get("output") not in names:
                names.append(workspace.get("output"))
        result = []
        for name in names:
            workspaces = sorted((workspace for workspace in data["workspaces"]
                                 if workspace.get("output") == name), key=lambda workspace: workspace["idx"])
            for workspace in workspaces:
                result.extend(member["id"] for node in dashboard_nodes(
                    window for window in data["windows"]
                    if window.get("workspace_id") == workspace["id"])
                    for member in node.members)
        return result

    def receive_health(self, connected, message):
        self.connected, self.health_message = connected, message
        self.health.emit(connected, message)

    def set_transition(self, value):
        self.transition = value
        self.busy_changed.emit(self.busy)

    def action(self, origin, kind, *args):
        if not self.connected or self.stopping:
            return False
        if self.busy:
            if kind == "force_close" and self.action_origin is not None:
                self.pending_force_close = (origin, args)
                return True
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
        pending, self.pending_force_close = self.pending_force_close, None
        if pending is not None:
            self.action(pending[0], "force_close", *pending[1])

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
        self.attention.close()
        self.browser_tabs.close()
        self.backend.stop()
        self._await_stop()

    def _await_stop(self):
        if self.backend.isRunning():
            QTimer.singleShot(50, self._await_stop)
        else:
            self.stopped.emit()
