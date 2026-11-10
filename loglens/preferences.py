"""Versioned, validated desktop settings with atomic replacement."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .desktop_data import COLUMNS, Scope
from .output import write_text

WIDTHS = dict(zip(COLUMNS, (184, 94, 116, 340)))
VIEWS = ("Dashboard", "Log explorer", "Settings")


def settings_path():
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData/Local")
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "LogLens" / "desktop.json"


def valid_scope(raw):
    if not isinstance(raw, dict):
        return None
    values = {k: raw.get(k, v) for k, v in asdict(Scope()).items()}
    if any(type(values[k]) is not type(v) for k, v in asdict(Scope()).items()):
        return None
    scope = Scope(**values)
    try:
        scope.filters()
    except ValueError:
        return None
    return scope


@dataclass
class Preferences:
    version: int = 1
    theme: str = "Dark"
    density: str = "Balanced"
    motion: str = "Auto"
    reduced: bool = False
    smooth_scroll: bool = True
    font_size: int = 10
    top: int = 5
    width: int = 1320
    height: int = 820
    x: int | None = None
    y: int | None = None
    maximized: bool = False
    sash: int = 310
    inspector_height: int = 180
    inspector: bool = True
    filtered_dashboard: bool = False
    advanced: bool = False
    compact_nav: bool = False
    columns: tuple = COLUMNS
    order: tuple = COLUMNS
    widths: dict = field(default_factory=WIDTHS.copy)
    view: str = "Dashboard"
    sort: str = "rowid"
    descending: bool = False
    page_size: int = 100
    recent: list = field(default_factory=list)
    scope: Scope = field(default_factory=Scope)
    presets: dict = field(default_factory=dict)

    @classmethod
    def read(cls, path):
        prefs = cls()
        try:
            data = json.loads(path.read_text(encoding="utf8"))
            if not isinstance(data, dict) or data.get("version", 0) not in (0, 1):
                raise ValueError("unrecognized settings format")
        except FileNotFoundError:
            return prefs, ""
        except (OSError, ValueError) as exc:
            return prefs, f"Settings could not be read ({exc}). Original file preserved."
        for key, choices in dict(
            theme=("Light", "Dark", "System"),
            density=("Compact", "Balanced", "Comfortable"),
            motion=("Auto", "Balanced", "High", "Off"),
            view=VIEWS,
            sort=("rowid", *COLUMNS),
            page_size=(50, 100, 250, 500),
        ).items():
            if data.get(key) in choices:
                setattr(prefs, key, data[key])
        for key in (
            "maximized",
            "filtered_dashboard",
            "inspector",
            "advanced",
            "compact_nav",
            "descending",
            "reduced",
            "smooth_scroll",
        ):
            if isinstance(data.get(key), bool):
                setattr(prefs, key, data[key])
        for key, lo, hi in (
            ("font_size", 9, 16),
            ("top", 1, 100),
            ("width", 640, 16000),
            ("height", 460, 9000),
            ("x", -50000, 50000),
            ("y", -50000, 50000),
            ("sash", 100, 8000),
            ("inspector_height", 80, 4000),
        ):
            val = data.get(key)
            if type(val) is int and lo <= val <= hi:
                setattr(prefs, key, val)
        cols, order, widths = (data.get(k) for k in ("columns", "order", "widths"))
        if isinstance(cols, list):
            prefs.columns = tuple(c for c in COLUMNS if c in cols) or COLUMNS
        if isinstance(order, list) and len(order) == 4 and all(c in order for c in COLUMNS):
            prefs.order = tuple(order)
        if isinstance(widths, dict):
            for c in COLUMNS:
                val = widths.get(c)
                if type(val) is int and 50 <= val <= 8000:
                    prefs.widths[c] = val
        if isinstance(data.get("recent"), list):
            prefs.recent = list(dict.fromkeys(v for v in data["recent"] if isinstance(v, str) and v))[:10]
        prefs.scope = valid_scope(data.get("scope")) or Scope()
        if isinstance(data.get("presets"), dict):
            for name, raw in data["presets"].items():
                scope = valid_scope(raw)
                if name.strip() and scope is not None:
                    prefs.presets[name] = scope
        return prefs, ""

    @classmethod
    def load(cls, path):
        return cls.read(path)[0]

    def save(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, json.dumps(asdict(self), indent=2))
