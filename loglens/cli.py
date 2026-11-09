"""Command-line boundary for validation, file I/O and exit status."""

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from . import __version__
from .analysis import Filters, analyze
from .output import validate_output, write_text
from .parsing import LEVELS, RecordError, parse_timestamp
from .reporting import render


def _timestamp(value: str) -> datetime:
    try:
        return parse_timestamp(value)
    except RecordError as exc:
        raise argparse.ArgumentTypeError("expected a timestamp like 2026-01-15T09:00:00Z") from exc


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loglens", description="Analyze a UTF-8 log file in one pass.",
        epilog="Example: loglens examples/checkout.log --level ERROR --top 3",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("input", type=Path, metavar="FILE", help="path to the log file")
    parser.add_argument("--level", choices=LEVELS, type=str.upper, action="append",
                        help="include this severity (repeatable)")
    parser.add_argument("--service", action="append", help="include this exact service (repeatable)")
    parser.add_argument("--since", type=_timestamp, metavar="TIME", help="inclusive lower timestamp")
    parser.add_argument("--until", type=_timestamp, metavar="TIME", help="inclusive upper timestamp")
    parser.add_argument("--search", default="", help="case-insensitive message substring")
    parser.add_argument("--top", type=_positive, default=5, metavar="N",
                        help="maximum entries in each ranking (default: 5)")
    parser.add_argument("--format", choices=("text", "json", "html"), default="text",
                        help="report format (default: text)")
    parser.add_argument("-o", "--output", type=Path, help="write report to a file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.since and args.until and args.since > args.until:
        parser.error("--since must be earlier than or equal to --until")
    filters = Filters(frozenset(args.level or ()), frozenset(args.service or ()),
                      args.since, args.until, args.search)
    try:
        with args.input.open("rb") as lines:
            if args.output:
                try:
                    validate_output(args.output, args.input)
                except ValueError as exc:
                    parser.error(str(exc))
            summary = analyze(lines, filters)
        report = render(summary, args.format, args.top)
        if args.output:
            write_text(args.output, report)
        else:
            # Redirected Windows consoles may use a legacy encoding.
            encoding = sys.stdout.encoding or "utf-8"
            print(report.encode(encoding, "backslashreplace").decode(encoding))
            sys.stdout.flush()
    except (OSError, ValueError) as exc:
        print(f"loglens: {exc}", file=sys.stderr)
        return 1
    return 0
