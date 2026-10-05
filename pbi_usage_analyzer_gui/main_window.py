"""Main window: start page, result tabs, detail panel, re-run, export and review state."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QSplitter, QStackedWidget, QTabWidget,
                               QVBoxLayout, QWidget)

from pbi_usage_analyzer import AnalysisResult, __version__
from pbi_usage_analyzer.model import ObjectType
from pbi_usage_analyzer.reporting.files import write_reports
from pbi_usage_analyzer.views import (Change, Explainer, ProjectState, compare_runs, diagnostic_rows,
                                      health_rows, object_key, object_rows, query_dependency_rows, snapshot)
from pbi_usage_analyzer.views.history import state_file

from .detail import (DetailPanel, change_html, diagnostic_html, health_html, object_html, query_html)
from .tabs import ChangesTab, CleanupTab, DiagnosticsTab, HealthTab, OverviewTab, QueriesTab
from .worker import AnalysisThread

APP_NAME = "Power BI Model Health Analyzer"
MAX_RECENT = 8


def project_folder(path: Path) -> Path:
    """A `.pbip` file stands for its folder."""
    return path.parent if path.suffix.casefold() == ".pbip" else path


def manual_path() -> Path:
    """The HTML manual shipped next to the Windows app, or the Markdown source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "User manual.html"
    return Path(__file__).resolve().parent.parent / "docs" / "manual" / "USER_MANUAL.md"


class StartPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        title = QLabel(f"<h1>{APP_NAME}</h1><p>Open a Power BI project (PBIP) saved with the "
                       "PBIR report format and TMDL semantic model format.</p>")
        title.setWordWrap(True)
        open_folder = QPushButton("Open project folder…")
        open_folder.clicked.connect(window.choose_folder)
        open_file = QPushButton("Open .pbip file…")
        open_file.clicked.connect(window.choose_pbip)
        buttons = QHBoxLayout()
        buttons.addWidget(open_folder)
        buttons.addWidget(open_file)
        buttons.addStretch()
        self.recent = QListWidget()
        self.recent.itemActivated.connect(self._activated)
        self._window = window
        note = QLabel("The analyzer only reads the project. It never changes or deletes anything.")
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("<b>Recent projects</b> (double-click to open)"))
        layout.addWidget(self.recent, 1)
        layout.addWidget(note)

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        self.recent.addItems(paths)
        if not paths:
            placeholder = QListWidgetItem("No recent projects yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(placeholder)

    def _activated(self, item: QListWidgetItem) -> None:
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self._window.open_project(Path(item.text()))


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, data_dir: Path | None = None):
        super().__init__()
        self.settings = settings or QSettings("pbi-usage-analyzer", "Power BI Model Health Analyzer")
        self.data_dir = data_dir or Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation))
        self.state: ProjectState | None = None
        self.changes: tuple[Change, ...] | None = None
        self.result: AnalysisResult | None = None
        self.project: Path | None = None
        self.explainer: Explainer | None = None
        self.thread: AnalysisThread | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(1300, 820)

        self.start = StartPage(self)
        self.results = QWidget()
        self.header = QLabel()
        self.header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner = QLabel("Some sources could not be fully read or traced. Results may be incomplete; "
                             "see the Diagnostics tab.")
        self.banner.setStyleSheet("background:#fff3cd; color:#664d03; padding:6px;")
        self.banner.setWordWrap(True)
        self.tabs = QTabWidget()
        self.overview, self.cleanup, self.health = OverviewTab(), CleanupTab(), HealthTab()
        self.diagnostics, self.queries, self.changes_tab = DiagnosticsTab(), QueriesTab(), ChangesTab()
        for widget, title in ((self.overview, "Overview"), (self.cleanup, "Cleanup"), (self.health, "Health"),
                              (self.changes_tab, "Changes"), (self.diagnostics, "Diagnostics"),
                              (self.queries, "Queries")):
            self.tabs.addTab(widget, title)
        self.detail = DetailPanel()
        splitter = QSplitter()
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([780, 520])  # the detail panel needs room for evidence paths
        layout = QVBoxLayout(self.results)
        layout.addWidget(self.header)
        layout.addWidget(self.banner)
        layout.addWidget(splitter, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(self.results)
        self.setCentralWidget(self.stack)

        self._create_actions()
        self.overview.show_objects.connect(self._show_objects)
        self.overview.show_health.connect(self._show_health)
        self.overview.show_diagnostics.connect(lambda: self.tabs.setCurrentWidget(self.diagnostics))
        self.overview.show_changes.connect(lambda: self.tabs.setCurrentWidget(self.changes_tab))
        self.cleanup.object_selected.connect(self._object_selected)
        self.health.finding_selected.connect(self._finding_selected)
        self.changes_tab.row_selected.connect(self._change_selected)
        for tab in (self.cleanup, self.health):
            tab.acknowledge_requested.connect(self.acknowledge)
            tab.unacknowledge_requested.connect(self.unacknowledge)
        self.diagnostics.row_selected.connect(lambda row: self.detail.show_html(diagnostic_html(row)))
        self.queries.row_selected.connect(lambda row: self.detail.show_html(query_html(row)))
        self.detail.open_file.connect(self.open_file)
        self.detail.show_object.connect(self.show_object)
        self.tabs.currentChanged.connect(lambda _: self.detail.clear_detail())
        self._refresh_recent()
        self.statusBar().showMessage("Open a project to start.")

    # Actions and menus

    def _create_actions(self) -> None:
        def action(text, slot, shortcut=None):
            item = QAction(text, self)
            item.triggered.connect(slot)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            return item

        self.open_folder_action = action("Open project folder…", self.choose_folder, QKeySequence.StandardKey.Open)
        self.open_pbip_action = action("Open .pbip file…", self.choose_pbip)
        self.rerun_action = action("Re-run analysis", self.rerun, "F5")
        self.export_action = action("Export reports…", lambda: self.export(json=False), "Ctrl+E")
        self.export_json_action = action("Export reports with JSON…", lambda: self.export(json=True))
        self.auto_reports_action = QAction("Write reports automatically", self)
        self.auto_reports_action.setCheckable(True)
        self.auto_reports_action.setChecked(self.settings.value("autoReports", False, type=bool))
        self.auto_reports_action.setToolTip("After every analysis, write the text and Excel reports into the "
                                            "project folder (as the command line does)")
        self.auto_reports_action.toggled.connect(self._auto_reports_toggled)
        self.quit_action = action("Quit", self.close, QKeySequence.StandardKey.Quit)
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.open_folder_action, self.open_pbip_action])
        self.recent_menu = file_menu.addMenu("Recent projects")
        file_menu.addSeparator()
        file_menu.addActions([self.rerun_action, self.export_action, self.export_json_action,
                              self.auto_reports_action])
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        self.acknowledge_action = action("Acknowledge selected…", self._acknowledge_selected, "Ctrl+K")
        self.unacknowledge_action = action("Remove acknowledgement", self._unacknowledge_selected, "Ctrl+Shift+K")
        self.prune_action = action("Remove acknowledgements of missing items", self.prune_acknowledgements)
        review_menu = self.menuBar().addMenu("&Review")
        review_menu.addActions([self.acknowledge_action, self.unacknowledge_action])
        review_menu.addSeparator()
        review_menu.addAction(self.prune_action)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(action("User manual", self.open_manual, "F1"))
        help_menu.addAction(action("About", self.about))
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main-toolbar")
        toolbar.addActions([self.open_folder_action, self.rerun_action, self.export_action])
        self._set_result_actions(False)

    def _set_result_actions(self, enabled: bool) -> None:
        for item in (self.rerun_action, self.export_action, self.export_json_action,
                     self.acknowledge_action, self.unacknowledge_action, self.prune_action):
            item.setEnabled(enabled)

    def _refresh_recent(self) -> None:
        paths = self.recent_projects()
        self.start.set_recent(paths)
        self.recent_menu.clear()
        for path in paths:
            self.recent_menu.addAction(path, lambda p=path: self.open_project(Path(p)))
        self.recent_menu.setEnabled(bool(paths))

    def recent_projects(self) -> list[str]:
        value = self.settings.value("recent", [])
        return [value] if isinstance(value, str) else list(value or [])

    def _remember(self, path: Path) -> None:
        paths = [str(path)] + [p for p in self.recent_projects() if p != str(path)]
        self.settings.setValue("recent", paths[:MAX_RECENT])
        self._refresh_recent()

    # Running the analysis

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open PBIP project folder", self._start_dir())
        if folder:
            self.open_project(Path(folder))

    def choose_pbip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open .pbip file", self._start_dir(),
                                              "Power BI project (*.pbip)")
        if path:
            self.open_project(Path(path))

    def _start_dir(self) -> str:
        return str(self.project.parent) if self.project else str(Path.home())

    def open_project(self, path: Path) -> None:
        self.project = project_folder(path)
        self._run()

    def rerun(self) -> None:
        if self.project is not None:
            self._run()

    def _run(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            return
        self.statusBar().showMessage(f"Analyzing {self.project} …")
        self._set_result_actions(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.thread = AnalysisThread(self.project, self)
        self.thread.succeeded.connect(self._succeeded)
        self.thread.failed.connect(self._failed)
        self.thread.finished.connect(QApplication.restoreOverrideCursor)
        self.thread.start()

    def _succeeded(self, result: AnalysisResult) -> None:
        self.show_result(result)
        self._remember(self.project)

    def _failed(self, message: str) -> None:
        self._set_result_actions(self.result is not None)
        self.statusBar().showMessage("Analysis failed.")
        QMessageBox.warning(self, "Could not analyze the project",
                            f"{self.project}\n\n{message}\n\nChoose the folder that contains the "
                            "*.Report and *.SemanticModel folders (or the .pbip file).")

    def show_result(self, result: AnalysisResult) -> None:
        """Display a result; a re-run of the same project keeps the selected row."""
        same_project = self.result is not None and self.result.project.root == result.project.root
        selected = self._selected_key() if same_project else None
        self.result = result
        self.project = result.project.root
        self.explainer = Explainer(result.graph, result.findings)
        objects, health = object_rows(result), health_rows(result)
        diagnostics, queries = diagnostic_rows(result), query_dependency_rows(result)
        if not same_project or self.state is None:
            self.state = self._load_state(result.project.root)
        current = snapshot(result)
        previous = self.state.last_run
        self.changes = compare_runs(previous, current) if previous is not None else None
        self.state.last_run = current
        self._save_state()
        acknowledgements = self.state.acknowledgements
        self.overview.set_result(objects, health, diagnostics, frozenset(acknowledgements), self.changes)
        self.cleanup.acknowledgements = acknowledgements
        self.health.acknowledgements = acknowledgements
        self.cleanup.set_rows(objects)
        self.health.set_rows(health)
        self.changes_tab.set_changes(self.changes, _when(previous.analyzed_at) if previous else None)
        self.diagnostics.set_rows(diagnostics)
        self.queries.set_rows(queries)
        if not same_project:
            self.cleanup.set_filters()
            self.health.set_filters()
            self.tabs.setCurrentWidget(self.overview)
        self.banner.setVisible(bool(diagnostics))
        self.header.setText(f"<b>{result.project.project_name}</b> &nbsp; {result.project.root} &nbsp; "
                            f"<span style='color:gray'>analyzed {datetime.now():%H:%M:%S}</span>")
        self.setWindowTitle(f"{result.project.project_name} — {APP_NAME}")
        self.stack.setCurrentWidget(self.results)
        self._set_result_actions(True)
        columns, measures = result.summary.columns, result.summary.measures
        self.statusBar().showMessage(
            f"{columns.business_total + measures.business_total} business objects: "
            f"{columns.used + measures.used} Used, {columns.manual_review + measures.manual_review} "
            f"Needs manual review, {columns.likely_unused + measures.likely_unused} Likely unused · "
            f"{len(health)} health findings · {len(diagnostics)} diagnostics"
            + (f" · {len(self.changes)} changes since last run" if self.changes else ""))
        if self.auto_reports_action.isChecked():
            self._write_automatic_reports(result)
        if selected is None or not self._restore(selected):
            self.detail.clear_detail()

    def _selected_key(self) -> tuple[str, str] | None:
        if self.tabs.currentWidget() is self.cleanup and self.cleanup.table.selected() is not None:
            return ("object", self.cleanup.table.selected().key)
        if self.tabs.currentWidget() is self.health and self.health.table.selected() is not None:
            return ("health", self.health.table.selected().key)
        return None

    def _restore(self, selected: tuple[str, str]) -> bool:
        kind, key = selected
        return self.cleanup.select_key(key) if kind == "object" else self.health.select_key(key)

    # Navigation and details

    def _object_selected(self, row) -> None:
        if self.explainer is not None:
            self.detail.show_html(object_html(row, self.explainer.explain(row.ref), self.explainer.status_of,
                                              self._acknowledgement(row.key)))

    def _finding_selected(self, row) -> None:
        self.detail.show_html(health_html(row, self._acknowledgement(row.key)))

    def _change_selected(self, change: Change) -> None:
        current = None
        if self.result is not None:
            current = next((f.ref for f in self.result.findings if object_key(f.ref) == change.key), None)
        self.detail.show_html(change_html(change, current))

    # Review state: acknowledgements and the last run, per user and project

    def _load_state(self, root: Path) -> ProjectState:
        path = state_file(self.data_dir, root)
        try:
            return ProjectState.load(path, str(root))
        except ValueError as exc:
            backup = path.with_name(path.stem + f".unreadable-{datetime.now():%Y%m%d-%H%M%S}.json")
            path.replace(backup)
            QMessageBox.warning(self, "Review state reset",
                                f"The saved acknowledgements for this project could not be read and were "
                                f"moved aside:\n{backup}\n\n{exc}")
            return ProjectState(str(root))

    def _save_state(self) -> None:
        if self.state is None or self.result is None:
            return
        try:
            self.state.save(state_file(self.data_dir, self.result.project.root))
        except OSError as exc:
            self.statusBar().showMessage(f"Could not save the review state: {exc}")

    def _acknowledgement(self, key: str):
        return self.state.acknowledgements.get(key) if self.state else None

    def _selected_review_key(self) -> str | None:
        tab = self.tabs.currentWidget()
        if tab in (self.cleanup, self.health) and tab.table.selected() is not None:
            return tab.table.selected().key
        return None

    def _acknowledge_selected(self) -> None:
        key = self._selected_review_key()
        if key is None:
            self.statusBar().showMessage("Select a row in the Cleanup or Health tab to acknowledge it.")
            return
        self.acknowledge(key)

    def _unacknowledge_selected(self) -> None:
        key = self._selected_review_key()
        if key is not None:
            self.unacknowledge(key)

    def acknowledge(self, key: str, note: str | None = None) -> None:
        """Mark a row as reviewed; asks for an optional note unless one is given."""
        if self.state is None:
            return
        if note is None:
            existing = self._acknowledgement(key)
            note, accepted = QInputDialog.getMultiLineText(
                self, "Acknowledge", "Optional note (why this is fine, who decided):",
                existing.note if existing else "")
            if not accepted:
                return
        self.state.acknowledge(key, note)
        self._review_changed(f"Acknowledged. Acknowledged rows are hidden unless you clear 'Hide acknowledged'.")

    def unacknowledge(self, key: str) -> None:
        if self.state is not None and key in self.state.acknowledgements:
            self.state.unacknowledge(key)
            self._review_changed("Acknowledgement removed.")

    def prune_acknowledgements(self) -> None:
        if self.state is None or self.result is None:
            return
        current = {row.key for row in object_rows(self.result)} | {row.key for row in health_rows(self.result)}
        stale = self.state.stale_acknowledgements(current)
        for item in stale:
            self.state.unacknowledge(item.key)
        self._review_changed(f"Removed {len(stale)} acknowledgements of items that no longer exist.")

    def _review_changed(self, message: str) -> None:
        self._save_state()
        acknowledgements = self.state.acknowledgements
        self.cleanup.set_acknowledgements(acknowledgements)
        self.health.set_acknowledgements(acknowledgements)
        if self.result is not None:
            self.overview.set_result(object_rows(self.result), health_rows(self.result),
                                     diagnostic_rows(self.result), frozenset(acknowledgements), self.changes)
        self.statusBar().showMessage(message)

    def _show_objects(self, status, object_type, table) -> None:
        self.cleanup.set_filters(status=status, object_type=object_type, table=table)
        self.tabs.setCurrentWidget(self.cleanup)

    def _show_health(self, severity) -> None:
        self.health.set_filters(severity=severity)
        self.tabs.setCurrentWidget(self.health)

    def show_object(self, ref) -> None:
        if ref.object_type == ObjectType.QUERY:
            self.tabs.setCurrentWidget(self.queries)
            if not self.queries.show_query(ref.table):
                self.statusBar().showMessage(f"Query {ref.table} has no dependencies between model queries.")
            return
        self.tabs.setCurrentWidget(self.cleanup)
        if not self.cleanup.show_ref(ref):
            self.statusBar().showMessage(f"{ref.label} has no cleanup status.")

    def open_file(self, path: str) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self.statusBar().showMessage(f"Could not open {path}")

    # Export and help

    def export(self, json: bool) -> None:
        if self.result is None:
            return
        if json and QMessageBox.question(
                self, "Export JSON",
                "The JSON report contains local file paths and the model's DAX and M expressions. "
                "Continue?") != QMessageBox.StandardButton.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "Export reports to folder", str(self.result.project.root))
        if not folder:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            files = write_reports(self.result, folder, json=json)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", f"{exc}\n\nIs a report file open in another program?")
            return
        finally:
            QApplication.restoreOverrideCursor()
        written = [files.text, files.excel] + ([files.json] if files.json else [])
        self.statusBar().showMessage("Wrote " + ", ".join(path.name for path in written))

    def open_manual(self) -> None:
        path = manual_path()
        if not path.exists():
            self.statusBar().showMessage(f"The user manual was not found: {path}")
            return
        self.open_file(str(path))

    def _auto_reports_toggled(self, enabled: bool) -> None:
        self.settings.setValue("autoReports", enabled)
        if enabled and self.result is not None:
            self._write_automatic_reports(self.result)

    def _write_automatic_reports(self, result: AnalysisResult) -> None:
        """Text and Excel reports into the project folder; failures only reach the status bar."""
        try:
            files = write_reports(result)
        except OSError as exc:
            self.statusBar().showMessage(f"Automatic reports not written ({exc}). Is a report open in Excel?")
            return
        self.statusBar().showMessage(f"Reports written to {files.text.parent}: {files.text.name}, {files.excel.name}")

    def about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}", (
            f"<h3>{APP_NAME}</h3><p>Version {__version__}</p>"
            "<p>Static analysis of Power BI PBIP projects: cleanup candidates, dependencies and "
            "model-health findings. The analyzer only reads the project.</p>"
            "<p><b>Likely unused</b> is a cleanup candidate, not proof that deletion is safe.</p>"
            "<p>Built with Qt for Python (PySide6), licensed under the LGPL v3.</p>"))

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.thread is not None and self.thread.isRunning():
            self.thread.wait(5000)
        super().closeEvent(event)


def _when(iso: str) -> str:
    """'2026-10-01T14:32:05' as '2026-10-01 14:32'."""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso
