"""Compact keyboard-friendly popup for choosing a manual window icon."""
import time

from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QScroller, QScrollerProperties, QToolButton,
                               QVBoxLayout, QWidget)


class ScrollIconButton(QToolButton):
    """Let a finger or mouse drag scroll from directly on an icon tile."""

    def __init__(self, scroll_area):
        super().__init__()
        self.scroll_area = scroll_area
        self.press_global = None
        self.press_scroll = 0
        self.last_motion = 0.0
        self.velocity = 0.0
        self.last_y = 0
        self.scrolling = False
        self.scroll_started = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.scroll_area.fling_animation.stop()
            self.press_global = event.globalPosition().toPoint()
            self.press_scroll = self.scroll_area.verticalScrollBar().value()
            self.last_y = self.press_global.y()
            self.last_motion = time.monotonic()
            self.velocity = 0.0
            self.scrolling = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_global is not None:
            now = time.monotonic()
            y = event.globalPosition().toPoint().y()
            distance = self.press_global.y() - y
            if abs(distance) >= max(8, QApplication.startDragDistance()):
                if not self.scrolling and self.scroll_started is not None:
                    self.scroll_started()
                self.scrolling = True
            if self.scrolling:
                self.setDown(False)
                self.scroll_area.verticalScrollBar().setValue(self.press_scroll + distance)
                elapsed = max(0.015, now - self.last_motion)
                self.velocity = (self.last_y - y) / elapsed
                self.last_motion = now
                self.last_y = y
                event.accept()
                return
        super().mouseMoveEvent(event)

    def hitButton(self, position):
        return not self.scrolling and super().hitButton(position)

    def mouseReleaseEvent(self, event):
        if self.scrolling and time.monotonic() - self.last_motion < 0.14:
            bar = self.scroll_area.verticalScrollBar()
            max_extra = self.scroll_area.viewport().height() * 1.5
            extra = max(-max_extra, min(max_extra, self.velocity * 0.22))
            target = max(bar.minimum(), min(bar.maximum(), round(bar.value() + extra)))
            if abs(target - bar.value()) >= 8:
                animation = self.scroll_area.fling_animation
                animation.setStartValue(bar.value())
                animation.setEndValue(target)
                animation.start()
        super().mouseReleaseEvent(event)
        self.press_global = None
        self.scrolling = False


