"""Analysis cards and two bounded, data-driven plots."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QProgressBar,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .desktop_style import DARK, button, label, panel
from .parsing import LEVELS
from .reporting import report_data, visible_text


class Plot(QWidget):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.colors = DARK
        self.values = None
        self.ends = ("", "")
        self.setMinimumHeight(162)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Record volume over time" if kind == "time" else "Severity distribution")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, w, h = self.colors, self.width(), self.height()
        if not self.values:
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No matching records")
        elif self.kind == "levels":
            step = h / len(LEVELS)
            maxcount = max(self.values.values()) or 1
            for j, level in enumerate(LEVELS):
                y = (j + 0.5) * step
                p.setPen(QColor(c["muted"]))
                p.drawText(QRectF(0, y - 12, 75, 24), Qt.AlignmentFlag.AlignVCenter, level)
                value = self.values[level]
                box = QRectF(76, y - 4, max(10, w - 131), 8)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(c["edge"]))
                p.drawRoundedRect(box, 4, 4)
                if value:
                    box.setWidth(max(2, box.width() * value / maxcount))
                    p.setBrush(QColor(c[level.lower()]))
                    p.drawRoundedRect(box, 4, 4)
                p.setPen(QColor(c["text"]))
                p.drawText(
                    QRectF(w - 56, y - 12, 54, 24),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    f"{value:,}",
                )
        else:
            totals, failures = self.values
            peak = max(totals) or 1
            left, top, right, bottom = 34, 11, w - 8, h - 23
            for tick in sorted({0, peak // 2, peak}):
                y = bottom - (bottom - top) * tick / peak
                p.setPen(QColor(c["edge"]))
                p.drawLine(QPointF(left, y), QPointF(right, y))
                p.setPen(QColor(c["muted"]))
                p.drawText(
                    QRectF(0, y - 9, 29, 18),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(tick),
                )
            for series, color in ((totals, "accent"), (failures, "error")):
                points = [
                    QPointF(
                        left + i * (right - left) / (len(series) - 1), bottom - v * (bottom - top) / peak
                    )
                    for i, v in enumerate(series)
                ]
                path = QPainterPath(points[0])
                for point in points[1:]:
                    path.lineTo(point)
                if color == "accent":
                    area = QPainterPath(path)
                    area.lineTo(right, bottom)
                    area.lineTo(left, bottom)
                    area.closeSubpath()
                    tint = QColor(c[color])
                    tint.setAlpha(33)
                    p.fillPath(area, tint)
                p.setPen(QPen(QColor(c[color]), 2.1))
                p.drawPath(path)
            p.setPen(QColor(c["muted"]))
            p.drawText(QRectF(left, bottom + 4, w // 2, 19), Qt.AlignmentFlag.AlignLeft, self.ends[0])
            p.drawText(
                QRectF(w // 2, bottom + 4, w // 2 - 8, 19), Qt.AlignmentFlag.AlignRight, self.ends[1]
            )
        p.end()


class Dashboard(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)
        self.welcome, intro = panel("Open a log file")
        intro.addWidget(
            label("Drop a .log or .txt file here to analyze it and explore its records.", "muted", True)
        )
        self.choose = button("Choose file…", role="primary")
        intro.addWidget(self.choose, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.welcome)
        bar, bl = panel()
        top = QHBoxLayout()
        top.addWidget(label("Analysis scope", "muted"))
        self.scope = QComboBox()
        self.scope.addItems(["Entire file", "Explorer matches"])
        top.addWidget(self.scope)
        self.range = label("Open a file to see its UTC range", "muted")
        self.range.setWordWrap(True)
        self.range.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.range, 1)
        bl.addLayout(top)
        layout.addWidget(bar)
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self.cards = []
        self.strips = []
        for title in ("Lines read", "Matched records", "Failures", "Failure rate"):
            card, box = panel()
            box.addWidget(label(title, "muted"))
            number = label("—", "number")
            box.addWidget(number)
            foot = label("—", "muted")
            box.addWidget(foot)
            strip = QProgressBar()
            strip.setRange(0, 1000)
            strip.setFixedHeight(3)
            strip.setTextVisible(False)
            box.addWidget(strip)
            self.strips.append(strip)
            self.cards.append((card, number, foot))
        layout.addLayout(self.grid)
        self.charts = QGridLayout()
        self.charts.setSpacing(12)
        self.panels = []
        for title, kind, subtitle in (
            ("Event volume", "time", "Matched records and failures · 20 UTC intervals"),
            ("Severity distribution", "levels", "Matched records by severity"),
        ):
            card, box = panel(title)
            caption = label(subtitle, "muted")
            box.addWidget(caption)
            plot = Plot(kind)
            box.addWidget(plot)
            if kind == "time":
                self.time = plot
                self.legend = caption
            else:
                self.levels = plot
            self.panels.append(card)
        self.rankings = []
        for title in ("Top failing services", "Recurring error messages"):
            card, box = panel(title)
            rows = QTreeWidget()
            rows.setColumnCount(3)
            rows.setHeaderLabels(["Rank", "Name", "Count"])
            rows.setAccessibleName(title)
            rows.setHeaderHidden(True)
            rows.setRootIsDecorated(False)
            rows.setUniformRowHeights(True)
            rows.setIndentation(0)
            rows.setMinimumHeight(120)
            rows.setMaximumHeight(180)
            rows.header().setStretchLastSection(False)
            rows.setColumnWidth(0, 36)
            rows.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            rows.setColumnWidth(2, 64)
            box.addWidget(rows)
            self.rankings.append(rows)
            self.panels.append(card)
        layout.addLayout(self.charts)
        layout.addStretch()
        self.mode = None
        self.reflow(1000)

    def reflow(self, width):
        narrow = width < 690
        if self.mode == narrow:
            return
        self.mode = narrow
        cols = 2 if narrow else 4
        for i, (widget, _, _) in enumerate(self.cards):
            self.grid.addWidget(widget, i // cols, i % cols)
        cols = 1 if narrow else 2
        for i, widget in enumerate(self.panels):
            self.charts.addWidget(widget, i // cols, i % cols)
        self.charts.setColumnStretch(0, 3)
        self.charts.setColumnStretch(1, 0 if narrow else 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "cards"):
            self.reflow(self.viewport().width())

    def display(self, summary, series, top, colors):
        self.welcome.setVisible(summary is None)
        self.scope.setEnabled(summary is not None)
        for plot in (self.time, self.levels):
            plot.colors = colors
        data = report_data(summary, top) if summary is not None else {}
        matched = data.get("matched", 0)
        self.time.values = series if matched else None
        self.levels.values = data.get("levels") if matched else None
        self.time.ends = tuple((data.get(k) or "")[11:19] for k in ("earliest_utc", "latest_utc"))
        lo, hi = data.get("earliest_utc"), data.get("latest_utc")
        interval = (
            f"{lo[:10]}   {lo[11:19]} – {hi[11:19]} UTC"
            if matched and lo[:10] == hi[:10]
            else f"{lo} → {hi}"
        )
        self.range.setText(interval if matched else "No matching time range")
        self.range.setToolTip(f"{lo} → {hi}" if matched else "")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setText(
            f'<span style="color:{colors["accent"]}">━ Matched</span> &nbsp; '
            f'<span style="color:{colors["error"]}">━ Failures</span> &nbsp; · &nbsp; 20 UTC intervals'
        )
        self.time.setAccessibleDescription(str(series) if matched else "No matches")
        self.levels.setAccessibleDescription(str(self.levels.values or {}))
        self.time.update()
        self.levels.update()
        if data:
            valid = data["lines"] - data["malformed"]
            rate = data["failure_percent"]
            values = (
                f"{data['lines']:,}",
                f"{matched:,}",
                f"{data['failures']:,}",
                f"{rate:.2f}%" if rate is not None else "n/a",
            )
            notes = (
                f"{valid:,} valid · {data['malformed']:,} malformed",
                f"{data['filtered_out']:,} filtered out",
                f"{summary.levels['ERROR']:,} error · {summary.levels['CRITICAL']:,} critical",
                "Of matched records",
            )
        else:
            values = ("0", "0", "0", "0.00%")
            notes = ("No file loaded",) * 4
        for i, (_, metric, note) in enumerate(self.cards):
            strip = self.strips[i]
            pairs = (
                (data.get("lines", 0) - data.get("malformed", 0), data.get("lines", 0)),
                (matched, data.get("lines", 0)),
                (data.get("failures", 0), matched),
                (data.get("failures", 0), matched),
            )
            n, total = pairs[i]
            strip.setValue(round(1000 * n / total) if total else 0)
            strip.setToolTip(
                ("Valid / all lines", "Matched / all lines", "Failures / matches", "Failures / matches")[i]
            )
            strip.setStyleSheet(
                "QProgressBar::chunk {background:" + colors[("info", "accent", "error", "cyan")[i]] + ";}"
            )
            metric.setText(values[i])
            metric.setStyleSheet("color:" + colors[("text", "accent", "error", "cyan")[i]])
            note.setText(notes[i])
        for tree, key, field in zip(
            self.rankings, ("top_failing_services", "top_error_messages"), ("service", "message")
        ):
            tree.clear()
            rows = data.get(key, [])
            if not rows:
                tree.addTopLevelItem(
                    QTreeWidgetItem(["", "No failures in this scope" if data else "Awaiting a file", ""])
                )
            for i, row in enumerate(rows, 1):
                item = QTreeWidgetItem([f"{i:02d}", visible_text(row[field][:512]), f"{row['count']:,}"])
                item.setForeground(0, QColor(colors["muted"]))
                item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tree.addTopLevelItem(item)
