"""Serialized worker: no compositor I/O on Qt's GUI thread."""
import copy
import queue
from PySide6.QtCore import QThread, Signal
from . import niri


class Backend(QThread):
    state = Signal(object)
    health = Signal(bool, str)
    finished_action = Signal(bool, str)
    task_finished = Signal(object, bool, object)

    def __init__(self, demo=False):
        super().__init__()
        self.commands = queue.Queue()
        self.demo = demo
        self.data = demo_state() if demo else None

    def submit(self, *command):
        self.commands.put(command)

    def stop(self):
        self.requestInterruption()
        self.commands.put(None)

    def run(self):
        last = None
        while not self.isInterruptionRequested():
            command = None
            try:
                command = self.commands.get(timeout=0.15)
            except queue.Empty:
                pass
            if self.isInterruptionRequested():
                break
            outcome = None
            task_result = None
            if command:
                kind, *args = command
                try:
                    if kind == "_task":
                        callback, function = args
                        task_result = (callback, True, function())
                    else:
                        if self.demo:
                            self.demo_action(kind, args)
                        elif kind == "move":
                            niri.insert_window(*args)
                        elif kind == "focus":
                            niri.focus_window(*args)
                        elif kind == "close":
                            niri.close_window(*args)
                        elif kind == "force_close":
                            niri.force_close_window(*args)
                        else:
                            raise ValueError(f"Unknown action: {kind}")
                        outcome = (True, {"move": "Window moved", "focus": "Window focused",
                                          "close": "Close requested",
                                          "force_close": "Window force-closed"}[kind])
                except Exception as error:
                    if kind == "_task":
                        task_result = (args[0], False, str(error))
                    else:
                        outcome = (False, str(error))
            try:
                data = copy.deepcopy(self.data) if self.demo else niri.snapshot()
                if command or data != last:
                    last = data
                    self.state.emit(data)
                self.health.emit(True, "Demo · changes stay in this preview" if self.demo else "Connected to Niri")
            except Exception as error:
                self.health.emit(False, str(error))
                if outcome and outcome[0]:
                    outcome = (False, f"Action sent, but desktop refresh failed: {error}")
                last = None
                if not command:
                    self.msleep(700)
            if outcome:
                self.finished_action.emit(*outcome)
            if task_result:
                self.task_finished.emit(*task_result)

    def demo_action(self, kind, args):
        if kind in ("close", "force_close"):
            self.data["windows"] = [w for w in self.data["windows"] if w["id"] != args[0]]
            return
        if kind == "focus":
            for w in self.data["windows"]:
                w["is_focused"] = w["id"] == args[0]
            return
        wid, workspace, anchor = args
        window = next(w for w in self.data["windows"] if w["id"] == wid)
        old = window["workspace_id"]
        peers = niri.ordered([w for w in self.data["windows"] if w["workspace_id"] == workspace and w["id"] != wid])
        index = next((i for i, w in enumerate(peers) if w["id"] == anchor), len(peers))
        peers.insert(index, window)
        window["workspace_id"] = workspace
        window["is_floating"] = False
        for i, w in enumerate(peers, 1):
            w["layout"] = {"pos_in_scrolling_layout": [i, 1]}
        if old != workspace:
            for i, w in enumerate(niri.ordered([w for w in self.data["windows"] if w["workspace_id"] == old]), 1):
                w["layout"] = {"pos_in_scrolling_layout": [i, 1]}


def demo_state():
    outputs = {name: {"model": model, "logical": {"x": i * 1920, "y": 0, "width": 1920, "height": 1080}} for i, (name, model) in enumerate([
        ("DP-1", "Main display"), ("DP-2", "Studio display"), ("HDMI-A-1", "Side display")])}
    workspaces = []
    windows = []
    apps = [("firefox", "Firefox", "Research · Niri desktop"), ("kitty", "Terminal", "~/projects/dashboard"),
            ("org.gnome.Nautilus", "Files", "Projects"), ("code", "Code", "main.py — dashboard"),
            ("spotify", "Spotify", "Focus playlist"), ("discord", "Discord", "Design studio"),
            ("org.gnome.TextEditor", "Notes", "Ideas for the week")]
    for m, name in enumerate(outputs):
        for j in range(3):
            wid = m * 3 + j + 1
            workspaces.append({"id": wid, "idx": j + 1, "name": ["Build", "Research", "Personal"][j] if m == 0 else None,
                               "output": name, "is_active": j == 0, "is_focused": m == 0 and j == 0})
            count = [3, 2, 0, 2, 1, 0, 1, 0, 2][wid - 1]
            for col in range(count):
                app, label, title = apps[(wid + col - 1) % len(apps)]
                windows.append({"id": len(windows) + 1, "app_id": app, "title": title,
                                "workspace_id": wid, "is_focused": len(windows) == 0, "is_floating": False,
                                "layout": {"pos_in_scrolling_layout": [col + 1, 1]}})
    return {"windows": windows, "workspaces": workspaces, "outputs": outputs}
