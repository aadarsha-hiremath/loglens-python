"""Generate a deterministic corpus, then time analysis independently of generation."""

import argparse
import json
import platform
import statistics
import tempfile
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from loglens.analysis import analyze


def generate(path: Path, rows: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    services = ("checkout", "cart", "payments", "inventory", "gateway", "worker", "queue")
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for i in range(rows):
            stamp = (base + timedelta(milliseconds=i)).isoformat(timespec="milliseconds")
            level = "ERROR" if i % 10 == 0 else "INFO"
            message = f"Retry bucket {i % 31}" if level == "ERROR" else "Operation completed"
            stream.write(f"{stamp} | {level} | {services[i % len(services)]} | {message}\n")


def run(path: Path, rows: int) -> None:
    with path.open("rb") as lines:
        summary = analyze(lines)
    if summary.matched != rows or summary.levels["ERROR"] != (rows + 9) // 10:
        raise RuntimeError("unexpected benchmark totals")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if min(args.rows, args.runs) < 1:
        parser.error("rows and runs must be positive")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "generated.log"
        generate(path, args.rows)
        elapsed = []
        for _ in range(args.runs):
            start = perf_counter()
            run(path, args.rows)
            elapsed.append(perf_counter() - start)
        tracemalloc.start()
        run(path, args.rows)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(json.dumps({
            "python": platform.python_version(), "platform": platform.platform(),
            "rows": args.rows, "bytes": path.stat().st_size, "runs_seconds": elapsed,
            "median_rows_per_second": round(args.rows / statistics.median(elapsed)),
            "peak_traced_bytes": peak,
        }, indent=2))


if __name__ == "__main__":
    main()
