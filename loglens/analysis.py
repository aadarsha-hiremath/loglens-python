"""Single-pass filtering and exact aggregation."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from heapq import nsmallest

from .parsing import FAILURES, LEVELS, Record, RecordError, parse_line


@dataclass(frozen=True, slots=True)
class Filters:
    levels: frozenset[str] = frozenset()
    services: frozenset[str] = frozenset()
    since: datetime | None = None
    until: datetime | None = None

    def matches(self, record: Record) -> bool:
        return (
            (not self.levels or record.level in self.levels)
            and (not self.services or record.service in self.services)
            and (self.since is None or record.timestamp >= self.since)
            and (self.until is None or record.timestamp <= self.until)
        )


@dataclass(slots=True)
class Summary:
    lines: int = 0
    matched: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    levels: Counter[str] = field(default_factory=lambda: Counter(dict.fromkeys(LEVELS, 0)))
    errors: Counter[str] = field(default_factory=Counter)
    failing_services: Counter[str] = field(default_factory=Counter)
    earliest: datetime | None = None
    latest: datetime | None = None

    def include(self, record: Record) -> None:
        self.matched += 1
        self.levels[record.level] += 1
        if self.earliest is None or record.timestamp < self.earliest:
            self.earliest = record.timestamp
        if self.latest is None or record.timestamp > self.latest:
            self.latest = record.timestamp
        if record.level in FAILURES:
            self.errors[record.message] += 1
            self.failing_services[record.service] += 1


def analyze(lines: Iterable[bytes], filters: Filters = Filters()) -> Summary:
    summary = Summary()
    for index, raw in enumerate(lines, start=1):
        summary.lines = index
        try:
            record = parse_line(raw, first_line=index == 1)
        except RecordError as exc:
            summary.rejected[str(exc)] += 1
            continue
        if filters.matches(record):
            summary.include(record)
    return summary


def ranked(counts: Counter[str], limit: int) -> list[tuple[str, int]]:
    """Return highest counts first with reproducible lexical tie-breaking."""
    return nsmallest(limit, counts.items(), key=lambda item: (-item[1], item[0]))
