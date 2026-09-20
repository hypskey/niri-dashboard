"""Stable shared numeric hints and an ambiguous-prefix selection state machine."""
from PySide6.QtCore import QObject, QTimer, Signal


class HintAssignments:
    def __init__(self):
        self.by_window = {}

    def update(self, ordered_window_ids):
        ordered = list(dict.fromkeys(ordered_window_ids))
        current = set(ordered)
        removed = bool(set(self.by_window) - current)
        self.by_window = {wid: hint for wid, hint in self.by_window.items() if wid in current}
        if removed:
            self.by_window = {wid: number for number, (wid, _old) in enumerate(
                sorted(self.by_window.items(), key=lambda item: item[1]), 1)}
        used = set(self.by_window.values())
        next_hint = max(used, default=0) + 1
        for window_id in ordered:
            if window_id not in self.by_window:
                self.by_window[window_id] = next_hint
                next_hint += 1
        return dict(self.by_window)


class NumericSelector(QObject):
    selected = Signal(int)
    changed = Signal(str)

    def __init__(self, timeout_ms=450, parent=None):
        super().__init__(parent)
        self.targets = {}
        self.pending = ""
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self._commit_pending)

    def update(self, assignments):
        self.targets = {str(hint): window_id for window_id, hint in assignments.items()}
        if self.pending and not any(number.startswith(self.pending) for number in self.targets):
            self.cancel_pending()
        elif self.pending:
            exact = self.targets.get(self.pending)
            longer = any(number.startswith(self.pending) and number != self.pending for number in self.targets)
            if exact is not None and not longer:
                self.timer.stop()
                self.pending = ""
                self.changed.emit("")
                self.selected.emit(exact)

    def press(self, digit):
        if digit not in "0123456789" or len(digit) != 1:
            return False
        attempted = self.pending + digit
        candidates = [number for number in self.targets if number.startswith(attempted)]
        if not candidates:
            previous = self.pending
            exact = self.targets.get(previous)
            self.cancel_pending()
            if exact is not None:
                self.selected.emit(exact)
            return self.press(digit) if previous else False
        exact = self.targets.get(attempted)
        longer = any(number != attempted for number in candidates)
        self.pending = attempted
        self.changed.emit(self.pending)
        if exact is not None and not longer:
            self.cancel_pending()
            self.selected.emit(exact)
        else:
            self.timer.start()
        return True

    def _commit_pending(self):
        window_id = self.targets.get(self.pending)
        self.pending = ""
        self.changed.emit("")
        if window_id is not None:
            self.selected.emit(window_id)

    def cancel_pending(self):
        had_pending = bool(self.pending)
        if had_pending:
            self.timer.stop()
            self.pending = ""
            self.changed.emit("")
        return had_pending
