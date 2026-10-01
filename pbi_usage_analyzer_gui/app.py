"""Application entry point: `python -m pbi_usage_analyzer_gui [project folder or .pbip]`."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .main_window import APP_NAME, MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("pbi-usage-analyzer")
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.open_project(Path(argv[1]))
    return app.exec()
