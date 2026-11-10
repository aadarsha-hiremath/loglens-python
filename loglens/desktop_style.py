"""Qt palette and reusable controls for the desktop workspace."""

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

DARK = dict(
    bg="#101622",
    rail="#0d1320",
    card="#192334",
    inset="#121c2a",
    edge="#303e52",
    text="#ecf1fb",
    muted="#afbdd1",
    accent="#aba5ff",
    active="#35315b",
    action="#5950c7",
    cyan="#55d7d3",
    debug="#b9a5fb",
    info="#70c7ff",
    warning="#f2c16b",
    error="#ff948e",
    critical="#fa9ac5",
)
LIGHT = dict(
    bg="#f1f4fa",
    rail="#e6ebf4",
    card="#ffffff",
    inset="#f5f7fc",
    edge="#c7d2e1",
    text="#19253a",
    muted="#495b73",
    accent="#5046a8",
    active="#e1def9",
    action="#5549ba",
    cyan="#117873",
    debug="#5940a3",
    info="#1a6295",
    warning="#80550a",
    error="#a43432",
    critical="#982859",
)


def colors_for(prefs, app):
    dark = prefs.theme == "Dark" or (
        prefs.theme == "System" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )
    return DARK if dark else LIGHT


def stylesheet(c):
    return (
        """
 QWidget {color:%(text)s; background:%(bg)s;}
 QFrame#rail {background:%(rail)s; border-right:1px solid %(edge)s;}
 QLabel, QCheckBox { background:transparent; }
 QLabel#brand {font-size:22px;font-weight:700;}
 QLabel#title {font-size:26px;font-weight:700;}
 QLabel#section {font-size:16px;font-weight:650;}
 QLabel#number {font-size:30px;font-weight:700;}
 QLabel#muted,QLabel#eyebrow {color:%(muted)s;}
 QLabel#eyebrow {font-size:11px;font-weight:650;letter-spacing:1px;}
 QFrame#card, QFrame#bar {background:%(card)s;border:1px solid %(edge)s;border-radius:8px;}
 QFrame#card QWidget, QFrame#bar QWidget {background:transparent;}
 QPushButton,QToolButton,QComboBox,QSpinBox,QLineEdit {background:%(inset)s;color:%(text)s;
  border:1px solid %(edge)s;border-radius:5px;padding:5px 9px;min-height:18px;}
 QPushButton:hover,QToolButton:hover,QComboBox:hover {border-color:%(accent)s;}
 QPushButton:focus,QLineEdit:focus,QComboBox:focus,QToolButton:focus,QSpinBox:focus,QTableView:focus,QPlainTextEdit:focus {border:1px solid %(accent)s;}
 QPushButton:disabled,QToolButton:disabled {color:%(muted)s;}
 QPushButton#primary {background:%(action)s;color:white;font-weight:650;}
 QPushButton#nav {background:transparent;border:0;text-align:left;padding:9px 12px;}
 QPushButton#nav:checked, QPushButton:checked {background:%(active)s;color:%(accent)s;}
 QPushButton#nav:hover {background:%(card)s;}
 QTreeWidget {border:none;background:%(card)s;}
 QTreeWidget::item {padding:4px;}
 QCheckBox::indicator:unchecked {width:13px;height:13px;border:1px solid %(muted)s;border-radius:3px;background:%(inset)s;}
 QScrollBar:vertical {background:%(inset)s;width:10px;margin:0;}
 QScrollBar:horizontal {background:%(inset)s;height:10px;margin:0;}
 QScrollBar::handle {background:%(edge)s;border-radius:4px;min-width:16px;min-height:16px;}
 QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;}
 QMenu,QAbstractItemView {background:%(card)s;selection-background-color:%(active)s;color:%(text)s;selection-color:%(text)s;}
 QMenu::item {padding:6px 16px;} QMenu::item:selected {background:%(active)s;}
 QTableView {background:%(inset)s;alternate-background-color:%(card)s;border:1px solid %(edge)s;
  gridline-color:%(edge)s;selection-background-color:%(active)s;selection-color:%(text)s;}
 QHeaderView::section {background:%(card)s;color:%(muted)s;padding:6px;text-align:left;border:0;border-bottom:1px solid %(edge)s;}
 QPlainTextEdit {background:%(inset)s;border:1px solid %(edge)s;border-radius:5px;padding:5px;}
 QScrollArea {border:none;} QSplitter::handle {background:%(edge)s;}
 QProgressBar {border:0;border-radius:3px;background:%(edge)s;} QProgressBar::chunk {background:%(accent)s;}
 QToolTip {background:%(card)s;color:%(text)s;border:1px solid %(edge)s;}
 """
        % c
    )


def label(text="", role="", wrap=False):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setObjectName(role)
    w.setWordWrap(wrap)
    return w


def button(text, action=None, role="", tip=""):
    b = QPushButton(text)
    b.setObjectName(role)
    if action is not None:
        b.clicked.connect(action)
    b.setToolTip(tip or text)
    return b


def panel(title=None):
    w = QFrame(objectName="card")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(15, 12, 15, 12)
    layout.setSpacing(7)
    if title:
        layout.addWidget(label(title, "section"))
    return w, layout


def icon(name, tone):
    """Small line-art mark, rendered once per palette change."""
    pix = QPixmap(48, 48)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(2, 2)
    p.setPen(
        QPen(QColor(tone), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )
    if name == "brand":
        for y in (5, 10, 15):
            p.drawPolyline(QPolygonF([QPointF(2, y + 1), QPointF(11, y + 5), QPointF(21, y)]))
    elif name == "Dashboard":
        for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 1.4, 1.4)
    elif name == "Log explorer":
        p.drawEllipse(QRectF(3, 3, 12, 12))
        p.drawLine(14, 14, 21, 21)
    elif name == "Settings":
        for i, x in enumerate((8, 16, 10)):
            y = 5 + 7 * i
            p.drawLine(3, y, 21, y)
            p.setBrush(QColor(tone))
            p.drawEllipse(QPointF(x, y), 2.1, 2.1)
    p.end()
    return QIcon(pix)
