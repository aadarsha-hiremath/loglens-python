"""Shared safe UTF-8 output for reports and preferences."""

import os
from collections.abc import Iterable
from concurrent.futures import CancelledError
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event


def validate_output(path: Path, source: Path) -> None:
    if path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
        raise ValueError("input and output must be different files")
    if path.exists() and not path.is_file():
        raise ValueError("output must be a regular file")


class Cancelled(CancelledError):
    """The worker acknowledged cancellation before completing its operation."""


def check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def write_atomic(path: Path, chunks: Iterable[str], cancel: Event | None = None) -> None:
    """Stage UTF-8 content, then commit with one atomic destination replacement."""
    check_cancel(cancel)
    tmp: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            tmp = Path(stream.name)
            for chunk in chunks:
                check_cancel(cancel)
                stream.write(chunk)
        check_cancel(cancel)
        # Replacement is the commit point. Once it succeeds, cancellation cannot undo it.
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def write_text(path: Path, report: str, cancel: Event | None = None) -> None:
    write_atomic(path, (report, "\n"), cancel)
