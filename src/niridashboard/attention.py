"""Local desktop-notification attention cues for identifiable open windows."""
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import time

from PySide6.QtCore import QObject, QProcess, QStandardPaths, QTimer, Signal
try:
    from PySide6.QtDBus import QDBusConnection
except ImportError:  # Desktop notifications still work without QtDBus PID lookup.
    QDBusConnection = None

from .icons import is_browser_app


ATTENTION_MS = 9000
WINDOW_COOLDOWN_SECONDS = 75
CODEX_COOLDOWN_SECONDS = 12
GLOBAL_COOLDOWN_SECONDS = 6
_MONITOR_RULE = ("type='method_call',interface='org.freedesktop.Notifications',"
                 "member='Notify',path='/org/freedesktop/Notifications'")
_STRING_LINE = re.compile(r'^\s+string\s+("(?:\\.|[^"\\])*")\s*$')
_SENDER = re.compile(r"\bsender=(:[\w.]+)")
_CODEX_REQUEST = re.compile(r"^(approval requested|action required|input required)\b",
                            re.IGNORECASE)

# A notification is the trigger. Hostnames identify the browser window; changing
# a tab title or visiting one of these sites never creates an attention cue.
_SITES = (
    ("Google Chat", ("chat.google.com",), ("google chat", "chat.google.com")),
    ("Gmail", ("mail.google.com",), ("gmail", "mail.google.com")),
    ("Proton Mail", ("mail.proton.me", "proton.me"),
     ("proton mail", "protonmail", "mail.proton.me")),
    ("WhatsApp", ("web.whatsapp.com",), ("whatsapp", "web.whatsapp.com")),
    ("ChatGPT", ("chatgpt.com",), ("chatgpt", "chatgpt.com")),
)
_NATIVE = (
    ("Discord", ("discord",), ("discord",)),
    ("Thunderbird", ("thunderbird",), ("thunderbird",)),
    ("Mail", ("evolution",), ("evolution",)),
    ("Proton Mail", ("protonmail", "proton-mail"),
     ("proton mail", "protonmail")),
    ("Signal", ("signal",), ("signal",)),
)
_TERMINALS = ("kitty", "alacritty", "wezterm", "foot", "gnome-terminal")


@dataclass(frozen=True)
class AttentionCue:
    window_id: int
    label: str
    number: int
    hostname: str = ""
    allow_focused: bool = False


def _mentions(text, markers):
    return any(re.search(r"(?<![a-z0-9])" + re.escape(marker) +
                         r"(?![a-z0-9])", text) for marker in markers)


def _unique(windows):
    return windows[0] if len(windows) == 1 else None


def _codex_window(window):
    return ("codex" in (window.get("title") or "").casefold() or
            (window.get("icon_override") or "").startswith("codex-pet-"))


