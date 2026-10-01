"""Run comparison and acknowledgements (pbi_usage_analyzer.views.history)."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.model import Status
from pbi_usage_analyzer.views import (ChangeKind, ProjectState, compare_runs, filter_health, filter_objects,
                                      health_rows, object_rows, snapshot)

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def copy(self, scenario):
        target = Path(self.tmp.name) / scenario
        shutil.copytree(SUITE / scenario, target)
        return target


class SnapshotAndCompareTests(HistoryTestCase):
    def test_snapshot_records_status_and_path_per_object(self):
        result = analyze_project(SUITE / '41_m_usage_aware_lineage')
        run = snapshot(result, datetime(2026, 10, 1, 12, 0))
        self.assertEqual(run.analyzed_at, '2026-10-01T12:00:00')
        self.assertEqual(set(run.objects), {row.key for row in object_rows(result)})
        amt = run.objects['Column|Raw 2024|amt']
        self.assertEqual((amt.label, amt.status), ('Raw 2024[amt]', Status.USED))
        self.assertTrue(amt.path.startswith('Report -> Sales[Amount]'))
        self.assertEqual(set(run.findings), {row.key for row in health_rows(result)})

    def test_identical_runs_have_no_changes(self):
        result = analyze_project(SUITE / '41_m_usage_aware_lineage')
        self.assertEqual(compare_runs(snapshot(result), snapshot(result)), ())

    def test_removed_visual_changes_status_and_keeps_the_old_path(self):
        project = self.copy('41_m_usage_aware_lineage')
        before = snapshot(analyze_project(project))
        (next(project.rglob('Visual2')) / 'visual.json').unlink()  # the Budget[Note] visual
        changes = compare_runs(before, snapshot(analyze_project(project)))
        change = next(c for c in changes if c.key == 'Column|Budget|Note')
        self.assertEqual((change.kind, change.before, change.after),
                         (ChangeKind.STATUS_CHANGED, 'Used', 'Likely unused'))
        self.assertEqual(change.before_path, 'Report -> Budget[Note]')
        self.assertEqual(change.after_path, '')
        self.assertTrue(all(c.kind == ChangeKind.STATUS_CHANGED for c in changes))

    def test_added_and_removed_objects_and_findings(self):
        project = self.copy('37_duplicate_measures')
        before = snapshot(analyze_project(project))
        tables = next(project.rglob('tables'))
        # Make one duplicate different: its duplicate finding disappears.
        sales = next(p for p in tables.glob('*.tmdl') if 'measure' in p.read_text(encoding='utf-8'))
        text = sales.read_text(encoding='utf-8')
        sales.write_text(text + '\n    measure \'Brand new\' = 1 + 1\n', encoding='utf-8')
        after = snapshot(analyze_project(project))
        kinds = {c.kind for c in compare_runs(before, after)}
        self.assertIn(ChangeKind.OBJECT_ADDED, kinds)
        added = next(c for c in compare_runs(before, after) if c.kind == ChangeKind.OBJECT_ADDED)
        self.assertTrue(added.label.endswith('[Brand new]'))
        self.assertEqual((added.before, added.after), ('', 'Likely unused'))
        # And the reverse direction reports the removal.
        reverse = compare_runs(after, before)
        self.assertIn(ChangeKind.OBJECT_REMOVED, {c.kind for c in reverse})
        self.assertIn(ChangeKind.FINDING_RESOLVED, {c.kind for c in reverse})  # its description finding

    def test_changes_are_ordered_by_kind_then_label(self):
        project = self.copy('41_m_usage_aware_lineage')
        before = snapshot(analyze_project(project))
        (next(project.rglob('Visual1')) / 'visual.json').unlink()
        changes = compare_runs(before, snapshot(analyze_project(project)))
        labels = [c.label.casefold() for c in changes]
        self.assertEqual(labels, sorted(labels))


class ProjectStateTests(HistoryTestCase):
    def test_round_trip_through_json(self):
        result = analyze_project(SUITE / '41_m_usage_aware_lineage')
        state = ProjectState('C:/project')
        state.acknowledge('Column|Sales|Note', '  kept for the finance report  ', datetime(2026, 10, 1))
        state.last_run = snapshot(result)
        path = Path(self.tmp.name) / 'state' / 'project.json'
        state.save(path)
        loaded = ProjectState.load(path, 'C:/project')
        self.assertEqual(loaded.to_dict(), state.to_dict())
        self.assertEqual(loaded.acknowledgements['Column|Sales|Note'].note, 'kept for the finance report')
        self.assertEqual(loaded.acknowledgements['Column|Sales|Note'].acknowledged_at, '2026-10-01')
        self.assertEqual(compare_runs(loaded.last_run, state.last_run), ())
        self.assertFalse(path.with_suffix('.json.tmp').exists())

    def test_missing_file_gives_an_empty_state(self):
        state = ProjectState.load(Path(self.tmp.name) / 'none.json', 'C:/project')
        self.assertEqual((state.project_root, state.acknowledgements, state.last_run), ('C:/project', {}, None))

    def test_unreadable_or_foreign_files_raise_value_error(self):
        path = Path(self.tmp.name) / 'bad.json'
        for content in ('{not json', '[]', json.dumps({'format': 99}), json.dumps({'format': 1})):
            with self.subTest(content=content):
                path.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    ProjectState.load(path, 'C:/project')

    def test_acknowledge_unacknowledge_and_stale(self):
        state = ProjectState('C:/project')
        state.acknowledge('A')
        state.acknowledge('B', 'note')
        state.unacknowledge('A')
        state.unacknowledge('missing')  # no error
        self.assertEqual(list(state.acknowledgements), ['B'])
        self.assertEqual([a.key for a in state.stale_acknowledgements(['C'])], ['B'])
        self.assertEqual(state.stale_acknowledgements(['B']), ())

    def test_filters_hide_acknowledged_keys(self):
        result = analyze_project(SUITE / '37_duplicate_measures')
        objects, health = object_rows(result), health_rows(result)
        hidden = {objects[0].key, health[0].key}
        self.assertEqual(len(filter_objects(objects, exclude_keys=hidden)), len(filter_objects(objects)) - 1)
        self.assertEqual(len(filter_health(health, exclude_keys=hidden)), len(health) - 1)


if __name__ == '__main__':
    unittest.main()
