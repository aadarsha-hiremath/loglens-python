"""File and query operations for the desktop window; worker inputs are immutable snapshots."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from .analysis import Filters
from .desktop_data import (
    COLUMNS,
    Scope,
    build_snapshot,
    export_selection,
    page_rows,
    records,
    scoped_summary,
    timeline,
)
from .reporting import render
from .output import validate_output, write_text


class Workspace:
    def reload(self):
        if self.source:
            self.load_file(self.source)

    def load_file(self, path):
        path = Path(path).absolute()
        if path.suffix.lower() not in (".log", ".txt"):
            self.notice("Choose a .log or .txt application log.")
            return
        self.search_timer.stop()
        self.reader.cancel(False)
        db = Path(self.temp.name) / ("b.sqlite" if self.db and self.db.name == "a.sqlite" else "a.sqlite")
        try:
            scope = self.ex.scope()
            scope.filters()
        except ValueError as exc:
            self.notice(str(exc))
            return
        self.prefs.scope = scope
        order, desc, size = self.prefs.sort, self.prefs.descending, self.prefs.page_size

        def work(cancel, progress):
            full = build_snapshot(path, db, Filters(), cancel, progress)
            series = timeline(db, full, Scope(), cancel)
            filtered = scoped_summary(db, full, scope, cancel)
            part = series if filtered is full else timeline(db, filtered, scope, cancel)
            return full, series, filtered, part, page_rows(db, 0, order, desc, cancel, scope, size)

        def done(result):
            self.source, self.db = path, db
            self.full, self.full_series, self.filtered, self.series, rows = result
            for lvl, check in self.ex.levels.items():
                check.setText(f"{lvl}   {self.full.levels[lvl]:,}")
            self.applied = scope
            self.setWindowTitle(f"{path.name} · LogLens")
            self.breadcrumb.setText("WORKSPACE   /   " + path.name)
            self.breadcrumb.setToolTip(str(path))
            self.prefs.recent = [str(path)] + [p for p in self.prefs.recent if p != str(path)][:9]
            self.rebuild_recent()
            self.dirty()
            self.show_stats()
            self.publish_page(0, rows)
            self.notice(f"Ready · {self.full.lines:,} lines read · {path.name}")
            if self.prefs.scope != scope:
                self.apply_filters()

        self.progress.setRange(0, 0)
        self.jobs.start("Opening " + path.name + "…", work, done)

    def restore_page_controls(self):
        if self.display_order is None:
            return
        col, desc, size = self.display_order
        self.prefs.sort, self.prefs.descending, self.prefs.page_size = col, desc, size
        h = self.ex.table.horizontalHeader()
        h.setSortIndicatorShown(col in COLUMNS)
        if col in COLUMNS:
            h.setSortIndicator(
                COLUMNS.index(col), Qt.SortOrder.DescendingOrder if desc else Qt.SortOrder.AscendingOrder
            )
        self.ex.size.blockSignals(True)
        self.ex.size.setCurrentText(str(size))
        self.ex.size.blockSignals(False)
        self.ex.page.blockSignals(True)
        self.ex.page.setValue(self.page_index + 1)
        self.ex.page.blockSignals(False)

    def failed(self, message):
        self.restore_page_controls()
        self.notice(message)

    def cancel_work(self):
        self.search_timer.stop()
        self.jobs.cancel()
        self.restore_page_controls()
        self.reader.cancel(False)
        self.update_controls()

    def schedule_search(self, *_):
        if not self.restoring:
            self.search_timer.start()

    def clear_filters(self):
        self.ex.set_scope(Scope())
        self.ex.preset.setCurrentIndex(0)
        self.apply_filters()

    def apply_filters(self):
        self.search_timer.stop()
        scope = self.ex.scope()
        try:
            scope.filters()
        except ValueError as exc:
            self.notice(str(exc))
            return
        self.prefs.scope = scope
        self.dirty()
        if not self.db or (self.jobs.active and self.jobs.label.startswith("Opening ")):
            return
        db, base = self.db, self.full
        original_series = self.full_series
        order, desc, size = self.prefs.sort, self.prefs.descending, self.prefs.page_size

        def work(cancel, progress):
            summary = scoped_summary(db, base, scope, cancel)
            series = original_series if summary is base else timeline(db, summary, scope, cancel)
            return summary, series, page_rows(db, 0, order, desc, cancel, scope, size)

        def done(result):
            self.filtered, self.series, rows = result
            self.applied = scope
            self.show_stats()
            self.publish_page(0, rows)

        self.jobs.start("Searching snapshot…", work, done)

    def show_stats(self, *_):
        filtered = self.dashboard.scope.currentIndex() == 1
        self.dashboard.display(
            self.filtered if filtered else self.full,
            self.series if filtered else self.full_series,
            self.prefs.top,
            self.colors,
        )

    def page_size(self, text):
        if self.restoring:
            return
        self.prefs.page_size = int(text)
        self.dirty()
        self.page(0)

    def sort(self, i):
        if self.jobs.active:
            return
        col = COLUMNS[i]
        self.prefs.descending = self.prefs.sort == col and not self.prefs.descending
        self.prefs.sort = col
        h = self.ex.table.horizontalHeader()
        h.setSortIndicatorShown(True)
        h.setSortIndicator(
            i, Qt.SortOrder.DescendingOrder if self.prefs.descending else Qt.SortOrder.AscendingOrder
        )
        self.dirty()
        self.page(0)

    def page(self, index):
        if self.restoring or self.db is None or self.jobs.active:
            return
        size = self.prefs.page_size
        index = max(0, min(index, max(0, (self.filtered.matched - 1) // size)))
        db, col, desc, scope = self.db, self.prefs.sort, self.prefs.descending, self.applied
        self.jobs.start(
            "Reading page…",
            lambda cancel, _: page_rows(db, index, col, desc, cancel, scope, size),
            lambda rows: self.publish_page(index, rows),
        )

    def publish_page(self, index, rows):
        self.reader.cancel(False)
        self.page_index = index
        self.display_order = (self.prefs.sort, self.prefs.descending, self.prefs.page_size)
        e = self.ex
        e.model.replace(rows)
        e.set_record(None)
        n = self.filtered.matched
        size = self.prefs.page_size
        start = index * size
        pages = max(1, (n + size - 1) // size)
        e.count.setText(f"{start + 1:,}–{start + len(rows):,} of {n:,} matches" if rows else "0 matches")
        e.page.blockSignals(True)
        e.page.setRange(1, pages)
        e.page.setValue(index + 1)
        e.page.blockSignals(False)
        e.pages.setText(f"of {pages:,}")
        desc = self.applied.description()
        e.scope_label.setText("Applied   /   " + (desc[:90] + "…" if len(desc) > 90 else desc))
        e.scope_label.setToolTip(desc)
        self.notice("Ready · " + self.source.name)
        self.update_controls()

    def selected_ids(self):
        return [self.ex.model.rows[i.row()][0] for i in self.ex.table.selectionModel().selectedRows()]

    def selected(self, *_):
        ids = self.selected_ids()
        self.ex.selected_export.setEnabled(bool(ids) and not self.jobs.active)
        self.reader.cancel(False)
        self.ex.set_record(None)
        if not ids or not self.db or not self.prefs.inspector:
            return
        current = self.ex.table.currentIndex()
        line = self.ex.model.rows[current.row()][0] if current.isValid() else ids[0]
        if line not in ids:
            line = ids[0]
        db = self.db
        self.reader.start(
            "Reading record", lambda cancel, _: next(records(db, [line], cancel)), self.ex.set_record
        )

    def copy(self, what):
        ids = self.selected_ids()
        if not ids or self.jobs.active:
            return
        db = self.db
        line = self.ex.record["line"] if self.ex.record and self.ex.record["line"] in ids else ids[0]

        def work(cancel, _):
            row = next(records(db, [line], cancel))
            return row["message"] if what == "message" else json.dumps(row, ensure_ascii=False, indent=2)

        def done(text):
            QApplication.clipboard().setText(text)
            self.notice("Message copied" if what == "message" else "Record copied")

        self.jobs.start("Preparing clipboard…", work, done)

    def save_selected(self):
        ids = self.selected_ids()
        if not ids or self.jobs.active:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export selected records", "selected.jsonl", "JSON Lines (*.jsonl)"
        )
        if path:
            db, source = self.db, self.source
            self.jobs.start(
                "Exporting selected records…",
                lambda cancel, _: export_selection(db, source, Path(path), ids, cancel),
                lambda _: self.notice(f"Saved {len(ids):,} records to {path}"),
            )

    def export(self, fmt, filtered=False):
        if self.jobs.active or not self.source:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export analysis", self.source.stem + "-report." + fmt, f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        summary = self.filtered if filtered else self.full
        source, limit = self.source, self.prefs.top

        def work(cancel, _):
            validate_output(Path(path), source)
            text = render(summary, fmt, limit)
            if not cancel.is_set():
                write_text(Path(path), text)

        self.jobs.start("Exporting report…", work, lambda _: self.notice(f"Saved {fmt.upper()} to {path}"))

    def update_controls(self):
        busy = self.jobs.active
        self.progress.setVisible(busy)
        self.cancel.setVisible(busy)
        self.refresh.setEnabled(bool(self.source) and not busy)
        self.exports.setEnabled(bool(self.full) and not busy)
        self.ex.size.setEnabled(not busy)
        self.ex.page.setEnabled(not busy and self.filtered is not None)
        self.ex.prev.setEnabled(not busy and self.page_index > 0)
        self.ex.next.setEnabled(
            not busy
            and self.filtered is not None
            and (self.page_index + 1) * self.prefs.page_size < self.filtered.matched
        )
        self.ex.selected_export.setEnabled(not busy and bool(self.selected_ids()))
        if not busy:
            self.progress.setRange(0, 0)
