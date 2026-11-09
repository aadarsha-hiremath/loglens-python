"""Render the same analysis in text, HTML, or machine-readable JSON."""

import json
from collections.abc import Iterable
from datetime import datetime
from html import escape

from .analysis import Summary, ranked


def _utc(stamp: datetime | None) -> str | None:
    return stamp.isoformat().replace("+00:00", "Z") if stamp else None


def _visible(value: str) -> str:
    # Escape terminal controls, bidi overrides and embedded line separators.
    return "".join(char if char.isprintable() else ascii(char)[1:-1] for char in value)


def render(summary: Summary, fmt: str, limit: int) -> str:
    malformed = summary.rejected.total()
    failures = summary.levels["ERROR"] + summary.levels["CRITICAL"]
    rate = round(100 * failures / summary.matched, 2) if summary.matched else None
    services = ranked(summary.failing_services, limit)
    errors = ranked(summary.errors, limit)
    reasons = sorted(summary.rejected.items())
    first, last = _utc(summary.earliest), _utc(summary.latest)
    if fmt == "json":
        return json.dumps({
            "lines": summary.lines, "malformed": malformed,
            "filtered_out": summary.lines - malformed - summary.matched,
            "matched": summary.matched, "failures": failures,
            "failure_percent": rate, "earliest_utc": first, "latest_utc": last,
            "levels": dict(summary.levels), "rejection_reasons": dict(reasons),
            "top_failing_services": [{"service": s, "count": n} for s, n in services],
            "top_error_messages": [{"message": m, "count": n} for m, n in errors],
        }, indent=2)

    totals = [
        ("Lines read", str(summary.lines)), ("Malformed", str(malformed)),
        ("Filtered out", str(summary.lines - malformed - summary.matched)),
        ("Matched", str(summary.matched)), ("Failures", str(failures)),
        ("Failure rate", f"{rate:.2f}%" if rate is not None else "n/a"),
        ("Earliest UTC", first or "n/a"), ("Latest UTC", last or "n/a"),
    ]
    sections: list[tuple[str, Iterable[tuple[str, int | str]]]] = [
        ("Overview", totals), ("Severity", summary.levels.items()),
        ("Top failing services", services), ("Top error messages", errors),
        ("Rejected lines by reason", reasons),
    ]
    if fmt == "text":
        blocks = ["LogLens report"]
        for title, rows in sections:
            body = "\n".join(f"  {_visible(label)}  {value}" for label, value in rows)
            blocks.append(f"{title}\n{body or '  (none)'}")
        return "\n\n".join(blocks)
    if fmt != "html":
        raise ValueError(f"unknown report format {fmt!r}")
    blocks = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
              '<meta name="viewport" content="width=device-width, initial-scale=1">',
              '<title>LogLens report</title><style>',
              'body{font:1rem/1.5 system-ui;margin:2rem auto;max-width:52rem;padding:0 1rem}',
              'table{border-collapse:collapse;width:100%}th,td{padding:.4rem;text-align:left;',
              'border-bottom:1px solid #aaa;overflow-wrap:anywhere}td{text-align:right}',
              '</style></head><body><main><h1>LogLens report</h1>']
    for title, rows in sections:
        body = "".join(
            f'<tr><th scope="row">{escape(_visible(label))}</th><td>{escape(str(value))}</td></tr>'
            for label, value in rows
        )
        blocks.append(f"<section><h2>{escape(title)}</h2>")
        blocks.append(f"<table><tbody>{body}</tbody></table>" if body else "<p>None</p>")
        blocks.append("</section>")
    return "\n".join([*blocks, "</main></body></html>"])
