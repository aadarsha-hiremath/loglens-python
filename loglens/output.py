"""Shared safe UTF-8 output for reports and preferences."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def validate_output(path: Path, source: Path) -> None:
    if path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
        raise ValueError("input and output must be different files")
    if path.exists() and not path.is_file():
        raise ValueError("output must be a regular file")


def write_text(path: Path, report: str) -> None:
    # Keep the previous report intact if writing or replacement fails.
    tmp: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=path.parent, delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(report + "\n")
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
