"""Parse one UTF-8 record at a time and normalize timestamps to UTC."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
FAILURES = frozenset(("ERROR", "CRITICAL"))
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
_SERVICE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")


class RecordError(ValueError):
    """The message is a stable, bounded diagnostic category."""


@dataclass(frozen=True, slots=True)
class Record:
    timestamp: datetime
    level: str
    service: str
    message: str


def parse_timestamp(value: str) -> datetime:
    if _TIMESTAMP.fullmatch(value):
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    raise RecordError("invalid timestamp")


def parse_line(raw: bytes, *, first_line: bool = False) -> Record:
    try:
        line = raw.decode("utf-8-sig" if first_line else "utf-8").removesuffix("\n").removesuffix("\r")
    except UnicodeDecodeError as exc:
        raise RecordError("invalid UTF-8") from exc
    fields = line.split(" | ", 3)
    if len(fields) != 4:
        raise RecordError("expected four fields")
    stamp, level, service, message = fields
    timestamp = parse_timestamp(stamp)
    if level not in LEVELS:
        raise RecordError("unknown level")
    if not _SERVICE.fullmatch(service):
        raise RecordError("invalid service")
    if not message.strip():
        raise RecordError("empty message")
    return Record(timestamp, level, service, message)
