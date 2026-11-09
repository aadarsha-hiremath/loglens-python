import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from loglens.analysis import Filters
from loglens.desktop_data import MAX_TOP, PAGE_SIZE, Cancelled, build_snapshot, make_filters, read_page
from loglens.preferences import Preferences
from loglens.reporting import render

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/checkout.log"
STAMP = b"2026-01-15T09:00:00Z"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.db = self.folder / "index"
        self.event = Event()

    def test_cli_and_snapshot_reports_are_identical(self):
        cases = [
            (("", "", "", "", ""), []),
            (("ERROR,CRITICAL", "payments,inventory", "2026-01-15T09:00:02Z", "2026-01-15T09:00:06Z", "TiMe"),
             ["--level", "error", "--level", "critical", "--service", "payments", "--service", "inventory",
              "--since", "2026-01-15T09:00:02Z", "--until", "2026-01-15T09:00:06Z", "--search", "TiMe"]),
            (("", "nobody", "", "", ""), ["--service", "nobody"]),
        ]
        for fields, args in cases:
            with self.subTest(fields=fields):
                summary = build_snapshot(SAMPLE, self.db, make_filters(*fields), self.event)
                for fmt in ("json", "html", "text"):
                    cli = subprocess.check_output([sys.executable, "-m", "loglens", SAMPLE, *args,
                        "--format", fmt, "--top", "2"], cwd=ROOT, encoding="utf8",
                        env={**os.environ, "PYTHONIOENCODING":"utf-8"})
                    self.assertEqual(cli, render(summary, fmt, 2) + "\n")

    def test_global_sort_complete_pages_stable_ties_and_rank_limit(self):
        src = self.folder / "input.log"
        total = 2 * PAGE_SIZE + 7
        src.write_bytes(b"".join(STAMP + f" | ERROR | api | retry {n:04d}\n".encode()
                                 for n in reversed(range(total))))
        summary = build_snapshot(src, self.db, Filters(), self.event)
        self.assertEqual(len(summary.errors), MAX_TOP)
        self.assertEqual(summary.matched, total)
        rows = [row for p in range(3) for row in read_page(self.db, p, "message", False, self.event)]
        self.assertEqual([r[-1] for r in rows], [f"retry {n:04d}" for n in range(total)])
        self.assertEqual(read_page(self.db, 0, "service", False, self.event)[0][-1], rows[-1][-1])
        self.assertEqual(read_page(self.db, 0, "message", True, self.event)[0][-1], rows[-1][-1])

    def test_empty_malformed_and_cancel(self):
        src = self.folder / "input.log"
        for data, rejected in ((b"", 0), (b"\xff\nbroken\n", 2)):
            src.write_bytes(data)
            summary = build_snapshot(src, self.db, Filters(), self.event)
            self.assertEqual(summary.rejected.total(), rejected)
            self.assertEqual(summary.matched, 0)
            self.assertEqual(read_page(self.db, 0, "rowid", False, self.event), [])
        self.event.set()
        with self.assertRaises(Cancelled):
            build_snapshot(src, self.db, Filters(), self.event)

    def test_utc_sort_and_unicode_preview(self):
        path = self.folder / "input.log"
        msg = "abc\0" + "界" * 600
        path.write_text(f"2026-01-15T09:00:00.1Z | ERROR | web | {msg}\n"
                        "2026-01-15T10:00:00+01:00 | INFO | web | saved", encoding="utf8")
        summary = build_snapshot(path, self.db, Filters(), self.event)
        rows = read_page(self.db, 0, "timestamp", False, self.event)
        self.assertEqual(rows[0][-1], "saved")
        self.assertEqual(rows[1][-1], msg[:512] + "…")
        self.assertIn(msg, summary.errors)
        self.assertEqual(read_page(self.db, 0, "level", False, self.event)[0][1], "INFO")
        self.assertEqual(read_page(self.db, 0, "level", True, self.event)[0][1], "ERROR")

    def test_unreadable_source_and_snapshot_after_rotation(self):
        src = self.folder / "test.log"
        src.write_bytes(STAMP + b" | INFO | api | first")
        with patch.object(Path, "open", side_effect=PermissionError("access denied")):
            with self.assertRaises(PermissionError):
                build_snapshot(src, self.db, Filters(), self.event)
        build_snapshot(src, self.db, Filters(), self.event)
        src.write_bytes(STAMP + b" | ERROR | api | second")
        self.assertEqual(read_page(self.db, 0, "rowid", False, self.event)[0][-1], "first")
        build_snapshot(src, self.db, Filters(), self.event)
        self.assertEqual(read_page(self.db, 0, "rowid", False, self.event)[0][-1], "second")

    def test_export_guard_after_input_is_removed(self):
        from loglens.output import validate_output
        source = self.folder / "gone.log"
        previous = self.folder / "report.html"
        previous.touch()
        validate_output(previous, source)
        with self.assertRaisesRegex(ValueError, "different files"):
            validate_output(source, source)

    def test_invalid_inputs_and_sort(self):
        for values in (("TYPO","","","",""), ("","","yesterday","",""),
                       ("","","2026-01-02T00:00:00Z","2026-01-01T00:00:00Z","")):
            with self.assertRaises(ValueError):
                make_filters(*values)
        with self.assertRaises(OSError):
            build_snapshot(self.folder/"missing", self.db, Filters(), self.event)
        with self.assertRaises(ValueError):
            build_snapshot(self.folder, self.db, Filters(), self.event)
        with self.assertRaises(ValueError):
            read_page(self.db, 0, "unknown", False, self.event)

    def test_preferences_round_trip_and_recovery(self):
        path = self.folder/"user"/"desktop.json"
        prefs = Preferences(theme="Dark", columns=("level",), font_size=14, top=9, sash=300)
        prefs.widths["level"] = 193
        prefs.save(path)
        self.assertEqual(Preferences.load(path), prefs)
        path.write_text("not JSON", encoding="utf8")
        self.assertEqual(Preferences.load(path), Preferences())
        path.write_text(json.dumps({"font_size":999,"columns":["bogus"],"widths":{"level":-2}}))
        self.assertEqual(Preferences.load(path), Preferences())
