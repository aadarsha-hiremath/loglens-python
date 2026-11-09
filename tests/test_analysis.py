import unittest
from collections import Counter

from loglens.analysis import Filters, analyze, ranked
from loglens.parsing import parse_timestamp


ROWS = (
    b"2026-02-28T12:00:02Z | ERROR | api | timeout\n",
    b"broken\n",
    b"2026-02-28T13:00:01+01:00 | CRITICAL | db | timeout\n",
    b"2026-02-28T12:00:01Z | INFO | db | ready\n",
    b"2026-02-28T12:00:03Z | ERROR | db | stopped",
)


class AnalysisTests(unittest.TestCase):
    def test_unsorted_stream_and_cross_service_errors(self):
        result = analyze(iter(ROWS))
        self.assertEqual((result.lines, result.matched, result.rejected.total()), (5, 4, 1))
        self.assertEqual(result.failing_services, {"db": 2, "api": 1})
        self.assertEqual(result.errors, {"timeout": 2, "stopped": 1})
        self.assertEqual(result.levels["DEBUG"], 0)
        self.assertEqual(result.earliest, parse_timestamp("2026-02-28T12:00:01Z"))
        self.assertEqual(result.latest, parse_timestamp("2026-02-28T12:00:03Z"))

    def test_filters_intersect_and_bounds_are_inclusive(self):
        instant = parse_timestamp("2026-02-28T12:00:01Z")
        result = analyze(ROWS, Filters(frozenset({"CRITICAL", "ERROR"}), frozenset({"db"}),
                                       since=instant, until=instant))
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.levels["CRITICAL"], 1)
        self.assertEqual(result.rejected.total(), 1)

    def test_one_sided_and_case_sensitive_filters(self):
        end = parse_timestamp("2026-02-28T12:00:02Z")
        self.assertEqual(analyze(ROWS, Filters(since=end)).matched, 2)
        self.assertEqual(analyze(ROWS, Filters(until=end)).matched, 3)
        self.assertEqual(analyze(ROWS, Filters(services=frozenset({"DB"}))).matched, 0)

    def test_empty_and_all_malformed(self):
        for rows in ([], [b"\n", b"\xff\n"]):
            with self.subTest(rows=rows):
                result = analyze(rows)
                self.assertIsNone(result.earliest)
                self.assertIsNone(result.latest)
                self.assertEqual(result.matched, 0)
                self.assertEqual(result.rejected.total(), len(rows))

    def test_ranking_ties_and_limit(self):
        counts = Counter({"db": 5, "api": 5, "web": 2})
        self.assertEqual(ranked(counts, 1), [("api", 5)])
        self.assertEqual(ranked(counts, 10), [("api", 5), ("db", 5), ("web", 2)])
