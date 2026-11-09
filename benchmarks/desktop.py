"""Measure real desktop scanning, paging and Tk dispatch on a generated log."""

import argparse
import json
import platform
import tempfile
import tkinter as tk
import tracemalloc
from pathlib import Path
from time import perf_counter

from loglens.desktop_data import PAGE_SIZE
from loglens.gui import Desktop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--trace", action="store_true", help="measure Python allocations during analysis")
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("--rows must be positive")
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        path = folder / "batch.log"
        with path.open("w", encoding="utf-8", newline="\n") as file:
            for i in range(args.rows):
                file.write(f"2026-01-15T09:00:00Z | ERROR | worker-{i % 7} | Request {i:09d} failed\n")
        root = tk.Tk()
        app = Desktop(root, folder/"settings.json")
        root.update()
        start = last = perf_counter()
        callbacks = 0
        worst_gap = 0.0

        def heartbeat():
            nonlocal last, callbacks, worst_gap
            now = perf_counter()
            worst_gap = max(worst_gap, now - last)
            callbacks += 1
            last = now
            if app.future is not None:
                root.after(25, heartbeat)
            else:
                root.quit()

        if args.trace:
            tracemalloc.start()
        try:
            app.scan(path)
            root.after(25, heartbeat)
            root.mainloop()
            elapsed = perf_counter() - start
            peak = tracemalloc.get_traced_memory()[1] if args.trace else None
            if args.trace:
                tracemalloc.stop()
            if app.summary is None or app.summary.matched != args.rows:
                raise RuntimeError(app.status.get())
            last_page = (args.rows - 1) // PAGE_SIZE
            paging_start = perf_counter()
            app.show_page(last_page, ("message", True))

            def check_page():
                if app.future is None:
                    root.quit()
                else:
                    root.after(10, check_page)

            root.after(10, check_page)
            root.mainloop()
            paging = perf_counter() - paging_start
            children = app.records.get_children()
            if app.page != last_page or app.records.set(children[-1], "message") != "Request 000000000 failed":
                raise RuntimeError("Incorrect globally sorted last page")
            print(json.dumps({
                "python": platform.python_version(), "os": platform.platform(), "rows": args.rows,
                "source_bytes": path.stat().st_size, "snapshot_bytes": app.db.stat().st_size,
                "scan_and_first_page_seconds": round(elapsed, 3), "tk_callbacks": callbacks,
                "max_callback_gap_ms": round(worst_gap * 1000, 1), "peak_traced_bytes": peak,
                "sorted_last_page_seconds": round(paging, 3), "last_page_rows": len(children),
            }, indent=2))
        finally:
            if args.trace:
                tracemalloc.stop()
            app.close()


if __name__ == "__main__":
    main()
