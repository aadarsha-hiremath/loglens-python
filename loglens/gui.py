"""Launch the optional Qt desktop with python -m loglens.gui [FILE]."""

import argparse
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the LogLens desktop workspace.")
    parser.add_argument("file", nargs="?", type=Path, help="optional log file")
    args = parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication
        from .desktop_window import Window
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            parser.exit(2, 'The desktop needs Qt. From the checkout run: python -m pip install ".[gui]"\n')
        raise
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("LogLens")
    win = Window()
    win.show()
    if args.file:
        win.load_file(args.file)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
