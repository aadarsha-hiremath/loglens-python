"""Validated local desktop preferences. Never stores log paths or contents."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .desktop_data import COLUMNS, MAX_TOP
from .output import write_text

WIDTHS = dict(zip(COLUMNS, (245, 110, 155, 420)))


def settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData/Local")
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "LogLens" / "desktop.json"


@dataclass
class Preferences:
    theme: str = "Light"
    font_size: int = 10
    top: int = 5
    width: int = 1100
    height: int = 760
    sash: int = 350
    columns: tuple[str, ...] = COLUMNS
    widths: dict[str, int] = field(default_factory=WIDTHS.copy)

    @classmethod
    def load(cls, path: Path) -> "Preferences":
        prefs = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return prefs
        if not isinstance(data, dict):
            return prefs
        if data.get("theme") in ("Light", "Dark"):
            prefs.theme = data["theme"]
        for key, lower, upper in (("font_size", 9, 16), ("top", 1, MAX_TOP),
                                  ("width", 720, 12000), ("height", 520, 8000), ("sash", 80, 10000)):
            value = data.get(key)
            if type(value) is int and lower <= value <= upper:
                setattr(prefs, key, value)
        columns = data.get("columns")
        if isinstance(columns, list):
            prefs.columns = tuple(c for c in COLUMNS if c in columns) or COLUMNS
        widths = data.get("widths")
        if isinstance(widths, dict):
            for c in COLUMNS:
                width = widths.get(c)
                if type(width) is int and 50 <= width <= 8000:
                    prefs.widths[c] = width
        return prefs

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, json.dumps(asdict(self), indent=2))
