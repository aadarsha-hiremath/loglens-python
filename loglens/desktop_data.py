"""Disk-backed snapshots for desktop analysis. This module has no Tk dependency."""

import os
import sqlite3
import stat
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from threading import Event

from .analysis import Filters, Summary, matching_records
from .parsing import FAILURES, LEVELS, parse_timestamp

COLUMNS = ("timestamp", "level", "service", "message")
PAGE_SIZE = 100
MAX_TOP = 100


class Cancelled(Exception):
    """A snapshot or page request was cancelled."""


def make_filters(level: str, service: str, since: str, until: str, search: str) -> Filters:
    def names(value: str) -> frozenset[str]:
        return frozenset(x.strip() for x in value.split(",") if x.strip())

    selected = names(level.upper())
    if selected.difference(LEVELS):
        raise ValueError("Unknown severity. Choose a listed level or leave it blank for all.")
    try:
        start, end = (parse_timestamp(s.strip()) if s.strip() else None for s in (since, until))
    except ValueError as exc:
        raise ValueError("Use a timestamp with a timezone, for example 2026-01-15T09:00:00Z.") from exc
    if start and end and start > end:
        raise ValueError("Since must be earlier than or equal to Until.")
    return Filters(selected, names(service), start, end, search)


def _connection(db: Path, cancel: Event) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA cache_size=-2048")
    conn.execute("PRAGMA temp_store=FILE")
    conn.set_progress_handler(lambda: int(cancel.is_set()), 1000)
    return conn


def build_snapshot(source: Path, db: Path, filters: Filters, cancel: Event) -> Summary:
    """Build a disposable index. A cancelled/failed build is never published."""
    if not stat.S_ISREG(source.stat().st_mode):
        raise ValueError("Select a regular log file.")
    summary = Summary()
    with source.open("rb") as stream, closing(_connection(db, cancel)) as conn:
        initial = os.fstat(stream.fileno())

        def lines() -> Iterator[bytes]:
            for line in stream:
                if cancel.is_set():
                    raise Cancelled()
                yield line

        def rows() -> Iterator[tuple[str, str, str, str]]:
            for record in matching_records(lines(), filters, summary):
                summary.include(record, count_keys=False)
                # Fixed-width UTC strings sort chronologically.
                stamp = record.timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z")
                yield stamp, record.level, record.service, record.message

        conn.execute("DROP TABLE IF EXISTS records")
        conn.execute("CREATE TABLE records(timestamp TEXT, level TEXT, service TEXT, message TEXT)")
        with conn:
            conn.executemany("INSERT INTO records VALUES (?, ?, ?, ?)", rows())
        final = source.stat()
        if (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) != (
                final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise ValueError("The file changed during analysis. Refresh to read it again.")

        def top(column: str) -> Counter[str]:
            # Column names are constants; grouping and sorting can spill to disk.
            query = (f"SELECT {column}, COUNT(*) AS n FROM records WHERE level IN (?, ?) "
                     f"GROUP BY {column} ORDER BY n DESC, {column} ASC LIMIT ?")
            return Counter(dict(conn.execute(query, (*sorted(FAILURES), MAX_TOP))))

        summary.failing_services = top("service")
        summary.errors = top("message")
    if cancel.is_set():
        raise Cancelled()
    return summary


def read_page(db: Path, page: int, column: str, descending: bool, cancel: Event) -> list[tuple]:
    if page < 0 or column not in ("rowid", *COLUMNS):
        raise ValueError("Invalid explorer page or sort column.")
    direction = "DESC" if descending else "ASC"
    order_key = column
    parameters = []
    if column == "level":
        cases = " ".join(f"WHEN ? THEN {i}" for i in range(len(LEVELS)))
        order_key = f"CASE level {cases} END"
        parameters.extend(LEVELS)
    # Byte slicing also preserves embedded NUL. A partial final UTF-8 character
    # can only occur beyond the 512 displayed code points.
    projection = ", ".join(f"substr(CAST({c} AS BLOB), 1, 2052)" for c in COLUMNS)
    with closing(_connection(db, cancel)) as conn:
        cursor = conn.execute(
            f"SELECT {projection} FROM records ORDER BY {order_key} {direction}, rowid ASC "
            "LIMIT ? OFFSET ?", (*parameters, PAGE_SIZE, page * PAGE_SIZE),
        )
        return [tuple(preview(cell.decode("utf-8", "ignore")) for cell in row) for row in cursor]


def preview(text: str) -> str:
    return text if len(text) <= 512 else text[:512] + "…"
