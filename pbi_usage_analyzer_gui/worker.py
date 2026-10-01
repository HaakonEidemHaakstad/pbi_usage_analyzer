"""Runs `analyze_project()` off the UI thread (OneDrive placeholders can stall reads)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from pbi_usage_analyzer import analyze_project


class AnalysisThread(QThread):
    succeeded = Signal(object)  # AnalysisResult
    failed = Signal(str)

    def __init__(self, project: Path, parent=None):
        super().__init__(parent)
        self.project = project

    def run(self) -> None:
        try:
            result = analyze_project(self.project)
        except Exception as exc:  # Shown to the user; discovery/read errors are fatal here.
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.succeeded.emit(result)
