"""Native Qt interaction and restart tests (GUI extra; works with Qt offscreen)."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog
    from loglens.desktop_window import Window
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    Window = None

from loglens.desktop_data import Scope
from loglens.preferences import Preferences

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/checkout.log"


@unittest.skipUnless(Window, "install the gui extra to run window tests")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / "settings.json"
        self.window = Window(self.path)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(lambda: self.window.close())

    def wait(self):
        w = self.window
        deadline = time.monotonic() + 15
        while w.jobs.active or w.reader.active or w.search_timer.isActive():
            self.app.processEvents()
            time.sleep(0.002)
            self.assertLess(time.monotonic(), deadline)
        self.app.processEvents()

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def test_open_apply_export_refresh_and_failed_input(self):
        w = self.window
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(SAMPLE), "")):
            self.click(w.open_btn)
        self.wait()
        self.assertEqual(w.full.matched, 9)
        w.navigate("Log explorer")
        self.click(w.ex.filters)
        w.ex.fields["service"].setText("payments")
        self.click(w.ex.apply)
        self.wait()
        self.assertEqual(w.filtered.matched, 3)
        self.assertEqual(w.full.matched, 9)
        for fmt in ("json", "html"):
            path = self.folder / ("filtered." + fmt)
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                w.export(fmt, True)
            self.wait()
            cli = subprocess.check_output(
                [sys.executable, "-m", "loglens", SAMPLE, "--service", "payments", "--format", fmt],
                cwd=ROOT,
                encoding="utf8",
                env={**os.environ, "PYTHONIOENCODING": "utf8"},
            )
            self.assertEqual(path.read_text(encoding="utf8"), cli)
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(SAMPLE), "")):
            w.export("json")
        self.wait()
        self.assertIn("different files", w.status.text())
        self.click(w.ex.clear)
        self.wait()
        self.click(w.refresh)
        self.wait()
        self.assertEqual(w.ex.model.rowCount(), 9)
        w.load_file(self.folder / "missing.log")
        self.wait()
        self.assertEqual(w.source, SAMPLE)
        self.assertIn("missing", w.status.text())
        w.load_file(self.folder / "bad.zip")
        self.assertIn(".log", w.status.text())

    def test_paging_sort_cancel_and_latest_query_wins(self):
        w = self.window
        log = self.folder / "many.log"
        stamp = "2026-01-01T00:00:00Z | ERROR | api | "
        log.write_text("".join(f"{stamp}{i:05d} {'Alpha' if i % 2 else 'Beta'}\n" for i in range(1234)))
        w.load_file(log)
        self.wait()
        w.navigate("Log explorer")
        self.click(w.ex.next)
        self.wait()
        self.assertEqual(w.ex.model.rows[0][0], 101)
        w.ex.page.setValue(5)
        self.wait()
        self.assertEqual(w.page_index, 4)
        w.sort(3)
        self.wait()
        w.sort(3)
        self.wait()
        self.assertEqual(w.ex.model.rows[0][0], 1234)
        w.ex.search.setText("Alpha")
        w.apply_filters()
        w.ex.search.setText("Beta")
        w.apply_filters()
        self.wait()
        self.assertEqual(w.filtered.matched, 617)
        self.assertTrue(all(row[-1].endswith("Beta") for row in w.ex.model.rows))
        w.load_file(SAMPLE)
        w.cancel_work()
        self.wait()
        self.assertEqual(w.source, log)
        self.assertEqual(w.status.text(), "Cancelled")

    def test_full_inspector_clipboard_export_and_drop(self):
        w = self.window
        path = self.folder / "worker.log"
        msg = "<trial> " + "Ü" * 19000
        service = "jobs-" + "a" * 9500
        path.write_text(
            "broken\n2026-01-01T00:00:00Z | ERROR | " + service + " | " + msg + "\n", encoding="utf8"
        )
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        w.dropEvent(event)
        self.wait()
        self.assertTrue(event.isAccepted())
        w.navigate("Log explorer")
        w.ex.table.selectRow(0)
        self.wait()
        self.assertEqual(w.ex.record["line"], 2)
        self.assertEqual(w.ex.record["message"], msg)
        self.assertEqual(len(w.ex.model.rows[0][-1]), 513)
        self.click(w.ex.forward)
        self.assertEqual(w.ex.message.toPlainText(), msg[8192:16384])
        w.ex.field.setCurrentIndex(1)
        self.click(w.ex.forward)
        self.assertEqual(w.ex.message.toPlainText(), service[8192:])
        self.click(w.ex.copy_msg)
        self.wait()
        self.assertEqual(self.app.clipboard().text(), msg)
        out = self.folder / "selected.jsonl"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(out), "")):
            self.click(w.ex.selected_export)
        self.wait()
        self.assertEqual(json.loads(out.read_text(encoding="utf8")), w.ex.record)

    def test_search_case_inclusive_and_zero_match(self):
        w = self.window
        w.load_file(SAMPLE)
        self.wait()
        w.ex.set_scope(
            Scope("ERROR", "payments", "2026-01-15T09:00:02Z", "2026-01-15T09:00:04Z", "TIMEOUT")
        )
        w.apply_filters()
        self.wait()
        self.assertEqual(w.filtered.matched, 2)
        w.ex.case.setChecked(True)
        self.wait()
        self.assertEqual(w.filtered.matched, 0)
        w.dashboard.scope.setCurrentIndex(1)
        self.assertEqual(w.dashboard.cards[3][1].text(), "n/a")
        w.ex.fields["since"].setText("bad date")
        w.apply_filters()
        self.assertIn("timezone", w.status.text())

    def test_persistence_presets_recent_and_reset(self):
        w = self.window
        w.load_file(SAMPLE)
        self.wait()
        w.navigate("Settings")
        for theme in ("Light", "Dark", "Light"):
            w.settings.controls["theme"].setCurrentText(theme)
        w.settings.controls["density"].setCurrentText("Compact")
        w.settings.controls["motion"].setCurrentText("Off")
        w.settings.controls["reduced"].setChecked(True)
        w.settings.controls["font_size"].setValue(12)
        w.settings.controls["top"].setValue(7)
        w.settings.columns["service"].setChecked(False)
        w.navigate("Log explorer")
        w.ex.table.setColumnWidth(0, 280)
        w.ex.table.horizontalHeader().moveSection(3, 1)
        w.ex.size.setCurrentText("250")
        self.wait()
        w.sort(2)
        self.wait()
        w.ex.set_scope(Scope(level="ERROR", service="payments"))
        w.apply_filters()
        self.wait()
        with patch.object(QInputDialog, "getText", return_value=("Payment errors", True)):
            w.save_preset()
            w.ex.fields["service"].setText("inventory")
            with patch.object(w, "confirm", return_value=True):
                w.save_preset()
        w.ex.inspect.setChecked(False)
        w.ex.filters.setChecked(True)
        w.resize(1080, 680)
        w.move(34, 40)
        QTest.qWait(450)
        self.assertEqual(w.saved.text(), "Settings saved")
        p = Preferences.load(self.path)
        self.assertEqual(p.recent, [str(SAMPLE)])
        self.assertEqual(p.presets["Payment errors"].service, "inventory")
        self.assertEqual((p.width, p.height, p.widths["timestamp"]), (1080, 680, 280))
        self.assertEqual((p.sort, p.order[1], p.page_size), ("service", "message", 250))
        w.close()
        self.window = w = Window(self.path)
        w.show()
        self.app.processEvents()
        self.assertEqual(w.prefs.theme, "Light")
        self.assertEqual(w.prefs.font_size, 12)
        self.assertEqual(w.prefs.top, 7)
        self.assertEqual(w.prefs.view, "Log explorer")
        self.assertTrue(w.ex.table.isColumnHidden(2))
        self.assertFalse(w.ex.inspect.isChecked())
        self.assertEqual(w.ex.scope().service, "payments")
        w.ex.preset.setCurrentText("Payment errors")
        w.apply_preset(1)
        self.assertEqual(w.ex.scope().service, "inventory")
        with patch.object(w, "confirm", return_value=True):
            w.delete_preset()
            w.clear_history()
            self.assertFalse(w.prefs.presets)
            self.assertFalse(w.prefs.recent)
            w.reset()
        self.assertEqual(w.prefs.theme, Preferences().theme)

    def test_clean_restart_and_save_failure(self):
        w = self.window
        self.assertIsNone(w.source)
        w.prefs.theme = "Light"
        with patch.object(Preferences, "save", side_effect=PermissionError("denied")):
            w.save()
        self.assertEqual(w.saved.text(), "Save failed")
        w.close()
        self.path.write_text('{"version":999}', encoding="utf8")
        self.window = w = Window(self.path)
        w.show()
        w.dirty()
        w.save()
        self.assertTrue(w.settings_issue)
        self.assertEqual(self.path.read_text(), '{"version":999}')

    def test_restore_in_independent_process(self):
        w = self.window
        w.preference("density", "Comfortable")
        w.navigate("Log explorer")
        w.close()
        check = """import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from loglens.desktop_window import Window
app=QApplication([])
win=Window(Path(sys.argv[1]))
assert win.prefs.view=='Log explorer' and win.ex.table.verticalHeader().defaultSectionSize()>=42
win.close()
"""
        subprocess.run(
            [sys.executable, "-c", check, str(self.path)],
            cwd=ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            check=True,
        )
