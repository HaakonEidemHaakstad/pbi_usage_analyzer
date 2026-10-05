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
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from pbi_usage_analyzer import analyze_project
    from pbi_usage_analyzer.model import ObjectRef, ObjectType, Status
    from pbi_usage_analyzer.views import Effect, filter_objects, health_rows, object_rows
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
        # Never touch the real per-user settings or review state.
        self.data_dir = Path(self.tmp.name) / "data"
        self.window = MainWindow(settings, self.data_dir)
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

    def test_changes_since_the_previous_run(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '41_m_usage_aware_lineage', project)
        self.run_analysis(project)
        self.assertIsNone(self.window.changes)
        self.assertIn('First analysis', self.window.changes_tab.message.text())
        (next(project.rglob('Visual2')) / 'visual.json').unlink()
        self.window.rerun_action.trigger()
        self.wait_for_analysis()
        rows = self.window.changes_tab.table.model.rows
        self.assertIn(('Budget[Note]', 'Used', 'Likely unused', Effect.ATTENTION),
                      [(c.change.label, c.change.before, c.change.after, c.effect) for c in rows])
        self.assertTrue(self.window.changes_tab.table.select(lambda c: c.change.label == 'Budget[Note]'))
        text = self.window.detail.toPlainText()
        self.assertIn('Report -> Budget[Note]', text)  # the evidence path it had before
        self.assertIn('Attention: No known use any more', text)
        # The comparison survives a restart: a new window compares with the last run.
        again = MainWindow(QSettings(str(Path(self.tmp.name) / "s2.ini"), QSettings.Format.IniFormat), self.data_dir)
        self.addCleanup(again.close)
        self.window = again
        self.run_analysis(project)
        self.assertEqual(again.changes, ())

    def test_change_ratings_risk_first_filter_and_overview_link(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '02_dax_transitive', project)
        self.run_analysis(project)
        sales = next(project.rglob('Sales.tmdl'))
        text = sales.read_text(encoding='utf-8')
        # Remove a used column: a Risk (removed while Used) and a Risk (DAX now unresolved).
        sales.write_text(text.replace("    column Amount\n        dataType: double\n        sourceColumn: Amount\n\n",
                                      ''), encoding='utf-8')
        self.window.rerun_action.trigger()
        self.wait_for_analysis()
        tab = self.window.changes_tab
        effects = [c.effect for c in tab.table.model.rows]
        self.assertEqual(effects[:2], [Effect.RISK, Effect.RISK])
        self.assertEqual(effects, sorted(effects, key=list(Effect).index))
        self.assertIn('2 risks', tab.message.text())
        model = tab.table.model
        self.assertEqual(model.data(model.index(0, 0)), 'Risk')
        self.assertIsNotNone(model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole))
        self.assertIn('The previous analysis proved this object used',
                      model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole))
        self.assertIn('Check it first', tab.effect.itemData(1, Qt.ItemDataRole.ToolTipRole))
        # The overview's risk button opens the tab filtered to risks.
        self.window._show_changes(Effect.IMPROVEMENT)
        self.assertTrue(all(c.effect == Effect.IMPROVEMENT for c in tab.table.model.rows))
        self.window._show_changes(Effect.RISK)
        self.assertIs(self.window.tabs.currentWidget(), tab)
        self.assertEqual({c.change.label for c in tab.table.model.rows}, {'Sales[Amount]', 'Sales[Measure B]'})
        self.assertIn('risks', self.window.statusBar().currentMessage())

    def test_acknowledgements_persist_hide_and_can_be_removed(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '37_duplicate_measures', project)
        self.run_analysis(project)
        health = self.window.health
        total = health.table.model.rowCount()
        key = health.table.model.rows[0].key
        self.window.acknowledge(key, note='Intentional copy for the finance page')
        self.assertEqual(health.table.model.rowCount(), total - 1)
        # A new window (restart) reads the saved acknowledgement.
        again = MainWindow(QSettings(str(Path(self.tmp.name) / "s2.ini"), QSettings.Format.IniFormat), self.data_dir)
        self.addCleanup(again.close)
        self.window = again
        self.run_analysis(project)
        self.assertEqual(again.health.table.model.rowCount(), total - 1)
        again.tabs.setCurrentWidget(again.health)
        self.assertTrue(again.health.select_key(key))  # reveals acknowledged rows
        self.assertIn('Intentional copy for the finance page', again.detail.toPlainText())
        again.unacknowledge(key)
        self.assertNotIn(key, again.state.acknowledgements)

    def test_stale_acknowledgements_and_unreadable_state(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '02_dax_transitive', project)
        self.run_analysis(project)
        self.window.acknowledge('Column|Gone|Away', note='')
        self.window.acknowledge('Column|Sales|Amount', note='')
        self.window.prune_acknowledgements()
        self.assertEqual(list(self.window.state.acknowledgements), ['Column|Sales|Amount'])
        # Corrupt the saved state: a new window warns, moves it aside and starts fresh.
        from pbi_usage_analyzer_gui.main_window import state_file
        path = state_file(self.data_dir, project)
        path.write_text('{broken', encoding='utf-8')
        shown = []
        original = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: shown.append(args))
        try:
            again = MainWindow(QSettings(str(Path(self.tmp.name) / "s2.ini"), QSettings.Format.IniFormat),
                               self.data_dir)
            self.addCleanup(again.close)
            self.window = again
            self.run_analysis(project)
        finally:
            QMessageBox.warning = original
        self.assertTrue(shown)
        self.assertEqual(again.state.acknowledgements, {})
        self.assertTrue(list(path.parent.glob('*.unreadable-*.json')))

    def test_references_link_to_the_objects_a_measure_uses(self):
        from PySide6.QtCore import QUrl
        self.run_analysis(SUITE / '02_dax_transitive')
        window = self.window
        window.tabs.setCurrentWidget(window.cleanup)
        self.assertTrue(window.cleanup.select_key('Measure|Sales|Measure A'))
        self.assertIn('References', window.detail.toPlainText())
        index = next(i for i, link in enumerate(window.detail._links)
                     if link[0] == 'object' and link[1].name == 'Measure B')
        window.detail._clicked(QUrl(f'link:{index}'))
        self.assertEqual(window.cleanup.table.selected().name, 'Measure B')

    def test_reports_are_written_automatically_when_enabled(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '02_dax_transitive', project)
        self.run_analysis(project)
        self.assertFalse(list(project.glob('*_usage_*')))  # off by default
        self.window.auto_reports_action.setChecked(True)  # writes for the current result at once
        self.assertEqual(sorted(p.suffix for p in project.glob('*_usage_*')), ['.txt', '.xlsx'])
        self.assertTrue(self.window.settings.value('autoReports', type=bool))
        for path in project.glob('*_usage_*'):
            path.unlink()
        self.window.rerun_action.trigger()
        self.wait_for_analysis()
        self.assertEqual(len(list(project.glob('*_usage_*'))), 2)
        self.assertIn('Reports written to', self.window.statusBar().currentMessage())

    def test_user_manual_is_found_from_source(self):
        from pbi_usage_analyzer_gui.main_window import manual_path
        self.assertTrue(manual_path().exists())
        self.assertIn('F1', [a.shortcut().toString() for a in self.window.findChildren(type(self.window.rerun_action))])

    def test_pbip_file_stands_for_its_folder(self):
        pbip = next((SUITE / '02_dax_transitive').glob('*.pbip'))
        self.assertEqual(project_folder(pbip), SUITE / '02_dax_transitive')


if __name__ == '__main__':
    unittest.main()
