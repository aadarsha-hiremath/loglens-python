"""SQLite snapshot, exact scoped statistics and bounded desktop record queries."""

import json
import os
import sqlite3
import stat
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .analysis import Filters, Summary, matching_records
from .output import validate_output
from .parsing import FAILURES, LEVELS, parse_timestamp

COLUMNS = ("timestamp", "level", "service", "message")
PAGE_SIZE = 100
MAX_TOP = 100


class Cancelled(Exception):
    """A worker request was superseded or cancelled."""


@dataclass(frozen=True)
class Scope:
    level: str = ""
    service: str = ""
    since: str = ""
    until: str = ""
    search: str = ""
    sensitive: bool = False

    def filters(self):
        return make_filters(self.level, self.service, self.since, self.until, self.search)

    def description(self):
        parts = [v for v in (self.level, self.service, self.since, self.until) if v]
        if self.search:
            parts.append(f"“{self.search}”" + (" (Aa)" if self.sensitive else ""))
        return " · ".join(parts) or "All valid records"


def make_filters(level, service, since, until, search):
    def names(value):
        return frozenset(x.strip() for x in value.split(",") if x.strip())

    selected = names(level.upper())
    if selected.difference(LEVELS):
        raise ValueError("Choose a listed severity.")
    try:
        start, end = (parse_timestamp(s.strip()) if s.strip() else None for s in (since, until))
    except ValueError as exc:
        raise ValueError("Use a time with a timezone, for example 2026-01-15T09:00:00Z.") from exc
    if start and end and start > end:
        raise ValueError("Start time must be earlier than or equal to end time.")
    return Filters(selected, names(service), start, end, search)


def connection(db, cancel):
    if cancel.is_set():
        raise Cancelled()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA cache_size=-2048")
    conn.execute("PRAGMA temp_store=FILE")
    conn.set_progress_handler(lambda: int(cancel.is_set()), 1000)
    return conn


def utc(stamp):
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def micros(stamp):
    delta = stamp - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def selection(scope):
    f = scope.filters()
    terms, args = [], []
    for field, values in (("level", f.levels), ("service", f.services)):
        if values:
            terms.append(f"{field} IN ({','.join('?' for _ in values)})")
            args.extend(sorted(values))
    for operator, bound in ((">=", f.since), ("<=", f.until)):
        if bound:
            terms.append(f"timestamp {operator} ?")
            args.append(utc(bound))
    if f.search:
        terms.append("instr(message, ?) > 0" if scope.sensitive else "instr(folded, ?) > 0")
        args.append(f.search if scope.sensitive else f.search.casefold())
    return " AND ".join(terms) or "1", args


def populate_ranks(conn, summary, where, args):
    for column, dest in (("service", "failing_services"), ("message", "errors")):
        query = (
            f"SELECT {column}, COUNT(*) AS n FROM records WHERE {where} AND level IN (?,?) "
            f"GROUP BY {column} ORDER BY n DESC, {column} LIMIT ?"
        )
        setattr(summary, dest, Counter(dict(conn.execute(query, (*args, *sorted(FAILURES), MAX_TOP)))))


