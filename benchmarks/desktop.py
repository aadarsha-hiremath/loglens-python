"""Measure scan, search, event dispatch, and Qt table paints in a real desktop window."""

import argparse
import ctypes
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from loglens.desktop_window import Window

PERIOD = 1 / 60


def intervals(times):
    gaps = [b - a for a, b in zip(times, times[1:])]
    if not gaps:
        return {}
    return {
        "events": len(times),
        "median_ms": round(statistics.median(gaps) * 1000, 1),
        "max_ms": round(max(gaps) * 1000, 1),
        "gaps_over_33ms": sum(g > 2 * PERIOD for g in gaps),
        "estimated_missed_slots": sum(max(0, round(g / PERIOD) - 1) for g in gaps),
    }


def working_set():
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    class Memory(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("faults", wintypes.DWORD),
            *((k, ctypes.c_size_t) for k in ("peak", "working", "a", "b", "c", "d", "e", "f")),
        ]

    counter = Memory()
    counter.size = ctypes.sizeof(counter)
    handle = ctypes.windll.kernel32.GetCurrentProcess
    handle.restype = wintypes.HANDLE
    measure = ctypes.windll.psapi.GetProcessMemoryInfo
    measure.argtypes = (wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD)
    return counter.peak if measure(handle(), ctypes.byref(counter), counter.size) else None


class Paints(QObject):
    def __init__(self):
        super().__init__()
        self.times = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.times.append(time.perf_counter())
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--unique", action="store_true", help="one distinct error message per row")
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("rows must be positive")
    app = QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        source = base / "generated.log"
        with source.open("w", encoding="utf8", newline="\n") as stream:
            for i in range(args.rows):
                group = "Retry" if i % 2 else "Timeout"
                msg = f"{group} request {i if args.unique else i % 6:08d}"
                stream.write(
                    f"2026-01-15T09:{i // 60 % 60:02}:{i % 60:02}Z | ERROR | worker-{i % 7} | {msg}\n"
                )
        w = Window(base / "settings.json")
        w.resize(1180, 730)
        w.show()
        app.processEvents()
        beats = []
        timer = QTimer(timerType=Qt.TimerType.PreciseTimer, interval=16)
        timer.timeout.connect(lambda: beats.append(time.perf_counter()))
        timer.start()

        def wait():
            end = time.perf_counter() + 90
            while w.jobs.active or w.reader.active:
                app.processEvents()
                time.sleep(0.001)
                if time.perf_counter() > end:
                    raise RuntimeError("Worker timeout")

        try:
            start = time.perf_counter()
            beats.clear()
            beats.append(start)
            w.load_file(source)
            wait()
            scan = time.perf_counter() - start
            assert w.full.matched == args.rows, w.status.text()
            beats.append(time.perf_counter())
            scan_dispatch = intervals(beats)
            w.navigate("Log explorer")
            w.ex.size.setCurrentText("500")
            wait()
            w.ex.search.setText("Retry")
            start = time.perf_counter()
            w.apply_filters()
            wait()
            search = time.perf_counter() - start
            assert w.filtered.matched == args.rows // 2
            beats.clear()
            paints = Paints()
            viewport = w.ex.table.viewport()
            viewport.installEventFilter(paints)
            bar = w.ex.table.verticalScrollBar()
            loop = QEventLoop()
            frames = 0

            def scroll():
                nonlocal frames
                bar.setValue((bar.value() + 13) % (bar.maximum() + 1))
                frames += 1
                if frames >= 120:
                    loop.quit()

            scrolling = QTimer(timerType=Qt.TimerType.PreciseTimer, interval=16)
            scrolling.timeout.connect(scroll)
            scrolling.start()
            loop.exec()
            scrolling.stop()
            viewport.removeEventFilter(paints)
            scroll_dispatch = intervals(beats)
            beats.clear()
            for i in range(8):
                w.navigate(("Dashboard", "Log explorer")[i % 2])
                until = time.perf_counter() + 0.17
                while time.perf_counter() < until:
                    app.processEvents()
                    time.sleep(0.001)
            print(
                json.dumps(
                    dict(
                        python=platform.python_version(),
                        qt=qt_version,
                        os=platform.platform(),
                        rows=args.rows,
                        unique=args.unique,
                        scan_s=round(scan, 3),
                        search_s=round(search, 3),
                        disk_bytes=w.db.stat().st_size,
                        peak_working_set=working_set(),
                        scan_dispatch=scan_dispatch,
                        scroll_dispatch=scroll_dispatch,
                        scroll_paints=intervals(paints.times),
                        navigation_dispatch=intervals(beats),
                    ),
                    separators=(",", ":"),
                )
            )
        finally:
            timer.stop()
            w.close()


if __name__ == "__main__":
    main()
