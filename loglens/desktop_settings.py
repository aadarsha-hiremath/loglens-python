"""Controls for workspace, performance and accessibility."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from .desktop_data import COLUMNS
from .desktop_style import button, label, panel
from .explorer import HEADERS


class Settings(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        self.controls = {}
        for heading, spec in (
            (
                "Appearance",
                (
                    ("theme", "Theme", ("Dark", "Light", "System")),
                    ("font_size", "Font size", (9, 16)),
                    ("density", "Table density", ("Compact", "Balanced", "Comfortable")),
                    ("top", "Top results", (1, 100)),
                ),
            ),
            (
                "Performance & accessibility",
                (
                    ("motion", "Transition quality", ("Auto", "Balanced", "High", "Off")),
                    ("reduced", "Reduced motion", None),
                    ("smooth_scroll", "Pixel scrolling", None),
                ),
            ),
        ):
            card, box = panel(heading)
            form = QFormLayout()
            for key, title, values in spec:
                if values is None:
                    w = QCheckBox()
                elif isinstance(values[0], int):
                    w = QSpinBox()
                    w.setRange(*values)
                else:
                    w = QComboBox()
                    w.addItems(values)
                w.setAccessibleName(title)
                form.addRow(title, w)
                self.controls[key] = w
            box.addLayout(form)
            layout.addWidget(card)
        card, box = panel("Workspace")
        box.addWidget(
            label("Drag explorer headers to reorder columns or resize their edges.", "muted", True)
        )
        row = QHBoxLayout()
        self.columns = {}
        for key, title in zip(COLUMNS, HEADERS):
            self.columns[key] = QCheckBox(title)
            row.addWidget(self.columns[key])
        box.addLayout(row)
        foot = QHBoxLayout()
        self.history = button("Clear recent files…")
        self.reset = button("Reset all settings…")
        foot.addWidget(self.history)
        foot.addWidget(self.reset)
        foot.addStretch()
        box.addLayout(foot)
        layout.addWidget(card)
        layout.addStretch()

    def restore(self, prefs):
        for key, w in self.controls.items():
            val = getattr(prefs, key)
            if isinstance(w, QComboBox):
                w.setCurrentText(val)
            elif isinstance(w, QSpinBox):
                w.setValue(val)
            else:
                w.setChecked(val)
        for c, w in self.columns.items():
            w.setChecked(c in prefs.columns)