def build_snapshot(source, db, filters, cancel, progress=lambda value: None):
    if not stat.S_ISREG(source.stat().st_mode):
        raise ValueError("Select a regular log file.")
    summary = Summary()
    with source.open("rb") as stream, closing(connection(db, cancel)) as conn:
        initial = os.fstat(stream.fileno())

        def lines():
            consumed = 0
            threshold = 0
            for line in stream:
                if cancel.is_set():
                    raise Cancelled()
                consumed += len(line)
                if consumed > initial.st_size:
                    raise ValueError("The file grew during analysis. Refresh to try again.")
                if consumed >= threshold:
                    progress(min(100, 100 * consumed // max(1, initial.st_size)))
                    threshold = consumed + max(65536, initial.st_size // 100)
                yield line

        def rows():
            for rec in matching_records(lines(), filters, summary):
                summary.include(rec, count_keys=False)
                yield (
                    summary.lines,
                    utc(rec.timestamp),
                    rec.level,
                    rec.service,
                    rec.message,
                    rec.message.casefold(),
                    micros(rec.timestamp),
                )

        conn.execute("DROP TABLE IF EXISTS records")
        conn.execute(
            "CREATE TABLE records(line INTEGER PRIMARY KEY, timestamp TEXT, level TEXT, "
            "service TEXT, message TEXT, folded TEXT, micros INTEGER)"
        )
        with conn:
            conn.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?)", rows())
        final = source.stat()
        if (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ):
            raise ValueError("The file changed during analysis. Refresh to try again.")
        progress(-1)
        for column in ("timestamp", "service", "level"):
            conn.execute(f"CREATE INDEX idx_{column} ON records({column})")
        populate_ranks(conn, summary, "1", [])
    return summary


def scoped_summary(db, base, scope, cancel):
    if scope == Scope():
        return base
    where, args = selection(scope)
    result = Summary(lines=base.lines, rejected=base.rejected.copy())
    with closing(connection(db, cancel)) as conn:
        query = f"SELECT level, COUNT(*), MIN(timestamp), MAX(timestamp) FROM records WHERE {where} GROUP BY level"
        for level, n, low, high in conn.execute(query, args):
            result.levels[level] = n
            result.matched += n
            first, last = parse_timestamp(low), parse_timestamp(high)
            result.earliest = min(result.earliest or first, first)
            result.latest = max(result.latest or last, last)
        populate_ranks(conn, result, where, args)
    return result


def timeline(db, summary, scope, cancel, bins=20):
    """Equal-duration UTC buckets of matched records and failures."""
    totals, failures = [0] * bins, [0] * bins
    if not summary.matched:
        return totals, failures
    where, args = selection(scope)
    low, high = micros(summary.earliest), micros(summary.latest)
    with closing(connection(db, cancel)) as conn:
        query = (
            f"SELECT min({bins - 1},(micros-?)*? / ?) AS bucket, "
            f"COUNT(*), SUM(level IN (?,?)) FROM records WHERE {where} GROUP BY bucket"
        )
        for bucket, n, f in conn.execute(query, (low, bins, max(1, high - low), *sorted(FAILURES), *args)):
            totals[bucket], failures[bucket] = n, f
    return totals, failures


def preview(text):
    return text if len(text) <= 512 else text[:512] + "…"


def page_rows(db, page, column, descending, cancel, scope=Scope(), size=PAGE_SIZE):
    if page < 0 or column not in ("rowid", *COLUMNS) or not 1 <= size <= 500:
        raise ValueError("Invalid page or sort order.")
    where, args = selection(scope)
    order = column
    if column == "level":
        order = "CASE level " + " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(LEVELS)) + " END"
    direction = "DESC" if descending else "ASC"
    projection = ", ".join(f"substr(CAST({c} AS BLOB), 1, 2052)" for c in COLUMNS)
    with closing(connection(db, cancel)) as conn:
        query = f"SELECT line, {projection} FROM records WHERE {where} ORDER BY {order} {direction}, line LIMIT ? OFFSET ?"
        return [
            (line, *(preview(t.decode("utf8", "ignore")) for t in cells))
            for line, *cells in conn.execute(query, (*args, size, page * size))
        ]


def read_page(db, page, column, descending, cancel):
    return [row[1:] for row in page_rows(db, page, column, descending, cancel)]


def records(db, ids, cancel):
    with closing(connection(db, cancel)) as conn:
        for line in ids:
            if cancel.is_set():
                raise Cancelled()
            row = conn.execute(
                "SELECT line,timestamp,level,service,message FROM records WHERE line=?", (line,)
            ).fetchone()
            if row:
                yield dict(zip(("line", *COLUMNS), row))


def export_selection(db, source, path, ids, cancel):
    validate_output(path, source)
    tmp = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            tmp = Path(stream.name)
            for record in records(db, ids, cancel):
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        if cancel.is_set():
            raise Cancelled()
        os.replace(tmp, path)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
