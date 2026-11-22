"""Run the Boolean signal regression in a disposable interpreter."""

import importlib.util
import subprocess
import sys
import unittest


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "install the gui extra to test Qt")
class QtRuntimeTests(unittest.TestCase):
    def test_boolean_signal_emissions_exit_cleanly(self):
        # A native reference-counting failure can abort after Python assertions pass.
        program = """
from PySide6.QtCore import QObject, Signal


class Probe(QObject):
    value_changed = Signal(bool)
    count = 0

    def record(self, value):
        if value is True:
            self.count += 1


probe = Probe()
probe.value_changed.connect(probe.record)
for _ in range(4000):
    probe.value_changed.emit(True)
assert probe.count == 4000, probe.count
"""
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", program],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
