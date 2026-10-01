"""Offscreen smoke tests of the PySide6 viewer; skipped when PySide6 is not installed."""
import importlib.util
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

HAS_QT = importlib.util.find_spec("PySide6") is not None
SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'

if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox

    from pbi_usage_analyzer import analyze_project
    from pbi_usage_analyzer.model import ObjectRef, ObjectType, Status
    from pbi_usage_analyzer.views import filter_objects, health_rows, object_rows
    from pbi_usage_analyzer_gui.main_window import MainWindow, project_folder


@unittest.skipUnless(HAS_QT, "PySide6 is not installed (pip install -r requirements-gui.txt)")
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = QSettings(str(Path(self.tmp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow(settings)
        self.addCleanup(self.window.close)

    def run_analysis(self, path):
        self.window.open_project(Path(path))
        self.wait_for_analysis()

    def wait_for_analysis(self):
        deadline = time.monotonic() + 30
        while not self.window.thread.isFinished():
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail("analysis did not finish")
        self.app.processEvents()  # deliver the queued result signal

    def test_open_project_through_the_worker_and_match_the_core(self):
        project = SUITE / '41_m_usage_aware_lineage'
        self.run_analysis(project)
        result = analyze_project(project)
        self.assertIs(self.window.stack.currentWidget(), self.window.results)
        self.assertEqual(self.window.cleanup.table.model.rowCount(), len(filter_objects(object_rows(result))))
        self.assertIn(str(project.resolve()), self.window.recent_projects())
        self.assertIn('41_m_usage_aware_lineage', self.window.header.text())
        self.assertFalse(self.window.banner.isVisibleTo(self.window))

    def test_filters_detail_and_navigation(self):
        self.run_analysis(SUITE / '41_m_usage_aware_lineage')
        window = self.window
        window._show_objects(Status.LIKELY_UNUSED, ObjectType.COLUMN, 'Raw 2024')
        self.assertIs(window.tabs.currentWidget(), window.cleanup)
        names = {row.name for row in window.cleanup.table.model.rows}
        self.assertEqual(names, {'Note'})
        # Selecting a Used object shows its evidence path.
        window.cleanup.set_filters()
        self.assertTrue(window.cleanup.select_key('Column|Raw 2024|amt'))
        html = window.detail.toPlainText()
        self.assertIn('Report -> Sales[Amount] -> Power Query -> Sales 2024[Amount] -> Power Query -> Raw 2024[amt]', html)
        # Search narrows the table.
        window.cleanup.search.setText('legacy')
        self.assertEqual([row.name for row in window.cleanup.table.model.rows], ['Legacy'])

    def test_health_finding_links_to_its_object_and_rerun_keeps_selection(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '37_duplicate_measures', project)
        self.run_analysis(project)
        window = self.window
        expected = health_rows(analyze_project(project))
        self.assertEqual(window.health.table.model.rowCount(), len(expected))
        window.tabs.setCurrentWidget(window.health)
        self.assertTrue(window.health.select_key(expected[0].key))
        self.assertIn(expected[0].title, window.detail.toPlainText())
        window.rerun_action.trigger()
        self.wait_for_analysis()
        self.assertEqual(window.health.table.selected().key, expected[0].key)
        window.show_object(expected[0].object_ref)
        self.assertIs(window.tabs.currentWidget(), window.cleanup)
        self.assertEqual(window.cleanup.table.selected().ref, expected[0].object_ref)

    def test_internal_objects_and_diagnostics_banner(self):
        self.run_analysis(SUITE / '27_incomplete_sources')
        self.assertTrue(self.window.banner.isVisibleTo(self.window))
        self.assertGreater(self.window.diagnostics.table.model.rowCount(), 0)
        self.run_analysis(SUITE / '08_autodate_scope_guard')
        cleanup = self.window.cleanup
        self.assertFalse(any(row.internal for row in cleanup.table.model.rows))
        cleanup.internal.setChecked(True)
        self.assertTrue(any(row.internal for row in cleanup.table.model.rows))

    def test_query_links_and_dependency_rows(self):
        self.run_analysis(SUITE / '42_m_shared_query_lineage')
        rows = self.window.queries.table.model.rows
        self.assertIn(('Report', 'Archive 2', ('Helper', 'Deep')), [(r.query, r.depends_on, r.via) for r in rows])
        self.window.show_object(ObjectRef(ObjectType.QUERY, 'Clean'))
        self.assertIs(self.window.tabs.currentWidget(), self.window.queries)
        self.assertEqual(self.window.queries.table.selected().query, 'Clean')

    def test_failed_analysis_reports_an_error_and_keeps_the_start_page(self):
        shown = []
        original = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: shown.append(args))
        try:
            self.run_analysis(Path(self.tmp.name))  # no PBIP inside
        finally:
            QMessageBox.warning = original
        self.assertTrue(shown)
        self.assertIs(self.window.stack.currentWidget(), self.window.start)

    def test_export_writes_reports_to_the_chosen_folder(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '02_dax_transitive', project)
        out = Path(self.tmp.name) / 'out'
        out.mkdir()
        self.run_analysis(project)
        from PySide6.QtWidgets import QFileDialog
        original = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(lambda *args, **kwargs: str(out))
        try:
            self.window.export(json=False)
        finally:
            QFileDialog.getExistingDirectory = original
        self.assertEqual(sorted(p.suffix for p in out.iterdir()), ['.txt', '.xlsx'])

    def test_smoke_test_mode_used_by_the_windows_build(self):
        import json
        from pbi_usage_analyzer_gui.app import smoke_test
        out = Path(self.tmp.name) / 'smoke'
        pbip = next((SUITE / '41_m_usage_aware_lineage').glob('*.pbip'))
        self.assertEqual(smoke_test(pbip, out), 0, (out / 'smoke-test-error.txt').read_text(encoding='utf-8')
                         if (out / 'smoke-test-error.txt').exists() else '')
        summary = json.loads((out / 'smoke-test.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['cleanup_rows'], 24)
        self.assertFalse(summary['frozen'])
        self.assertTrue((out / 'smoke-test.png').stat().st_size > 0)
        self.assertEqual(len(summary['reports']), 3)
        self.assertEqual(smoke_test(Path(self.tmp.name) / 'missing', out), 1)
        self.assertIn('NotADirectoryError', (out / 'smoke-test-error.txt').read_text(encoding='utf-8'))

    def test_pbip_file_stands_for_its_folder(self):
        pbip = next((SUITE / '02_dax_transitive').glob('*.pbip'))
        self.assertEqual(project_folder(pbip), SUITE / '02_dax_transitive')


if __name__ == '__main__':
    unittest.main()
