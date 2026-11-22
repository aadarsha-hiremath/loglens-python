import json
import os
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from loglens.output import write_text

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "checkout.log"


def cli(*args):
    return subprocess.run([sys.executable, "-m", "loglens", *map(str, args)], cwd=ROOT,
                          capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})


class CliTests(unittest.TestCase):
    def test_sample_and_repeatable_flags(self):
        result = cli(SAMPLE, "--service", "inventory", "--service", "payments", "--level", "error",
                     "--level", "critical", "--until", "2026-01-15T09:00:06Z", "--format", "json", "--top", 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data["lines"], data["matched"], data["filtered_out"], data["malformed"]),
                         (10, 3, 6, 1))
        self.assertEqual(data["failure_percent"], 100.0)
        self.assertEqual(data["top_failing_services"], [{"service": "payments", "count": 2}])
        self.assertEqual(data["top_error_messages"], [{"message": "Upstream timeout", "count": 2}])

    def test_help_and_version(self):
        for flag, expected in [("--help", "--service"), ("--version", "loglens 0.3.0")]:
            result = cli(flag)
            self.assertEqual(result.returncode, 0)
            self.assertIn(expected, result.stdout)

    def test_argument_errors(self):
        for args in [("--since", "yesterday"), ("--top", "0"), ("--top", "abc"),
                     ("--level", "oops"), ("--format", "pdf"),
                     ("--since", "2026-01-02T00:00:00Z", "--until", "2026-01-01T00:00:00Z")]:
            with self.subTest(args=args):
                result = cli(SAMPLE, *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error:", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_io_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            for args in [(missing,), (SAMPLE, "-o", missing / "report.html")]:
                result = cli(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn("loglens:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_invalid_utf8_does_not_swallow_next_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.log"
            path.write_bytes(b"\xff\n2026-01-01T00:00:00Z | ERROR | api | ok")
            result = cli(path, "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["rejection_reasons"], {"invalid UTF-8": 1})
            self.assertEqual(data["matched"], 1)

    def test_writes_utf8_and_replaces_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "app.log", Path(tmp) / "report.html"
            path.write_text("2026-01-01T00:00:00Z | ERROR | api | cafÃ© & retry", encoding="utf-8")
            output.write_text("stale", encoding="utf-8")
            result = cli(path, "--format", "html", "-o", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("cafÃ© &amp; retry", output.read_text(encoding="utf-8"))

    def test_redirected_html_is_utf8_with_a_legacy_stdout_encoding(self):
        class MessageCells(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_cell = False
                self.cells = []
                self.tags = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                if tag == "th":
                    self.in_cell = True
                    self.cells.append("")

            def handle_endtag(self, tag):
                if tag == "th":
                    self.in_cell = False

            def handle_data(self, data):
                if self.in_cell:
                    self.cells[-1] += data

        messages = [
            "ASCII message", "caf\u00e9", "\u0c95\u0ca8\u0ccd\u0ca8\u0ca1",
            "\u96ea", "\U0001f680", """<script> & \'single\' "double" \u00e9 \u0c95 \U0001f680""",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.log"
            path.write_text(
                "".join(f"2026-01-01T00:00:00Z | ERROR | api | {message}\n" for message in messages),
                encoding="utf8",
            )
            result = subprocess.run(
                [sys.executable, "-m", "loglens", str(path), "--format", "html", "--top", "10"],
                cwd=ROOT, capture_output=True, check=True,
                env={**os.environ, "PYTHONIOENCODING": "cp1252"},
            )
        self.assertEqual(result.stderr, b"")
        html = result.stdout.decode("utf8", errors="strict")
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertTrue(html.endswith("</html>\n"))
        self.assertIn('<meta charset="utf-8">', html)
        self.assertIn("&lt;script&gt; &amp; &#x27;single&#x27; &quot;double&quot;", html)
        parsed = MessageCells()
        parsed.feed(html)
        self.assertNotIn("script", parsed.tags)
        for message in messages:
            self.assertIn(message, parsed.cells)

    def test_refuses_input_as_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.log"
            path.write_bytes(b"original")
            result = cli(path, "-o", path)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_bytes(), b"original")

    def test_failed_replacement_preserves_report_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report"
            path.write_bytes(b"previous")
            with patch("loglens.output.os.replace", side_effect=PermissionError), self.assertRaises(PermissionError):
                write_text(path, "new")
            self.assertEqual(path.read_bytes(), b"previous")
            self.assertEqual(list(Path(tmp).iterdir()), [path])
