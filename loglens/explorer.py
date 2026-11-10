"""Virtual table, filter controls and a full-record inspector."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QScrollArea,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .desktop_data import COLUMNS, Scope
from .desktop_style import DARK, button, label, panel
from .parsing import LEVELS
from .reporting import visible_text

HEADERS = ("Time (UTC)", "Severity", "Service", "Message")


class Rows(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def replace(self, rows):
        self.beginResetModel()
        self.rows = [
            (
                line,
                stamp.replace("T", " ").replace(".000000Z", "").removesuffix("Z"),
                level,
                service if service.isprintable() else visible_text(service),
                msg if msg.isprintable() else visible_text(msg),
            )
            for line, stamp, level, service, msg in rows
        ]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]

    def data(self, index, role):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.rows[index.row()][index.column() + 1]


class Badge(QStyledItemDelegate):
    colors = DARK

    def paint(self, painter, option, index):
        text = index.data()
        if text not in LEVELS:
            return super().paint(painter, option, index)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(self.colors["active"]))
        color = QColor(self.colors[text.lower()])
        tint = QColor(color)
        tint.setAlpha(34)
        rect = QRectF(
            option.rect.x() + 6,
            option.rect.center().y() - 10,
            option.fontMetrics.horizontalAdvance(text) + 16,
            21,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class Explorer(QWidget):
    def __init__(self):
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search messages…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search messages")
        self.case = QCheckBox("Match case")
        self.filters = button("Filters")
        self.filters.setCheckable(True)
        self.clear = button("Clear")
        for w in (self.search, self.case, self.filters, self.clear):
            tools.addWidget(w)
        box.addLayout(tools)
        self.advanced, inner = panel()
        inner.addWidget(label("FILTERS", "eyebrow"))
        inner.addWidget(label("Severity", "section"))
        self.levels = {}
        for lvl in LEVELS:
            self.levels[lvl] = QCheckBox(lvl)
            inner.addWidget(self.levels[lvl])
        self.fields = {}
        for k, title, hint in (
            ("service", "Service", "Comma-separated names"),
            ("since", "From · inclusive", "YYYY-MM-DDThh:mm:ssZ"),
            ("until", "To · inclusive", "YYYY-MM-DDThh:mm:ssZ"),
        ):
            inner.addWidget(label(title, "muted"))
            self.fields[k] = QLineEdit(placeholderText=hint)
            self.fields[k].setAccessibleName(title)
            inner.addWidget(self.fields[k])
        self.apply = button("Apply filters", role="primary")
        inner.addWidget(self.apply)
        inner.addSpacing(8)
        inner.addWidget(label("Saved filters", "section"))
        self.preset = QComboBox()
        self.preset.setAccessibleName("Saved filter presets")
        self.save_preset = button("Save preset…")
        self.delete_preset = button("Delete preset")
        for control in (self.preset, self.save_preset, self.delete_preset):
            inner.addWidget(control)
        inner.addStretch()
        drawer = QScrollArea()
        drawer.setWidgetResizable(True)
        drawer.setWidget(self.advanced)
        drawer.setMinimumWidth(172)
        drawer.setMaximumWidth(195)
        self.advanced = drawer
        heading = QHBoxLayout()
        self.scope_label = label("All valid records", "muted")
        self.scope_label.setSizePolicy(self.search.sizePolicy())
        heading.addWidget(self.scope_label, 1)
        self.selected_export = button("Export selected…")
        self.inspect = button("Inspector")
        self.inspect.setCheckable(True)
        heading.addWidget(self.selected_export)
        heading.addWidget(self.inspect)
        box.addLayout(heading)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.table = QTableView()
        self.model = Rows(self.table)
        self.table.setModel(self.model)
        self.table.setAccessibleName("Matching log records")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setMinimumSectionSize(50)
        self.badge = Badge(self.table)
        self.table.setItemDelegateForColumn(1, self.badge)
        self.split.addWidget(self.table)
        self.detail, detail = panel("Record inspector")
        self.detail.setMinimumWidth(200)
        self.identity = label("Select a record", "muted", True)
        detail.addWidget(self.identity)
        self.details = label("", wrap=True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail.addWidget(self.details)
        self.message_title = label("MESSAGE", "eyebrow")
        detail.addWidget(self.message_title)
        self.field = QComboBox()
        self.field.addItems(["Message", "Full service name"])
        self.field.setAccessibleName("Inspector text field")
        detail.addWidget(self.field)
        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("Select a row to read its full message.")
        self.message.setReadOnly(True)
        self.message.setAccessibleName("Complete record message")
        detail.addWidget(self.message, 1)
        chunks = QHBoxLayout()
        self.back = button("‹")
        self.forward = button("›")
        self.part = label("", "muted")
        for w in (self.back, self.part, self.forward):
            chunks.addWidget(w)
        detail.addLayout(chunks)
        copy = QHBoxLayout()
        self.copy_record = button("Copy record")
        self.copy_msg = button("Copy message")
        copy.addWidget(self.copy_record)
        copy.addWidget(self.copy_msg)
        detail.addLayout(copy)
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        middle = QHBoxLayout()
        middle.addWidget(self.advanced)
        middle.addWidget(self.split, 1)
        box.addLayout(middle, 1)
        pager = QHBoxLayout()
        self.count = label("0 matches", "muted")
        pager.addWidget(self.count, 1)
        self.prev = button("‹")
        self.prev.setAccessibleName("Previous page")
        self.next = button("›")
        self.next.setAccessibleName("Next page")
        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.setKeyboardTracking(False)
        self.page.setAccessibleName("Current page")
        self.pages = label("of 1", "muted")
        self.size = QComboBox()
        self.size.addItems(["50", "100", "250", "500"])
        self.size.setAccessibleName("Rows per page")
        for w in (self.prev, self.page, self.pages, self.next, label("Rows", "muted"), self.size):
            pager.addWidget(w)
        box.addLayout(pager)
        self.record = None
        self.chunk = 0
        self.back.clicked.connect(lambda: self.show_chunk(self.chunk - 1))
        self.forward.clicked.connect(lambda: self.show_chunk(self.chunk + 1))
        self.field.currentIndexChanged.connect(lambda _: self.show_chunk(0))
        self.set_record(None)

    def scope(self):
        return Scope(
            ",".join(k for k, b in self.levels.items() if b.isChecked()),
            *(self.fields[k].text().strip() for k in ("service", "since", "until")),
            self.search.text(),
            self.case.isChecked(),
        )

    def set_scope(self, scope):
        self.search.setText(scope.search)
        self.case.setChecked(scope.sensitive)
        for lvl, b in self.levels.items():
            b.setChecked(lvl in scope.level.split(","))
        for k, w in self.fields.items():
            w.setText(getattr(scope, k))

    def set_record(self, record):
        self.record = record
        long_service = bool(record and len(record["service"]) > 80)
        self.field.setCurrentIndex(0)
        self.field.setVisible(long_service)
        self.message_title.setVisible(not long_service)
        self.identity.setText(f"Source line {record['line']:,}" if record else "Select a record")
        if record:
            stamp = record["timestamp"].replace(".000000Z", "Z")
            service = record["service"][:80] + ("…" if long_service else "")
            self.details.setText(f"UTC     {stamp}\nLevel    {record['level']}\nService  {service}")
            self.details.setToolTip(record["service"][:4096])
        else:
            self.details.clear()
        self.copy_msg.setEnabled(bool(record))
        self.copy_record.setEnabled(bool(record))
        self.show_chunk(0)

    def show_chunk(self, index):
        key = "service" if self.field.currentIndex() == 1 else "message"
        msg = self.record[key] if self.record else ""
        parts = max(1, (len(msg) + 8191) // 8192)
        self.chunk = max(0, min(index, parts - 1))
        self.message.setPlainText(msg[self.chunk * 8192 : (self.chunk + 1) * 8192])
        for w in (self.back, self.part, self.forward):
            w.setVisible(parts > 1)
        self.part.setText(f"Part {self.chunk + 1} of {parts}")
        self.back.setEnabled(self.chunk > 0)
        self.forward.setEnabled(self.chunk + 1 < parts)