class IconPicker(QDialog):
    selected = Signal(str)
    reset_requested = Signal()

    def __init__(self, catalog, icons, palette, settings, parent=None, usage=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.catalog = catalog
        self.icons = icons
        self.palette = palette
        self.settings = settings
        self.usage = usage
        self.entries = ()
        self.current = 0
        self.last_tap = None
        self._moving_highlight = False
        self.preview_queue = []
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(4)
        self.preview_timer.timeout.connect(self.load_previews)
        s = settings.scaled
        self.setObjectName("niridashboard-icon-picker")
        self.setFixedSize(s(320), s(300))
        self.setStyleSheet(f"""
            #niridashboard-icon-picker {{ background: {palette.dashboard_background}; border: {s(1)}px solid {palette.node_border}; border-radius: {s(12)}px; }}
            QLineEdit {{ background: {palette.node_background}; color: {palette.primary_text}; border: {s(1)}px solid {palette.node_border}; border-radius: {s(7)}px; padding: {s(8)}px {s(10)}px; font-size: {s(settings.normal_text_size)}px; }}
            QToolButton {{ color: {palette.primary_text}; background: transparent; border: {s(1)}px solid transparent; border-radius: {s(8)}px; padding: {s(6)}px; font-size: {s(settings.window_title_size)}px; }}
            QToolButton:focus, QToolButton[selected="true"] {{ background: {palette.focused_background}; border-color: {palette.focused_border}; }}
            QPushButton {{ color: {palette.secondary_text}; background: transparent; border: 0; padding: {s(6)}px; font-size: {s(settings.normal_text_size)}px; }}
            QPushButton:hover {{ color: {palette.primary_text}; }}
            QScrollBar:vertical {{ width: {s(12)}px; background: transparent; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {palette.node_border}; border-radius: {s(6)}px; min-height: {s(36)}px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(8), s(8), s(8), s(8))
        layout.setSpacing(s(6))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search icons…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(s(38))
        self.search.textChanged.connect(self.update_results)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(s(4))
        self.grid.setVerticalSpacing(s(6))
        self.results = QScrollArea()
        self.results.setWidgetResizable(True)
        self.results.setFrameShape(QScrollArea.Shape.NoFrame)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setWidget(self.grid_widget)
        self.results.setFixedHeight(s(190))
        self.results.fling_animation = QPropertyAnimation(
            self.results.verticalScrollBar(), b"value", self.results)
        self.results.fling_animation.setDuration(340)
        self.results.fling_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.results.viewport().setAttribute(
            Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        scroller = QScroller.scroller(self.results.viewport())
        properties = scroller.scrollerProperties()
        properties.setScrollMetric(QScrollerProperties.ScrollMetric.MaximumVelocity, 0.45)
        properties.setScrollMetric(
            QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
            QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        scroller.setScrollerProperties(properties)
        QScroller.grabGesture(self.results.viewport(),
                              QScroller.ScrollerGestureType.TouchGesture)
        self.results.verticalScrollBar().valueChanged.connect(self._scrolled)
        layout.addWidget(self.results)
        footer = QHBoxLayout()
        self.empty = QLabel("No matching icons")
        self.empty.setStyleSheet(
            f"color: {palette.secondary_text}; padding: {s(8)}px;")
        self.empty.hide()
        footer.addWidget(self.empty)
        footer.addStretch(1)
        reset = QPushButton("Reset to default icon")
        reset.setMinimumHeight(s(38))
        reset.clicked.connect(self.reset_requested)
        reset.clicked.connect(self.reject)
        footer.addWidget(reset)
        self.update_button = QToolButton()
        self.update_button.setText("↻")
        self.update_button.setToolTip("Update icons from assets/icons")
        self.update_button.setFixedSize(s(38), s(38))
        self.update_button.clicked.connect(self.refresh_icons)
        footer.addWidget(self.update_button)
        layout.addLayout(footer)
        self.update_results()

    def refresh_icons(self):
        self.catalog.refresh_assets()
        self.update_results()
        self.search.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_at(self, position):
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            position.setX(max(area.left(), min(position.x(), area.right() - self.width() + 1)))
            position.setY(max(area.top(), min(position.y(), area.bottom() - self.height() + 1)))
        self.move(position)
        self.show()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)
        if self.preview_queue:
            self.preview_timer.start()

    def update_results(self):
        self.preview_timer.stop()
        self.results.fling_animation.stop()
        self.last_tap = None
        self._moving_highlight = True
        self.preview_queue.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search.text()
        self.entries = self.catalog.search(query)
        if not query.strip() and self.usage is not None:
            self.entries = self.usage.favorites_first(self.entries)
        self.current = 0
        self.empty.setVisible(not self.entries)
        icon_size = self.settings.scaled(36)
        blank = QPixmap(icon_size, icon_size)
        blank.fill(Qt.GlobalColor.transparent)
        placeholder = QIcon(blank)
        for index, entry in enumerate(self.entries):
            button = ScrollIconButton(self.results)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setText(entry.name)
            button.setIcon(placeholder)
            button.setIconSize(QSize(icon_size, icon_size))
            button.setFixedSize(self.settings.scaled(92),
                                self.settings.scaled(70))
            button.scroll_started = self._scrolled
            button.clicked.connect(lambda _checked=False, icon_id=entry.id: self.tap_icon(icon_id))
            self.grid.addWidget(button, index // 3, index % 3)
            self.preview_queue.append((button, entry.id, icon_size))
        self._highlight()
        self._moving_highlight = False
        if self.isVisible() and self.preview_queue:
            self.preview_timer.start()

    def load_previews(self):
        for _ in range(min(2, len(self.preview_queue))):
            button, icon_id, icon_size = self.preview_queue.pop(0)
            button.setIcon(self.icons.catalog_icon_for_size(icon_id, icon_size))
        if not self.preview_queue:
            self.preview_timer.stop()

    def choose(self, icon_id):
        self.selected.emit(icon_id)
        self.accept()

    def tap_icon(self, icon_id):
        now = time.monotonic()
        if (self.last_tap is not None and self.last_tap[0] == icon_id
                and now - self.last_tap[1] <= QApplication.doubleClickInterval() / 1000):
            self.choose(icon_id)
            return
        self.last_tap = (icon_id, now)
        self.current = next(index for index, entry in enumerate(self.entries)
                            if entry.id == icon_id)
        self._highlight()

    def _scrolled(self, *_args):
        if self._moving_highlight:
            return
        self.last_tap = None
        if self.current is not None:
            self.current = None
            self._highlight()

    def _highlight(self):
        self._moving_highlight = True
        for index in range(self.grid.count()):
            widget = self.grid.itemAt(index).widget()
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            widget.setProperty("selected", index == self.current)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            if index == self.current:
                margin = self.settings.scaled(4)
                self.results.ensureWidgetVisible(widget, margin, margin)
        self._moving_highlight = False

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.entries:
                self.choose(self.entries[self.current if self.current is not None else 0].id)
                return True
            shifts = {Qt.Key.Key_Left: -1, Qt.Key.Key_Up: -3,
                      Qt.Key.Key_Right: 1, Qt.Key.Key_Down: 3}
            if key in shifts and self.entries:
                self.current = max(0, min(len(self.entries) - 1,
                                          (self.current if self.current is not None else 0) + shifts[key]))
                self._highlight()
                return True
        return super().eventFilter(watched, event)