def terminal_runs_codex(pid, proc_root=Path("/proc")):
    """Inspect a terminal's local descendants only when an alert arrives."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    pending = [(pid, 0)]
    seen = set()
    while pending and len(seen) < 32:
        current, depth = pending.pop(0)
        if current in seen or depth > 3:
            continue
        seen.add(current)
        process = proc_root / str(current)
        try:
            name = (process / "comm").read_text().strip().casefold()
            if name == "codex":
                return True
            if depth < 3:
                children = (process / "task" / str(current) / "children").read_text()
                pending.extend((int(child), depth + 1)
                               for child in children.split() if child.isdigit())
        except (OSError, UnicodeError):
            continue
    return False


def resolve_notification(app_name, app_icon, summary, windows, sender_pid=None):
    """Return one (window, label), or None when attribution is uncertain."""
    source = f"{app_name} {app_icon}".casefold()
    description = f"{source} {summary}".casefold()
    browser_windows = [w for w in windows if is_browser_app(w.get("app_id"))]

    site_mentioned = False
    for label, hosts, markers in _SITES:
        if not _mentions(description, markers):
            continue
        site_mentioned = True
        match = _unique([
            w for w in browser_windows
            if any((w.get("browser_hostname") or "").casefold() == host or
                   (w.get("browser_hostname") or "").casefold().endswith("." + host)
                   for host in hosts)])
        if match is None and _mentions(source, markers):
            # With only one browser window, the notification's application
            # identity is enough even when a background tab sent the alert.
            match = _unique(browser_windows)
        if match is not None and not match.get("is_focused"):
            return match, label
    if site_mentioned:
        return None

    # A generic browser notification is safe to attribute only if exactly one
    # browser window is open and its active site is in the small attention set.
    if is_browser_app(source):
        match = _unique(browser_windows)
        if match is not None and not match.get("is_focused"):
            hostname = (match.get("browser_hostname") or "").casefold()
            for label, hosts, _markers in _SITES:
                if any(hostname == host or hostname.endswith("." + host)
                       for host in hosts):
                    return match, label
        return None

    terminals = [w for w in windows
                 if any(term in (w.get("app_id") or "").casefold()
                        for term in _TERMINALS)]
    codex_windows = [w for w in terminals
                     if _codex_window(w) or terminal_runs_codex(w.get("pid"))]
    if _mentions(source, ("codex",)):
        match = _unique(codex_windows)
        return (match, "Codex") if match is not None else None

    # Kitty reports Codex CLI alerts under its own application name. Match
    # the D-Bus sender process to Niri's window PID, then inspect that
    # terminal's children for Codex. An explicit icon/title remains a fallback.
    if any(_mentions(source, (term,)) for term in _TERMINALS):
        sender_match = _unique([
            w for w in terminals if sender_pid is not None and
            w.get("pid") == sender_pid])
        if sender_match is not None:
            if sender_match in codex_windows:
                return sender_match, "Codex"
            return None
        if sender_pid is None and _CODEX_REQUEST.search(summary or ""):
            match = _unique(codex_windows)
            if match is not None:
                return match, "Codex"

    for label, app_markers, source_markers in _NATIVE:
        if _mentions(source, source_markers):
            match = _unique([
                w for w in windows
                if _mentions((w.get("app_id") or "").casefold(), app_markers)])
            return (match, label) if match is not None and not match.get("is_focused") else None

    for terminal in _TERMINALS:
        if _mentions(source, (terminal,)):
            match = _unique([
                w for w in windows
                if terminal in (w.get("app_id") or "").casefold()])
            return (match, "Terminal") if match is not None and not match.get("is_focused") else None
    return None


class NotificationListener(QObject):
    """Read Notify calls from the local session bus without owning the daemon."""
    notification = Signal(str, str, str, object)  # application, icon, summary, sender PID

    def __init__(self, parent=None, enabled=True):
        super().__init__(parent)
        self.buffer = ""
        self.fields = None
        self.sender = None
        self.enabled = enabled
        self.executable = QStandardPaths.findExecutable("dbus-monitor")
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._finished)
        self.retry = QTimer(self)
        self.retry.setSingleShot(True)
        self.retry.setInterval(10000)
        self.retry.timeout.connect(self.start)
        if enabled and self.executable:
            self.start()
        elif enabled:
            logging.getLogger(__name__).warning(
                "dbus-monitor is unavailable; pet attention is disabled")

    def start(self):
        if self.enabled and self.executable and self.process.state() == QProcess.ProcessState.NotRunning:
            self.process.start(self.executable, ["--session", _MONITOR_RULE])

    def _finished(self, *_args):
        if self.enabled:
            self.retry.start()

    def _read(self):
        self.feed(bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace"))

    def feed(self, text):
        """Consume complete monitor lines; bounded because titles can be large."""
        self.buffer += text
        if len(self.buffer) > 16384:
            self.buffer = ""
            self.fields = None
            return
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.startswith("method call "):
                self.fields = ([] if "interface=org.freedesktop.Notifications; member=Notify"
                               in line else None)
                match = _SENDER.search(line)
                self.sender = match[1] if match is not None else None
                continue
            if self.fields is None:
                continue
            match = _STRING_LINE.match(line)
            if match is None:
                continue
            try:
                value = json.loads(match[1])
            except (ValueError, TypeError):
                self.fields = None
                continue
            self.fields.append(value[:256])
            if len(self.fields) == 3:
                self.notification.emit(*self.fields, self._sender_pid())
                self.fields = None

    def _sender_pid(self):
        if not self.enabled or not self.sender or QDBusConnection is None:
            return None
        interface = QDBusConnection.sessionBus().interface()
        if interface is None:
            return None
        reply = interface.servicePid(self.sender)
        return int(reply.value()) if reply.isValid() else None

    def close(self):
        self.enabled = False
        self.retry.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(250):
                self.process.kill()
                self.process.waitForFinished(250)


class AttentionManager(QObject):
    changed = Signal(object)

    def __init__(self, parent=None, enabled=True):
        super().__init__(parent)
        self.windows = []
        self.hints = {}
        self.current = None
        self.last_by_window = {}
        self.last_global = float("-inf")
        self.last_event = None
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.setInterval(ATTENTION_MS)
        self.dismiss_timer.timeout.connect(self.clear)
        self.listener = NotificationListener(self, enabled)
        self.listener.notification.connect(self.receive_notification)

    def update_state(self, data, hints):
        self.windows = list(data["windows"])
        self.hints = dict(hints)
        alive = {w["id"] for w in self.windows}
        self.last_by_window = {wid: when for wid, when in self.last_by_window.items()
                               if wid in alive}
        if self.current is None:
            return
        window = next((w for w in self.windows if w["id"] == self.current.window_id), None)
        if (window is None or
                (window.get("is_focused") and not self.current.allow_focused) or
                self.current.window_id not in self.hints or
                (self.current.hostname and
                 window.get("browser_hostname") != self.current.hostname)):
            self.clear()
        elif self.hints[self.current.window_id] != self.current.number:
            self.current = AttentionCue(self.current.window_id, self.current.label,
                                        self.hints[self.current.window_id],
                                        self.current.hostname,
                                        self.current.allow_focused)
            self.changed.emit(self.current)

    def receive_notification(self, app_name, app_icon, summary, sender_pid=None, now=None):
        now = time.monotonic() if now is None else now
        self.last_event = {"app": app_name[:64], "sender_pid": sender_pid}
        if self.current is not None or now - self.last_global < GLOBAL_COOLDOWN_SECONDS:
            self.last_event["result"] = "busy-or-cooldown"
            return False
        resolved = resolve_notification(app_name, app_icon, summary,
                                        self.windows, sender_pid)
        if resolved is None:
            self.last_event["result"] = "unmatched"
            return False
        window, label = resolved
        wid = window["id"]
        if wid not in self.hints:
            self.last_event["result"] = "missing-hint"
            self.last_event["window_id"] = wid
            return False
        cooldown = (CODEX_COOLDOWN_SECONDS if label == "Codex"
                    else WINDOW_COOLDOWN_SECONDS)
        if now - self.last_by_window.get(wid, float("-inf")) < cooldown:
            self.last_event["result"] = "window-cooldown"
            self.last_event["window_id"] = wid
            return False
        self.current = AttentionCue(wid, label, self.hints[wid],
                                    window.get("browser_hostname") or "",
                                    label == "Codex")
        self.last_by_window[wid] = now
        self.last_global = now
        self.last_event["result"] = "shown"
        self.last_event["window_id"] = wid
        self.dismiss_timer.start()
        self.changed.emit(self.current)
        return True

    def clear(self):
        if self.current is not None:
            self.current = None
            self.dismiss_timer.stop()
            self.changed.emit(None)

    def close(self):
        self.clear()
        self.listener.close()
