"""Qt shell, workspace navigation and preference persistence."""

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QPalette, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .dashboard import Dashboard
from .desktop_data import COLUMNS, Scope
from .desktop_jobs import Jobs
from .desktop_settings import Settings
from .desktop_style import button, colors_for, icon, label, stylesheet
from .desktop_workspace import Workspace
from .explorer import Explorer
from .preferences import Preferences, VIEWS, settings_path


class Window(Workspace, QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        QApplication.instance().setStyle("Fusion")
        self.path = settings or settings_path()
        self.prefs, self.settings_issue = Preferences.read(self.path)
        self.restoring = True
        self.temp = tempfile.TemporaryDirectory(prefix="loglens-")
        self.db = self.source = self.full = self.filtered = self.full_series = self.series = None
        self.page_index = 0
        self.display_order = None
        self.applied = Scope()
        self.jobs = Jobs(self)
        self.reader = Jobs(self)
        self.autosave = QTimer(self, interval=300, singleShot=True)
        self.autosave.timeout.connect(self.save)
        self.search_timer = QTimer(self, interval=230, singleShot=True)
        self.search_timer.timeout.connect(self.apply_filters)
        self.anim = None
        self.slow_until = 0
        self.setAcceptDrops(True)
        self.setWindowTitle("LogLens")
        self.setMinimumSize(660, 480)
        self.build()
        self.restore()
        self.connect_controls()
        self.restoring = False
        if self.settings_issue:
            self.saved.setText("Settings protected")
            self.notice(self.settings_issue + " Use Reset all settings to recover.")
        self.update_controls()

    def build(self):
        base = QWidget()
        self.setCentralWidget(base)
        layout = QHBoxLayout(base)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rail = QFrame(objectName="rail")
        rail = QVBoxLayout(self.rail)
        rail.setContentsMargins(12, 18, 12, 14)
        brand = QHBoxLayout()
        self.mark = label()
        self.mark.setFixedSize(32, 32)
        self.brand = label("LogLens", "brand")
        brand.addWidget(self.mark)
        brand.addWidget(self.brand)
        brand.addStretch()
        rail.addLayout(brand)
        rail.addSpacing(22)
        self.nav = {}
        for v in VIEWS:
            b = button(v, lambda checked=False, name=v: self.navigate(name), "nav", v)
            b.setCheckable(True)
            b.setAccessibleName(v)
            b.setIconSize(QSize(19, 19))
            self.nav[v] = b
            rail.addWidget(b)
            if v == "Log explorer":
                rail.addStretch()
        self.recents = button("Recent files")
        self.recent_menu = QMenu(self)
        self.recents.setMenu(self.recent_menu)
        rail.addWidget(self.recents)
        self.collapse = button("‹   Collapse sidebar", self.toggle_rail)
        rail.addWidget(self.collapse)
        self.version = label("LogLens   /   " + __version__, "muted")
        rail.addWidget(self.version)
        layout.addWidget(self.rail)
        main = QWidget()
        area = QVBoxLayout(main)
        area.setContentsMargins(18, 14, 16, 9)
        area.setSpacing(10)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.breadcrumb = label("WORKSPACE", "eyebrow")
        self.title = label("Dashboard", "title")
        titles.addWidget(self.breadcrumb)
        titles.addWidget(self.title)
        header.addLayout(titles)
        header.addStretch()
        self.open_btn = button("Open file…", self.pick, "primary", "Open a log file (Ctrl+O)")
        self.refresh = button("Refresh", self.reload, tip="Read the current file again (Ctrl+R)")
        self.exports = button("Export…")
        menu = QMenu(self)
        for fmt in ("json", "html"):
            menu.addAction(f"Entire file · {fmt.upper()}", lambda checked=False, f=fmt: self.export(f))
            menu.addAction(
                f"Explorer matches · {fmt.upper()}", lambda checked=False, f=fmt: self.export(f, True)
            )
        self.exports.setMenu(menu)
        for b in (self.open_btn, self.refresh, self.exports):
            header.addWidget(b)
        area.addLayout(header)
        self.stack = QStackedWidget()
        self.dashboard = Dashboard()
        self.dashboard.choose.clicked.connect(self.pick)
        self.ex = Explorer()
        self.settings = Settings()
        for view in (self.dashboard, self.ex, self.settings):
            self.stack.addWidget(view)
        area.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        self.status = label("Ready · Open a file to begin", "muted")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.saved = label("", "muted")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(110)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.cancel = button("Cancel", self.cancel_work, tip="Cancel operation (Esc)")
        footer.addWidget(self.status, 1)
        for w in (self.progress, self.cancel, self.saved):
            footer.addWidget(w)
        area.addLayout(footer)
        layout.addWidget(main, 1)

    def restore(self):
        p, e = self.prefs, self.ex
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(screen.width(), p.width), min(screen.height(), p.height))
        if p.x is not None and p.y is not None:
            point = QPoint(p.x, p.y)
            if any(s.availableGeometry().contains(point + QPoint(40, 20)) for s in QApplication.screens()):
                self.move(point)
        if p.maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self.settings.restore(p)
        self.dashboard.scope.setCurrentIndex(int(p.filtered_dashboard))
        e.set_scope(p.scope)
        e.size.setCurrentText(str(p.page_size))
        e.inspect.setChecked(p.inspector)
        e.filters.setChecked(p.advanced)
        e.detail.setVisible(p.inspector)
        e.advanced.setVisible(p.advanced)
        self.style_app()
        self.rail_size()
        self.navigate(p.view)
        header = e.table.horizontalHeader()
        for i, c in enumerate(p.order):
            col = COLUMNS.index(c)
            header.moveSection(header.visualIndex(col), i)
        for i, c in enumerate(COLUMNS):
            e.table.setColumnHidden(i, False)
            e.table.setColumnWidth(i, p.widths[c])
            e.table.setColumnHidden(i, c not in p.columns)
        header.setSortIndicatorShown(p.sort in COLUMNS)
        if p.sort in COLUMNS:
            header.setSortIndicator(
                COLUMNS.index(p.sort),
                Qt.SortOrder.DescendingOrder if p.descending else Qt.SortOrder.AscendingOrder,
            )
        QTimer.singleShot(0, self.restore_split)
        self.rebuild_recent()
        self.rebuild_presets()

    def restore_split(self):
        width = self.prefs.sash
        self.ex.split.setSizes(
            [max(180, self.ex.split.width() - width - 4), width]
            if self.ex.split.orientation() == Qt.Orientation.Horizontal
            else [
                max(120, self.ex.split.height() - self.prefs.inspector_height - 4),
                self.prefs.inspector_height,
            ]
        )

    def connect_controls(self):
        e = self.ex
        self.jobs.activity.connect(self.notice)
        self.jobs.activity.connect(lambda _: self.update_controls())
        self.jobs.progress.connect(self.show_progress)
        self.jobs.error.connect(self.failed)
        self.jobs.idle.connect(self.update_controls)
        self.reader.error.connect(self.notice)
        e.search.textEdited.connect(self.schedule_search)
        e.case.toggled.connect(self.schedule_search)
        for w in e.fields.values():
            w.returnPressed.connect(self.apply_filters)
        e.apply.clicked.connect(self.apply_filters)
        e.clear.clicked.connect(self.clear_filters)
        e.filters.toggled.connect(self.show_filters)
        e.inspect.toggled.connect(self.show_inspector)
        e.prev.clicked.connect(lambda: self.page(self.page_index - 1))
        e.next.clicked.connect(lambda: self.page(self.page_index + 1))
        e.page.valueChanged.connect(lambda n: self.page(n - 1))
        e.size.currentTextChanged.connect(self.page_size)
        e.table.horizontalHeader().sectionClicked.connect(self.sort)
        e.table.horizontalHeader().sectionResized.connect(self.column_width)
        e.table.horizontalHeader().sectionMoved.connect(self.column_order)
        e.table.selectionModel().selectionChanged.connect(self.selected)
        e.split.splitterMoved.connect(self.moved_split)
        e.save_preset.clicked.connect(self.save_preset)
        e.delete_preset.clicked.connect(self.delete_preset)
        e.preset.activated.connect(self.apply_preset)
        e.copy_msg.clicked.connect(lambda: self.copy("message"))
        e.copy_record.clicked.connect(lambda: self.copy("record"))
        e.selected_export.clicked.connect(self.save_selected)
        self.dashboard.scope.currentIndexChanged.connect(self.dashboard_scope)
        for key, w in self.settings.controls.items():
            signal = (
                w.currentTextChanged
                if isinstance(w, QComboBox)
                else w.valueChanged
                if isinstance(w, QSpinBox)
                else w.toggled
            )
            signal.connect(lambda value, k=key: self.preference(k, value))
        for c, w in self.settings.columns.items():
            w.toggled.connect(lambda checked, col=c: self.column_visible(col, checked))
        self.settings.history.clicked.connect(self.clear_history)
        self.settings.reset.clicked.connect(self.reset)
        self.ex.search.setToolTip("Search complete messages in the open file (Ctrl+F).")
        self.ex.table.setToolTip("Select a row to inspect it. Ctrl+C copies the current record.")
        for key, slot in (
            ("Ctrl+O", self.pick),
            ("Ctrl+R", self.reload),
            ("Ctrl+F", self.focus_search),
            ("Escape", self.cancel_work),
        ):
            QShortcut(QKeySequence(key), self, activated=slot)
        shortcut = QShortcut(QKeySequence("Ctrl+C"), e.table)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda: self.copy("record"))
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme)

    def dashboard_scope(self, index):
        self.prefs.filtered_dashboard = bool(index)
        self.show_stats()
        self.dirty()

    def system_theme(self, *_):
        if self.prefs.theme == "System":
            self.style_app()

    def style_app(self):
        p = self.prefs
        self.colors = colors_for(p, QApplication.instance())
        pal = QPalette()
        roles = QPalette.ColorRole
        for role, key in (
            (roles.Window, "bg"),
            (roles.WindowText, "text"),
            (roles.Base, "inset"),
            (roles.Text, "text"),
            (roles.Button, "card"),
            (roles.ButtonText, "text"),
            (roles.Highlight, "active"),
            (roles.HighlightedText, "text"),
            (roles.AlternateBase, "card"),
            (roles.PlaceholderText, "muted"),
        ):
            pal.setColor(role, QColor(self.colors[key]))
        self.setPalette(pal)
        self.setFont(QFont("Segoe UI", p.font_size))
        self.setStyleSheet(stylesheet(self.colors))
        self.mark.setPixmap(icon("brand", self.colors["accent"]).pixmap(32, 32))
        for v, b in self.nav.items():
            b.setIcon(icon(v, self.colors["accent"]))
        self.ex.badge.colors = self.colors
        self.ex.table.setFont(QFont("Consolas", p.font_size))
        self.ex.message.setFont(QFont("Consolas", p.font_size))
        self.ex.table.verticalHeader().setDefaultSectionSize(
            max(
                self.fontMetrics().height() + 7,
                {"Compact": 25, "Balanced": 33, "Comfortable": 42}[p.density],
            )
        )
        self.ex.table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
            if p.smooth_scroll
            else QAbstractItemView.ScrollMode.ScrollPerItem
        )
        self.show_stats()

    def rail_size(self):
        small = self.prefs.compact_nav or self.width() < 1000
        self.rail.setFixedWidth(68 if small else 175)
        self.brand.setVisible(not small)
        self.version.setVisible(not small)
        for v, b in self.nav.items():
            b.setText("" if small else "  " + v)
        self.recents.setText("⋯" if small else "Recent files")
        self.collapse.setText("›" if small else "‹   Collapse sidebar")
        self.collapse.setVisible(self.width() >= 1000)
        self.collapse.setToolTip("Expand sidebar" if small else "Collapse sidebar")

    def toggle_rail(self):
        self.prefs.compact_nav = not self.prefs.compact_nav
        self.rail_size()
        self.transition(self.stack)
        self.dirty()

    def transition(self, w):
        if self.anim:
            self.anim.stop()
            self.anim.targetObject().move(self.anim.endValue())
            self.anim.deleteLater()
            self.anim = None
        p = self.prefs
        if (
            self.restoring
            or p.reduced
            or p.motion == "Off"
            or self.jobs.active
            or (p.motion == "Auto" and monotonic() < self.slow_until)
        ):
            return
        dest = w.pos()
        self.anim = QPropertyAnimation(w, b"pos", self)
        self.anim.setStartValue(dest + QPoint(7, 0))
        self.anim.setEndValue(dest)
        self.anim.setDuration(140 if p.motion == "High" else 90)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        last = monotonic()

        def tick(_):
            nonlocal last
            now = monotonic()
            if now - last > 0.045:
                self.slow_until = now + 10
            last = now

        self.anim.valueChanged.connect(tick)
        self.anim.start()

    def navigate(self, name):
        self.prefs.view = name
        self.stack.setCurrentIndex(VIEWS.index(name))
        self.title.setText(name)
        for v, b in self.nav.items():
            b.setChecked(name == v)
        if name == "Log explorer":
            QTimer.singleShot(0, self.restore_split)
        self.transition(self.stack.currentWidget())
        self.dirty()

    def focus_search(self):
        self.navigate("Log explorer")
        self.ex.search.setFocus()
        self.ex.search.selectAll()

    def show_progress(self, value):
        if value < 0:
            self.progress.setRange(0, 0)
            self.notice("Preparing index and statistics…")
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(value)
            self.notice(f"Reading file · {value}% of bytes")

    def notice(self, text):
        self.status.setText(text)
        self.status.setToolTip(text)

    def dirty(self, *_):
        if self.restoring:
            return
        if self.settings_issue:
            self.saved.setText("Settings protected")
            return
        self.saved.setText("Changes pending")
        self.autosave.start()

    def save(self):
        if self.settings_issue:
            return
        try:
            self.prefs.save(self.path)
        except OSError as exc:
            self.saved.setText("Save failed")
            self.saved.setToolTip(str(exc))
        else:
            self.saved.setText("Settings saved")
            self.saved.setToolTip(str(self.path))

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self.restoring and self.isVisible() and not self.isMaximized():
            self.prefs.x, self.prefs.y = self.x(), self.y()
            self.dirty()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "ex"):
            self.rail_size()
            orient = Qt.Orientation.Vertical if self.width() < 920 else Qt.Orientation.Horizontal
            if self.ex.split.orientation() != orient:
                self.ex.split.setOrientation(orient)
                self.restore_split()
        if not self.restoring:
            self.prefs.maximized = self.isMaximized()
            if not self.isMaximized():
                self.prefs.width, self.prefs.height = self.width(), self.height()
            self.dirty()

    def preference(self, key, value):
        if self.restoring:
            return
        setattr(self.prefs, key, value)
        if key == "top":
            self.show_stats()
        elif key in ("theme", "density", "font_size", "smooth_scroll"):
            self.style_app()
        self.dirty()

    def column_width(self, i, old, width):
        if not self.restoring and width >= 50:
            self.prefs.widths[COLUMNS[i]] = width
            self.dirty()

    def column_order(self, *_):
        if not self.restoring:
            h = self.ex.table.horizontalHeader()
            self.prefs.order = tuple(COLUMNS[h.logicalIndex(i)] for i in range(4))
            self.dirty()

    def column_visible(self, col, visible):
        if self.restoring:
            return
        cols = tuple(c for c, w in self.settings.columns.items() if w.isChecked())
        if not cols:
            self.settings.columns[col].setChecked(True)
            self.notice("Keep at least one column visible.")
            return
        self.prefs.columns = cols
        self.ex.table.setColumnHidden(COLUMNS.index(col), not visible)
        self.dirty()

    def moved_split(self, *_):
        width = self.ex.split.sizes()[1]
        if width and not self.restoring:
            if self.ex.split.orientation() == Qt.Orientation.Horizontal:
                self.prefs.sash = width
            else:
                self.prefs.inspector_height = width
            self.dirty()

    def show_inspector(self, show):
        self.prefs.inspector = show
        self.ex.detail.setVisible(show)
        if show:
            self.restore_split()
            self.transition(self.ex.detail)
            self.selected()
        self.dirty()

    def show_filters(self, show):
        self.ex.advanced.setVisible(show)
        self.prefs.advanced = show
        self.dirty()

    def confirm(self, title, prompt):
        return QMessageBox.question(self, title, prompt) == QMessageBox.StandardButton.Yes

    def clear_history(self):
        if self.confirm("Clear recent files", "Remove all file paths from recent files?"):
            self.prefs.recent.clear()
            self.rebuild_recent()
            self.dirty()

    def reset(self):
        if not self.confirm(
            "Reset settings", "Reset appearance, layout, filters, presets and recent files?"
        ):
            return
        if self.settings_issue and self.path.exists():
            try:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
                shutil.copy2(self.path, self.path.with_suffix(f".{stamp}.bak"))
            except OSError as exc:
                self.notice(f"Could not back up settings: {exc}")
                return
        self.cancel_work()
        self.settings_issue = ""
        self.restoring = True
        self.prefs = Preferences()
        self.showNormal()
        self.restore()
        self.restoring = False
        self.apply_filters()
        self.dirty()

    def rebuild_recent(self):
        self.recent_menu.clear()
        for path in self.prefs.recent:
            self.recent_menu.addAction(path, lambda checked=False, v=path: self.load_file(Path(v)))
        if not self.prefs.recent:
            self.recent_menu.addAction("No recent files").setEnabled(False)
        self.settings.history.setEnabled(bool(self.prefs.recent))

    def rebuild_presets(self):
        w = self.ex.preset
        w.clear()
        w.addItem("Saved filters…")
        w.addItems(sorted(self.prefs.presets))
        self.ex.delete_preset.setEnabled(bool(self.prefs.presets))

    def save_preset(self):
        scope = self.ex.scope()
        try:
            scope.filters()
        except ValueError as exc:
            self.notice(str(exc))
            return
        name, ok = QInputDialog.getText(
            self,
            "Save filter preset",
            "Preset name",
            text=self.ex.preset.currentText() if self.ex.preset.currentIndex() > 0 else "",
        )
        name = name.strip()
        if not ok or not name:
            return
        if name in self.prefs.presets and not self.confirm(
            "Update preset", f"Replace the saved filters for {name}?"
        ):
            return
        self.prefs.presets[name] = scope
        self.rebuild_presets()
        self.ex.preset.setCurrentText(name)
        self.dirty()

    def delete_preset(self):
        name = self.ex.preset.currentText()
        if name in self.prefs.presets and self.confirm("Delete preset", f"Delete {name}?"):
            del self.prefs.presets[name]
            self.rebuild_presets()
            self.dirty()

    def apply_preset(self, i):
        if i:
            self.ex.set_scope(self.prefs.presets[self.ex.preset.itemText(i)])
            self.apply_filters()

    def pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open log file", "", "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.load_file(Path(path))

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.load_file(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def closeEvent(self, event):
        self.search_timer.stop()
        self.jobs.shutdown()
        self.reader.shutdown()
        self.autosave.stop()
        self.save()
        self.temp.cleanup()
        event.accept()
