import unittest
from datetime import UTC, datetime

from loglens.parsing import RecordError, parse_line, parse_timestamp


class ParsingTests(unittest.TestCase):
    def test_preserves_message_with_delimiter_and_unicode(self):
        raw = "2026-03-04T01:02:03Z | INFO | api.v2-1 | café | done  \r\n".encode()
        record = parse_line(raw)
        self.assertEqual((record.service, record.level, record.message),
                         ("api.v2-1", "INFO", "café | done  "))

    def test_fraction_offset_and_day_rollover(self):
        self.assertEqual(parse_timestamp("2024-03-01T00:30:00.1+02:00"),
                         datetime(2024, 2, 29, 22, 30, 0, 100000, UTC))

    def test_bom_only_at_start(self):
        raw = b"\xef\xbb\xbf2026-03-04T01:02:03Z | INFO | cart | saved"
        self.assertEqual(parse_line(raw, first_line=True).message, "saved")
        with self.assertRaisesRegex(RecordError, "invalid timestamp"):
            parse_line(raw)

    def test_invalid_timestamps(self):
        for stamp in ("2026-02-29T00:00:00Z", "2026-01-01", "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00+01:60", "2026-01-01T00:00:00+24:00",
                      "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00",
                      "2026-01-01T00:00:00.1234567Z", "2026-01-01T25:01:00Z"):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(RecordError, "invalid timestamp"):
                parse_timestamp(stamp)

    def test_rejection_categories(self):
        for tail, reason in [
            (b"INFO | cart | \xff", "invalid UTF-8"), (b"INFO | cart", "expected four fields"),
            (b"info | cart | ok", "unknown level"), (b"ERROR | two words | no", "invalid service"),
            (b"ERROR | cart |  \t", "empty message"),
        ]:
            with self.subTest(tail=tail), self.assertRaisesRegex(RecordError, reason):
                parse_line(b"2026-03-04T01:02:03Z | " + tail)
