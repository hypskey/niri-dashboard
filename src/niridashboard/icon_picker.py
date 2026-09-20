"""Compact keyboard-friendly popup for choosing a manual window icon."""
from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget


class IconPicker(QDialog):
    selected = Signal(str)
    reset_requested = Signal()

    def __init__(self, catalog, icons, palette, settings, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.catalog = catalog
        self.icons = icons
        self.palette = palette
        self.settings = settings
        self.entries = ()
        self.current = 0
        self.setObjectName("niridashboard-icon-picker")
        self.setFixedSize(320, 300)
        self.setStyleSheet(f"""
            #niridashboard-icon-picker {{ background: {palette.dashboard_background}; border: 1px solid {palette.node_border}; border-radius: 12px; }}
            QLineEdit {{ background: {palette.node_background}; color: {palette.primary_text}; border: 1px solid {palette.node_border}; border-radius: 7px; padding: 8px 10px; }}
            QToolButton {{ color: {palette.primary_text}; background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px; }}
            QToolButton:focus, QToolButton:hover, QToolButton[selected="true"] {{ background: {palette.focused_background}; border-color: {palette.focused_border}; }}
            QPushButton {{ color: {palette.secondary_text}; background: transparent; border: 0; padding: 6px; }}
            QPushButton:hover {{ color: {palette.primary_text}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search icons…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.update_results)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        self.results = QScrollArea()
        self.results.setWidgetResizable(True)
        self.results.setFrameShape(QScrollArea.Shape.NoFrame)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setWidget(self.grid_widget)
        self.results.setFixedHeight(204)
        layout.addWidget(self.results)
        footer = QHBoxLayout()
        self.empty = QLabel("No matching icons")
        self.empty.setStyleSheet(f"color: {palette.secondary_text}; padding: 8px;")
        self.empty.hide()
        footer.addWidget(self.empty)
        footer.addStretch(1)
        reset = QPushButton("Reset to default icon")
        reset.clicked.connect(self.reset_requested)
        reset.clicked.connect(self.reject)
        footer.addWidget(reset)
        layout.addLayout(footer)
        self.update_results()

    def open_at(self, position):
        self.move(position)
        self.show()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)

    def update_results(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.entries = self.catalog.search(self.search.text())
        self.current = 0
        self.empty.setVisible(not self.entries)
        for index, entry in enumerate(self.entries):
            button = QToolButton()
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setText(entry.name)
            button.setIcon(self.icons.catalog_icon_for_size(entry.id, 36))
            button.setIconSize(QSize(36, 36))
            button.setFixedSize(94, 64)
            button.clicked.connect(lambda _checked=False, icon_id=entry.id: self.choose(icon_id))
            self.grid.addWidget(button, index // 3, index % 3)
        self._highlight()

    def choose(self, icon_id):
        self.selected.emit(icon_id)
        self.accept()

    def _highlight(self):
        for index in range(self.grid.count()):
            widget = self.grid.itemAt(index).widget()
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            widget.setProperty("selected", index == self.current)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            if index == self.current:
                self.results.ensureWidgetVisible(widget, 4, 4)

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.entries:
                self.choose(self.entries[self.current].id)
                return True
            shifts = {Qt.Key.Key_Left: -1, Qt.Key.Key_Up: -3,
                      Qt.Key.Key_Right: 1, Qt.Key.Key_Down: 3}
            if key in shifts and self.entries:
                self.current = max(0, min(len(self.entries) - 1, self.current + shifts[key]))
                self._highlight()
                return True
        return super().eventFilter(watched, event)
