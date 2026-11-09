import json
import unittest
from html.parser import HTMLParser

from loglens.analysis import analyze
from loglens.reporting import render


class CellReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


class ReportTests(unittest.TestCase):
    def test_html_treats_markup_as_text(self):
        message = """<script>alert("x" & 'y')</script>"""
        summary = analyze([f"2026-01-01T00:00:00Z | ERROR | cart | {message}".encode()])
        html = render(summary, "html", 5)
        parser = CellReader()
        parser.feed(html)
        self.assertIn(message, parser.text)
        self.assertNotIn("script", parser.tags)
        self.assertIn("&amp;", html)

    def test_terminal_escapes_controls_json_round_trips_them(self):
        message = "timeout\x1b[2J\u202e"
        summary = analyze([f"2026-01-01T00:00:00Z | ERROR | cart | {message}".encode()])
        report = render(summary, "text", 5)
        self.assertNotIn("\x1b", report)
        self.assertNotIn("\u202e", report)
        self.assertEqual(json.loads(render(summary, "json", 5))["top_error_messages"],
                         [{"message": message, "count": 1}])

    def test_empty_report(self):
        summary = analyze([])
        data = json.loads(render(summary, "json", 1))
        self.assertIsNone(data["failure_percent"])
        self.assertIsNone(data["latest_utc"])
        self.assertEqual(data["top_failing_services"], [])
        self.assertIn("(none)", render(summary, "text", 1))
        self.assertIn("<p>None</p>", render(summary, "html", 1))
