"""Tk desktop interface. Launch with python -m loglens.gui [FILE]."""

import argparse
import sqlite3
import tempfile
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, ttk

from .desktop_data import COLUMNS, MAX_TOP, PAGE_SIZE, Cancelled, build_snapshot, make_filters, preview, read_page
from .desktop_style import apply_style, scroll_table, severity_chart
from .output import validate_output, write_text
from .parsing import LEVELS
from .preferences import Preferences, settings_path
from .reporting import visible_text, render, report_data

HEADINGS = ("Timestamp (UTC)", "Severity", "Service", "Message")


class Desktop:
    def __init__(self, root, preferences=None):
        self.root = root
        self.settings = preferences or settings_path()
        self.prefs = Preferences.load(self.settings)
        self.root.title("LogLens")
        self.root.minsize(760, 555)
        self.resize_window()
        self.colors = apply_style(root, self.prefs.theme, self.prefs.font_size)
        self.temp = tempfile.TemporaryDirectory(prefix="loglens-")
        self.db = Path(self.temp.name) / "snapshot.sqlite"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loglens")
        self.future = None
        self.cancellable = False
        self.stop = Event()
        self.closing = False
        self.source = None
        self.summary = None
        self.counts = {}
        self.page = 0
        self.sort = ("rowid", False)
        self.applied = "All records"
        self.status = tk.StringVar(value="Open a log file to begin.")
        self.file_label = tk.StringVar(value="No file selected")
        self.scope = tk.StringVar(value="")
        self.page_text = tk.StringVar(value="No records")
        self.page_number = tk.StringVar(value="1")
        self.page_count = tk.StringVar(value="of 1")
        self.times = tk.StringVar(value="UTC range   —")
        self.inputs = {}
        self.metrics = {}
        self.make_layout()
        self.display_summary()
        self.set_controls()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-o>", lambda event: self.open_file())
        root.bind("<F5>", lambda event: self.scan())
        self.sash_pending = True
        self.split.bind("<Configure>", self.on_split_resize)
        self.split.bind("<Map>", lambda event: self.root.after_idle(self.restore_sash) if self.sash_pending else None)

    def resize_window(self):
        width = min(self.root.winfo_screenwidth(), self.prefs.width)
        height = min(self.root.winfo_screenheight() - 65, self.prefs.height)
        self.root.geometry(f"{width}x{height}")

    def on_split_resize(self, event):
        if self.sash_pending and event.width >= 320:
            self.sash_pending = False
            self.root.after_idle(self.restore_sash)

    def restore_sash(self):
        if not self.split.winfo_ismapped() or self.split.winfo_width() < 320:
            self.sash_pending = True
            return
        self.sash_pending = False
        self.split.sashpos(0, min(self.prefs.sash, max(100, self.split.winfo_width() - 240)))

    def make_layout(self):
        outer = ttk.Frame(self.root, padding=(16, 10))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="LogLens", style="Title.TLabel").pack(side="left")
        self.settings_btn = ttk.Button(header, text="Preferences", command=self.preferences)
        self.settings_btn.pack(side="right", padx=(6, 0))
        self.export_btn = ttk.Menubutton(header, text="Export report")
        exports = tk.Menu(self.export_btn, tearoff=False)
        for fmt in ("json", "html"):
            exports.add_command(label=fmt.upper() + "…", command=lambda f=fmt: self.export(f))
        self.export_btn.configure(menu=exports)
        self.export_btn.pack(side="right")

        bar = ttk.Frame(outer)
        bar.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        self.open_btn = ttk.Button(bar, text="Open log…", style="Accent.TButton", command=self.open_file)
        self.open_btn.pack(side="left")
        self.refresh_btn = ttk.Button(bar, text="Refresh", command=self.scan)
        self.refresh_btn.pack(side="left", padx=6)
        ttk.Label(bar, textvariable=self.file_label, style="Section.TLabel", anchor="w").pack(
            side="left", fill="x", expand=True, padx=6)

        filters = ttk.Frame(outer)
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        fields = (("level", "Severity", 10), ("service", "Service", 12),
                  ("since", "Since (inclusive)", 17), ("until", "Until (inclusive)", 17),
                  ("search", "Message contains", 14))
        for i, (key, label, width) in enumerate(fields):
            filters.columnconfigure(i, weight=1)
            ttk.Label(filters, text=label, style="Muted.TLabel").grid(row=0, column=i, sticky="w")
            value = self.inputs[key] = tk.StringVar()
            if key == "level":
                widget = ttk.Combobox(filters, textvariable=value, values=("", *LEVELS), width=width)
            else:
                widget = ttk.Entry(filters, textvariable=value, width=width)
            widget.grid(row=1, column=i, sticky="ew", padx=(0, 6))
            widget.bind("<Return>", lambda event: self.scan())
        self.apply_btn = ttk.Button(filters, text="Apply", command=self.scan)
        self.apply_btn.grid(row=1, column=5)
        self.clear_btn = ttk.Button(filters, text="Clear", command=self.clear_filters)
        self.clear_btn.grid(row=1, column=6, padx=(4, 0))

        self.tabs = ttk.Notebook(outer)
        self.tabs.grid(row=3, column=0, sticky="nsew")
        overview = ttk.Frame(self.tabs, padding=10)
        explorer = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(overview, text="Dashboard")
        self.tabs.add(explorer, text="Log explorer")
        self.make_dashboard(overview)
        self.make_explorer(explorer)
        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        ttk.Label(footer, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=80)
        self.cancel_btn = ttk.Button(footer, text="Cancel", command=self.stop_job)


    def make_dashboard(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        ttk.Label(parent, textvariable=self.scope, style="Muted.TLabel").grid(row=0, sticky="w")
        tiles = ttk.Frame(parent)
        tiles.grid(row=1, sticky="ew", pady=7)
        for i, (key, label) in enumerate((("lines","Lines read"), ("valid","Valid records"),
                ("malformed","Malformed"), ("filtered_out","Filtered out"), ("matched","Matched"),
                ("failures","Failures"), ("rate","Failure rate"))):
            tiles.columnconfigure(i, weight=1, uniform="tile")
            tile = ttk.Frame(tiles, style="Tile.TFrame", padding=(8, 7))
            tile.grid(row=0, column=i, sticky="nsew", padx=(0, 3))
            ttk.Label(tile, text=label, style="Tile.TLabel").pack(anchor="w")
            self.metrics[key] = tk.StringVar(value="—")
            ttk.Label(tile, textvariable=self.metrics[key], style="Value.TLabel").pack(anchor="w")
        ttk.Label(parent, textvariable=self.times, style="Muted.TLabel").grid(row=2, sticky="w", pady=(0, 8))
        self.split = ttk.Panedwindow(parent, orient="horizontal")
        self.split.grid(row=3, sticky="nsew")
        left = ttk.Frame(self.split, padding=(0, 0, 8, 0))
        right = ttk.Frame(self.split, padding=(8, 0, 0, 0))
        self.split.add(left, weight=1)
        self.split.add(right, weight=2)
        ttk.Label(left, text="Severity distribution", style="Section.TLabel").pack(anchor="w", pady=(0, 5))
        self.chart = tk.Canvas(left, highlightthickness=0, width=170, height=160)
        self.chart.pack(fill="both", expand=True)
        self.chart.bind("<Configure>", lambda event: severity_chart(self.chart, self.counts, self.colors))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        self.ranks = {}
        for index, (key, title, field) in enumerate((("top_failing_services", "Top failing services", "Service"),
                                                     ("top_error_messages", "Top error messages", "Message"))):
            ttk.Label(right, text=title, style="Section.TLabel").grid(row=index*2, sticky="w", pady=(0, 4))
            frame, tree = scroll_table(right, ("count", "label"), ("Count", field), (65, 210), 3)
            frame.grid(row=index*2+1, sticky="nsew", pady=(0, 6))
            self.ranks[key] = tree

    def make_explorer(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, textvariable=self.page_text).pack(side="left")
        self.next_btn = ttk.Button(toolbar, text="Next →", command=lambda: self.show_page(self.page + 1))
        self.next_btn.pack(side="right")
        self.prev_btn = ttk.Button(toolbar, text="← Previous", command=lambda: self.show_page(self.page - 1))
        self.prev_btn.pack(side="right", padx=5)
        self.go_btn = ttk.Button(toolbar, text="Go", width=4, command=self.jump_page)
        self.go_btn.pack(side="right", padx=(3, 8))
        ttk.Label(toolbar, textvariable=self.page_count).pack(side="right", padx=3)
        self.page_field = ttk.Entry(toolbar, textvariable=self.page_number, width=6)
        self.page_field.pack(side="right")
        self.page_field.bind("<Return>", lambda event: self.jump_page())
        ttk.Label(toolbar, text="Page").pack(side="right", padx=4)
        frame, self.records = scroll_table(parent, COLUMNS, HEADINGS,
                [self.prefs.widths[c] for c in COLUMNS], horizontal=True)
        self.records.configure(displaycolumns=self.prefs.columns)
        frame.pack(fill="both", expand=True)
        for col in COLUMNS:
            self.records.heading(col, command=lambda c=col: self.sort_by(c))
        ttk.Label(parent, text="Click a heading to sort all matches. Drag edges to resize. Cells preview up to 512 characters.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    def set_controls(self):
        busy = self.future is not None
        if busy and self.cancellable:
            self.cancel_btn.pack(side="right")
        else:
            self.cancel_btn.pack_forget()
        ready = self.summary is not None and not busy
        for widget, enabled in ((self.open_btn, not busy), (self.settings_btn, not busy),
                (self.refresh_btn, self.source and not busy), (self.apply_btn, self.source and not busy),
                (self.clear_btn, not busy), (self.export_btn, ready),
                (self.cancel_btn, busy and self.cancellable),
                (self.go_btn, ready and self.summary.matched > PAGE_SIZE),
                (self.page_field, ready and self.summary.matched > PAGE_SIZE),
                (self.prev_btn, ready and self.page > 0),
                (self.next_btn, ready and (self.page + 1) * PAGE_SIZE < self.summary.matched)):
            widget.state(["!disabled"] if enabled else ["disabled"])

    def work(self, label, function, on_success, *, cancellable=True):
        if self.future or self.closing:
            return
        self.stop = Event()
        self.cancellable = cancellable
        self.future = self.pool.submit(function, self.stop)
        self.status.set(label)
        self.progress.pack(side="right", padx=8)
        self.progress.start(12)
        self.set_controls()

        def poll():
            if not self.future.done():
                self.root.after(50, poll)
                return
            completed, self.future = self.future, None
            self.progress.stop()
            self.progress.pack_forget()
            try:
                result = completed.result()
                if self.stop.is_set():
                    raise Cancelled()
                if not self.closing:
                    on_success(result)
            except (OSError, sqlite3.Error, ValueError, Cancelled) as exc:
                self.status.set("Cancelled." if self.stop.is_set() else f"Could not complete operation: {exc}")
            finally:
                self.set_controls()
                if self.closing:
                    self.finish_close()
        self.root.after(50, poll)

    def stop_job(self):
        if self.future and self.cancellable:
            self.stop.set()
            self.status.set("Cancelling…")

    def open_file(self):
        if self.future:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open a log file",
                                          filetypes=[("Log files", "*.log"), ("All files", "*")])
        if path:
            self.scan(Path(path))

    def clear_filters(self):
        for value in self.inputs.values():
            value.set("")
        if self.source:
            self.scan()

    def scan(self, source=None):
        if self.future or self.closing:
            return
        path = source or self.source
        if path is None:
            return
        try:
            filters = make_filters(**{key: var.get() for key, var in self.inputs.items()})
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.source = Path(path).absolute()
        path = self.source
        shown = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
        self.file_label.set(str(shown))
        self.root.title(f"{path.name} · LogLens")
        self.summary = None
        self.page, self.sort = 0, ("rowid", False)
        self.applied = " · ".join(f"{k}={v.get()}" for k, v in self.inputs.items() if v.get()) or "All records"
        self.display_summary()
        self.display_page([])

        def scan_file(cancel):
            summary = build_snapshot(path, self.db, filters, cancel)
            rows = read_page(self.db, 0, "rowid", False, cancel)
            return summary, rows

        def loaded(result):
            self.summary, rows = result
            self.display_summary()
            self.display_page(rows)
            self.status.set(f"Analysis complete · {self.summary.lines:,} lines read")
        self.work("Analyzing file…", scan_file, loaded)

    def display_summary(self):
        data = report_data(self.summary, self.prefs.top) if self.summary is not None else {}
        if data:
            data["valid"] = data["lines"] - data["malformed"]
            rate = data["failure_percent"]
            data["rate"] = f"{rate:.2f}%" if rate is not None else "n/a"
        self.scope.set(f"Full-file analysis   /   {self.applied}" if data else "Full-file analysis")
        for key, value in self.metrics.items():
            n = data.get(key, "—")
            value.set(f"{n:,}" if isinstance(n, int) else n)
        self.times.set(f"Earliest UTC   {data.get('earliest_utc') or '—'}     ·     "
                       f"Latest UTC   {data.get('latest_utc') or '—'}")
        self.counts = data.get("levels", {})
        severity_chart(self.chart, self.counts, self.colors)
        for key, tree in self.ranks.items():
            tree.delete(*tree.get_children())
            for row in data.get(key, []):
                label = row.get("service", row.get("message", ""))
                tree.insert("", "end", values=(row["count"], visible_text(preview(label))))

    def display_page(self, rows):
        self.records.delete(*self.records.get_children())
        for row in rows:
            self.records.insert("", "end", values=tuple(visible_text(text) for text in row))
        for col, label in zip(COLUMNS, HEADINGS):
            suffix = (" ↓" if self.sort[1] else " ↑") if col == self.sort[0] else ""
            self.records.heading(col, text=label + suffix)
        matched = self.summary.matched if self.summary else 0
        pages = (matched + PAGE_SIZE - 1) // PAGE_SIZE
        self.page_number.set(str(self.page + 1) if matched else "0")
        self.page_count.set(f"of {pages:,}")
        start = self.page * PAGE_SIZE
        self.page_text.set(f"{start+1:,}–{start+len(rows):,} of {matched:,} matches" if rows else ("0 matches" if self.summary is not None else "No snapshot"))

    def jump_page(self):
        if self.future or self.summary is None:
            return
        pages = (self.summary.matched + PAGE_SIZE - 1) // PAGE_SIZE
        try:
            number = int(self.page_number.get())
            if not 1 <= number <= pages:
                raise ValueError()
        except ValueError:
            self.status.set(f"Enter a page number from 1 to {pages:,}.")
            return
        self.show_page(number - 1)

    def sort_by(self, column):
        self.show_page(0, (column, self.sort[0] == column and not self.sort[1]))

    def show_page(self, page, sort=None):
        if self.future or self.summary is None or not 0 <= page <= max(0, (self.summary.matched-1)//PAGE_SIZE):
            return
        order = sort or self.sort

        def loaded(rows):
            self.page, self.sort = page, order
            self.display_page(rows)
            self.status.set(f"Snapshot · {self.applied}")
        self.work("Reading records…", lambda cancel: read_page(self.db, page, *order, cancel), loaded)

    def export(self, fmt):
        if self.future or self.summary is None:
            return
        dest = filedialog.asksaveasfilename(parent=self.root, title="Export report", defaultextension="."+fmt,
                    initialfile=self.source.stem+"-report."+fmt, filetypes=[(fmt.upper(), "*."+fmt)])
        if not dest:
            return
        path, source, summary, limit = Path(dest), self.source, self.summary, self.prefs.top

        def save(cancel):
            validate_output(path, source)
            write_text(path, render(summary, fmt, limit))
        self.work("Saving report…", save, lambda _: self.status.set(f"Saved {fmt.upper()} report to {path}"),
                  cancellable=False)

    def remember_layout(self):
        if self.root.state() == "normal":
            self.prefs.width = self.root.winfo_width()
            self.prefs.height = self.root.winfo_height()
        sash = self.split.sashpos(0)
        if not self.sash_pending and sash >= 80:
            self.prefs.sash = sash
        for col in COLUMNS:
            self.prefs.widths[col] = int(self.records.column(col, "width"))

    def preferences(self):
        if self.future:
            return
        self.remember_layout()
        win = tk.Toplevel(self.root)
        win.title("LogLens preferences")
        win.transient(self.root)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        theme = tk.StringVar(value=self.prefs.theme)
        size = tk.StringVar(value=str(self.prefs.font_size))
        top = tk.StringVar(value=str(self.prefs.top))
        for i, (label, variable, values) in enumerate((
                ("Theme", theme, ("Light", "Dark")), ("Font size", size, tuple(range(9, 17))),
                ("Top results", top, None))):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=4)
            if values:
                field = ttk.Combobox(body, textvariable=variable, values=values, state="readonly", width=10)
            else:
                field = ttk.Spinbox(body, from_=1, to=MAX_TOP, textvariable=variable, width=10)
            field.grid(row=i, column=1, sticky="ew", pady=4)
        ttk.Label(body, text="Explorer columns", style="Section.TLabel").grid(row=3, columnspan=2, sticky="w", pady=6)
        flags = {}
        for i, (col, heading) in enumerate(zip(COLUMNS, HEADINGS)):
            flags[col] = tk.BooleanVar(value=col in self.prefs.columns)
            ttk.Checkbutton(body, text=heading, variable=flags[col]).grid(row=4+i, columnspan=2, sticky="w")
        actions = ttk.Frame(body)
        actions.grid(row=8, columnspan=2, sticky="ew", pady=(10, 0))

        def apply(reset=False):
            if reset:
                self.prefs = Preferences()
                self.resize_window()
            else:
                visible = tuple(c for c in COLUMNS if flags[c].get())
                try:
                    n = int(top.get())
                    if not 1 <= n <= MAX_TOP or not visible:
                        raise ValueError()
                except ValueError:
                    messagebox.showerror("Preferences", "Use 1–100 top results and select at least one column.", parent=win)
                    return
                self.prefs.theme, self.prefs.font_size = theme.get(), int(size.get())
                self.prefs.top, self.prefs.columns = n, visible
            self.colors = apply_style(self.root, self.prefs.theme, self.prefs.font_size)
            self.records.configure(displaycolumns=self.prefs.columns)
            for c in COLUMNS:
                self.records.column(c, width=self.prefs.widths[c])
            win.destroy()
            if reset:
                self.root.after_idle(self.restore_sash)
            self.display_summary()
            self.save_preferences()

        ttk.Button(actions, text="Reset to defaults", command=lambda: apply(True)).pack(side="left")
        ttk.Button(actions, text="Apply", style="Accent.TButton", command=apply).pack(side="right", padx=(6, 0))
        win.grab_set()
        win.focus_set()

    def save_preferences(self):
        try:
            self.prefs.save(self.settings)
        except OSError as exc:
            messagebox.showwarning("Preferences", f"Could not save preferences: {exc}", parent=self.root)

    def close(self):
        self.closing = True
        if self.future:
            self.stop_job()
            self.status.set("Finishing current operation…")
        else:
            self.finish_close()

    def finish_close(self):
        try:
            self.remember_layout()
            self.save_preferences()
            self.pool.shutdown(wait=True)
            self.temp.cleanup()
        finally:
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the LogLens desktop application.")
    parser.add_argument("file", nargs="?", type=Path, help="optional log file to analyze")
    args = parser.parse_args(argv)
    root = tk.Tk()
    desktop = Desktop(root)
    if args.file:
        root.after_idle(lambda: desktop.scan(args.file))
    root.mainloop()


if __name__ == "__main__":
    main()
