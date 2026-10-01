"""The UI-agnostic presentation layer (pbi_usage_analyzer.views) and shared report writing."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

from pbi_usage_analyzer import analyze_project, filter_health_findings
from pbi_usage_analyzer.analysis.classify import ROOT_EVIDENCE, classify
from pbi_usage_analyzer.health.engine import RULE_INFO, RULES
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.model import (DependencyGraph, Evidence, EvidenceType, ModelObject, ObjectRef,
                                      ObjectType, Status)
from pbi_usage_analyzer.reporting.files import write_reports
from pbi_usage_analyzer.views import (CATEGORY_LABELS, EVIDENCE_LABELS, STATUS_INFO, Explainer,
                                      filter_health, filter_objects, format_path, health_rows,
                                      object_key, object_rows, query_dependency_rows, unused_by_table)
from pbi_usage_analyzer.views import explain as explain_module

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
SCENARIOS = sorted(p for p in SUITE.iterdir() if p.is_dir())


@lru_cache(maxsize=None)
def analysis(name):
    return analyze_project(SUITE / name)


def paths_by_label(name):
    result = analysis(name)
    explainer = Explainer(result.graph, result.findings)
    return {f.ref.label: explainer.explain(f.ref) for f in result.findings}


class CatalogTests(unittest.TestCase):
    def test_every_status_evidence_type_and_rule_has_text(self):
        self.assertEqual(set(STATUS_INFO), set(Status))
        self.assertEqual(set(EVIDENCE_LABELS), set(EvidenceType))
        self.assertEqual(list(RULE_INFO), [rule_id for rule_id, _, _ in RULES])
        self.assertLessEqual({info.category for info in RULE_INFO.values()}, set(CATEGORY_LABELS))
        self.assertTrue(all(info.label and info.summary and info.explanation for info in STATUS_INFO.values()))

    def test_likely_unused_explanation_carries_the_caveat(self):
        self.assertIn('not proof that deletion is safe', STATUS_INFO[Status.LIKELY_UNUSED].explanation)

    def test_root_priority_covers_every_root_evidence_type(self):
        self.assertEqual(set(explain_module._ROOT_PRIORITY), ROOT_EVIDENCE)

    def test_emitted_findings_match_rule_metadata(self):
        for scenario in SCENARIOS:
            for finding in analysis(scenario.name).health_findings:
                with self.subTest(scenario=scenario.name, rule=finding.rule_id):
                    info = RULE_INFO[finding.rule_id]
                    self.assertEqual((finding.category, finding.severity), (info.category, info.severity))


class EvidencePathTests(unittest.TestCase):
    def test_transitive_dax(self):
        explained = paths_by_label('02_dax_transitive')
        self.assertEqual(format_path(explained['Sales[Amount]'].use_path),
                         'Report -> Sales[Measure A] -> DAX -> Sales[Measure B] -> DAX -> Sales[Amount]')

    def test_hierarchy_and_two_hop_lineage(self):
        self.assertEqual(format_path(paths_by_label('05_hierarchy')['Dates[Year]'].use_path),
                         'Report -> Dates[Calendar] -> Hierarchy -> Dates[Year]')
        explained = paths_by_label('41_m_usage_aware_lineage')
        self.assertEqual(format_path(explained['Raw 2024[amt]'].use_path),
                         'Report -> Sales[Amount] -> Power Query -> Sales 2024[Amount] -> Power Query -> Raw 2024[amt]')

    def test_review_received_through_lineage_names_its_origin(self):
        explained = paths_by_label('41_m_usage_aware_lineage')
        self.assertEqual(format_path(explained['Raw 2024[Code]'].review_path),
                         'Sales[Unused Code] -> DAX -> Sales[Code] -> Power Query -> Sales 2024[Code] '
                         '-> Power Query -> Raw 2024[Code]')
        # Own manual-review evidence explains itself; no lineage path.
        self.assertEqual(explained['Sales[Code]'].review_path, ())
        self.assertTrue(explained['Sales[Code]'].evidence)
        self.assertEqual(explained['Sales 2024[Note]'].use_path + explained['Sales 2024[Note]'].review_path, ())

    def test_every_used_object_has_a_connected_path(self):
        for scenario in SCENARIOS:
            result = analysis(scenario.name)
            explainer = Explainer(result.graph, result.findings)
            for finding in result.findings:
                if finding.status != Status.USED:
                    continue
                with self.subTest(scenario=scenario.name, object=finding.ref.label):
                    path = explainer.explain(finding.ref).use_path
                    self.assertTrue(path)
                    self.assertIn(path[0].evidence_type, ROOT_EVIDENCE)
                    for previous, edge in zip(path, path[1:]):
                        self.assertEqual(edge.source, previous.target)
                    self.assertEqual(path[-1].target, finding.ref)

    def test_report_use_is_preferred_as_the_path_start(self):
        graph = DependencyGraph()
        key = ObjectRef(ObjectType.COLUMN, 'Sales', 'Key')
        graph.add_object(ModelObject(key))
        # Relationship evidence first in graph order, as build_graph adds it.
        graph.add_evidence(Evidence(None, key, EvidenceType.RELATIONSHIP_DEPENDENCY, 'relationship'))
        graph.add_evidence(Evidence(None, key, EvidenceType.DIRECT_REPORT_USE, 'visual'))
        findings = classify(graph)
        path = Explainer(graph, findings).explain(key).use_path
        self.assertEqual(format_path(path), 'Report -> Sales[Key]')


class RowTests(unittest.TestCase):
    def test_object_rows_mirror_findings_with_unique_keys(self):
        result = analysis('41_m_usage_aware_lineage')
        rows = object_rows(result)
        self.assertEqual([row.ref for row in rows], [f.ref for f in result.findings])
        self.assertEqual(len({row.key for row in rows}), len(rows))
        self.assertEqual(object_key(rows[0].ref), rows[0].key)
        margin = next(row for row in rows if row.name == 'Margin')
        self.assertTrue(margin.calculated)

    def test_object_filters(self):
        rows = object_rows(analysis('41_m_usage_aware_lineage'))
        unused = filter_objects(rows, statuses=[Status.LIKELY_UNUSED])
        self.assertTrue(unused and all(row.status == Status.LIKELY_UNUSED for row in unused))
        self.assertEqual(filter_objects(rows, statuses=[]), ())
        both = filter_objects(rows, statuses=[Status.USED, Status.LIKELY_UNUSED], tables=['Raw 2024'])
        self.assertEqual({row.name for row in both}, {'amt', 'Note'})
        self.assertEqual({row.name for row in filter_objects(rows, text='RAW 2024')},
                         {'amt', 'Region', 'Note', 'Code'})
        self.assertEqual(filter_objects(rows, types=[ObjectType.MEASURE])[0].name, 'Unused Code')

    def test_internal_objects_are_hidden_unless_requested(self):
        rows = object_rows(analysis('08_autodate_scope_guard'))
        self.assertTrue(any(row.internal for row in rows))
        self.assertFalse(any(row.internal for row in filter_objects(rows)))
        self.assertTrue(any(row.internal for row in filter_objects(rows, include_internal=True)))

    def test_health_rows_filters_agree_with_the_engine_filter(self):
        result = analysis('19_many_to_many_health')
        rows = health_rows(result)
        self.assertEqual(len({row.key for row in rows}), len(rows))
        for rule_ids, severities in ((None, None), (['RELATIONSHIP_TEXT_KEY'], None),
                                     (None, [HealthSeverity.WARNING]), ([], None)):
            expected = filter_health_findings(result.health_findings, rule_ids=rule_ids,
                                              severities=None if severities is None else [s.value for s in severities])
            actual = filter_health(rows, rule_ids=rule_ids, severities=severities)
            self.assertEqual([row.title for row in actual], [f.title for f in expected])

    def test_relationship_scope_label_shows_endpoints(self):
        rows = health_rows(analysis('18_relationship_health'))
        self.assertTrue(rows)
        for row in rows:
            self.assertIn('→', row.scope_label)
            self.assertNotEqual(row.scope_label, row.scope)
            self.assertIn(row.scope, row.key)  # identity stays the relationship name
        others = health_rows(analysis('37_duplicate_measures'))
        self.assertTrue(all(row.scope_label == row.scope for row in others))
        self.assertEqual(len(filter_health(rows, text='→')), len(rows))

    def test_health_key_is_relative_to_the_project(self):
        for row in health_rows(analysis('37_duplicate_measures')):
            self.assertNotIn(str(SUITE), row.key)
            self.assertIn('.SemanticModel/definition/', row.key)

    def test_health_findings_reference_their_object(self):
        result = analysis('37_duplicate_measures')
        refs = [f.object_ref for f in result.health_findings]
        self.assertTrue(refs and all(ref in result.graph.objects for ref in refs))
        paths = analysis('34_m_hardcoded_paths')
        for finding in paths.health_findings:
            with self.subTest(scope=finding.scope):
                if finding.object_ref is not None:
                    self.assertEqual(finding.object_ref.object_type, ObjectType.QUERY)
                    self.assertIn(finding.object_ref, paths.graph.objects)
        relationship = analysis('18_relationship_health').health_findings
        self.assertTrue(relationship and all(f.object_ref is None for f in relationship))

    def test_query_dependency_rows_name_the_load_disabled_path(self):
        rows = query_dependency_rows(analysis('42_m_shared_query_lineage'))
        self.assertIn(('Report', 'Archive 2', ('Helper', 'Deep')), [(r.query, r.depends_on, r.via) for r in rows])

    def test_unused_by_table(self):
        rows = object_rows(analysis('41_m_usage_aware_lineage'))
        table = dict((name, (unused, total)) for name, unused, total in unused_by_table(rows))
        self.assertEqual(table['Sales'], (3, 5))  # Region, Note, Margin of five columns


class WriteReportsTests(unittest.TestCase):
    def test_writes_into_the_chosen_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            shutil.copytree(SUITE / '41_m_usage_aware_lineage', project)
            out = Path(tmp) / 'out'
            out.mkdir()
            files = write_reports(analyze_project(project), out, json=True)
            self.assertEqual({files.text.parent, files.excel.parent, files.json.parent}, {out})
            self.assertTrue(files.text.read_text(encoding='utf-8').startswith('='))
            self.assertGreater(files.excel.stat().st_size, 0)
            self.assertFalse(any(p.suffix in {'.txt', '.xlsx', '.json'} and 'usage' in p.name
                                 for p in project.iterdir()))
            self.assertIsNone(write_reports(analyze_project(project), out).json)


class ImportGuardTests(unittest.TestCase):
    def test_core_never_loads_a_gui_toolkit(self):
        code = ("import sys, pbi_usage_analyzer, pbi_usage_analyzer.views, pbi_usage_analyzer.reporting.files, "
                "pbi_usage_analyzer.main; "
                "bad = [m for m in sys.modules if m.split('.')[0] in "
                "{'PySide6', 'PyQt5', 'PyQt6', 'tkinter', 'pbi_usage_analyzer_gui'}]; "
                "sys.exit(', '.join(bad) or None)")
        completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                   cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
