"""Exercise real Tk widgets when the host provides a display."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, "Tk unavailable")
class WindowTests(unittest.TestCase):
    def setUp(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        from loglens.gui import Desktop
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.prefs = self.folder/"prefs.json"
        self.app = Desktop(root, self.prefs)
        self.root = root
        self.root.update()
        self.assertGreater(self.app.split.sashpos(0), 100)
        self.addCleanup(self.shutdown)
        self.sample = Path(__file__).resolve().parents[1]/"examples/checkout.log"

    def shutdown(self):
        self.wait()
        self.app.close()

    def wait(self):
        deadline = time.monotonic() + 15
        while self.app.future is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)
        self.assertIsNone(self.app.future, "worker timed out")

    def test_open_apply_export_refresh_and_failed_input(self):
        app = self.app
        with patch("tkinter.filedialog.askopenfilename", return_value=str(self.sample)):
            app.open_btn.invoke()
        self.wait()
        self.assertEqual(app.metrics["matched"].get(), "9")
        app.inputs["service"].set("payments")
        app.apply_btn.invoke()
        self.wait()
        self.assertEqual(app.metrics["filtered_out"].get(), "6")
        self.assertEqual(len(app.records.get_children()), 3)
        for fmt in ("json", "html"):
            dest = self.folder/f"report.{fmt}"
            with patch("tkinter.filedialog.asksaveasfilename", return_value=str(dest)):
                app.export(fmt)
            self.wait()
            self.assertTrue(dest.is_file())
            self.assertIn("Saved", app.status.get())
        with patch("tkinter.filedialog.asksaveasfilename", return_value=str(self.sample)):
            app.export("html")
        self.wait()
        self.assertIn("different files", app.status.get())
        app.clear_btn.invoke()
        self.wait()
        app.refresh_btn.invoke()
        self.wait()
        self.assertEqual(app.metrics["matched"].get(), "9")
        app.scan(self.folder/"missing")
        self.wait()
        self.assertIn("Could not complete", app.status.get())
        self.assertIn("disabled", app.export_btn.state())

    def test_preferences_page_sort_and_cancellation(self):
        app = self.app
        source = self.folder/"many.log"
        source.write_bytes(b"2026-01-01T00:00:00Z | ERROR | api | retry\n" * 234)
        app.scan(source)
        app.scan(self.sample)
        self.wait()
        self.assertEqual(app.source, source)
        app.tabs.select(1)
        app.next_btn.invoke()
        self.wait()
        self.assertIn("101–200 of 234", app.page_text.get())
        app.page_number.set("999")
        app.go_btn.invoke()
        self.assertIn("1 to 3", app.status.get())
        app.page_number.set("3")
        app.go_btn.invoke()
        self.wait()
        self.assertIn("201–234", app.page_text.get())
        app.sort_by("message")
        self.wait()
        self.assertEqual(app.page, 0)
        app.sort_by("message")
        self.wait()
        self.assertEqual(app.sort, ("message", True))
        app.settings_btn.invoke()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        controls = dialog.winfo_children()[0].winfo_children()
        combos = [w for w in controls if isinstance(w, ttk.Combobox)]
        combos[0].set("Dark")
        combos[1].set("12")
        next(w for w in controls if isinstance(w, ttk.Spinbox)).set("1")
        next(w for w in controls if isinstance(w, ttk.Checkbutton)).invoke()
        actions = next(w for w in controls if isinstance(w, ttk.Frame))
        next(w for w in actions.winfo_children() if w.cget("text") == "Apply").invoke()
        self.assertEqual(app.prefs.theme, "Dark")
        self.assertEqual(app.prefs.columns, ("level","service","message"))
        self.assertTrue(self.prefs.is_file())
        app.scan(source)
        app.cancel_btn.invoke()
        self.wait()
        self.assertEqual(app.status.get(), "Cancelled.")
        app.settings_btn.invoke()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        actions = next(w for w in dialog.winfo_children()[0].winfo_children() if isinstance(w, ttk.Frame))
        next(w for w in actions.winfo_children() if w.cget("text") == "Reset to defaults").invoke()
        self.assertEqual(app.prefs.theme, "Light")
        self.assertEqual(len(app.prefs.columns), 4)
