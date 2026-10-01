"""Application entry point: `python -m pbi_usage_analyzer_gui [project folder or .pbip]`.

`--smoke-test PROJECT OUTPUT_FOLDER` analyzes a project without user interaction,
loads it into the main window, writes all reports, `smoke-test.json` and a
rendering of the window (`smoke-test.png`) to the folder and exits. The Windows build uses it to check the frozen application
(which has no console); run it with QT_QPA_PLATFORM=offscreen to stay invisible.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from .main_window import APP_NAME, MainWindow, project_folder


def smoke_test(project: Path, output: Path) -> int:
    from pbi_usage_analyzer import __version__, analyze_project
    from pbi_usage_analyzer.reporting.files import write_reports

    output.mkdir(parents=True, exist_ok=True)
    try:
        result = analyze_project(project_folder(project))
        window = MainWindow(QSettings(str(output / "smoke-test-settings.ini"), QSettings.Format.IniFormat))
        window.show_result(result)
        window.resize(1400, 860)
        window.grab().save(str(output / "smoke-test.png"))  # rendered without showing the window
        files = write_reports(result, output, json=True)
        summary = {
            "version": __version__,
            "project": result.project.project_name,
            "frozen": bool(getattr(sys, "frozen", False)),
            "cleanup_rows": window.cleanup.table.model.rowCount(),
            "health_rows": window.health.table.model.rowCount(),
            "reports": sorted(path.name for path in (files.text, files.excel, files.json)),
        }
        (output / "smoke-test.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        window.close()
        return 0
    except Exception:
        (output / "smoke-test-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("pbi-usage-analyzer")
    if len(argv) == 4 and argv[1] == "--smoke-test":
        return smoke_test(Path(argv[2]), Path(argv[3]))
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.open_project(Path(argv[1]))
    return app.exec()
