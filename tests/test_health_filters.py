import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from pbi_usage_analyzer import analyze_project, filter_health_findings, HealthSeverity
from pbi_usage_analyzer.main import cli


class HealthFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        fixture = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/19_many_to_many_health'
        shutil.copytree(fixture, self.root)
        model = next(self.root.glob('*.SemanticModel'))
        path = model / 'definition/tables/Fact.tmdl'
        path.write_text(path.read_text(encoding='utf-8') + '\n    measure Undocumented = 1\n', encoding='utf-8')

    def test_filters_intersect_without_changing_analysis(self):
        original = analyze_project(self.root)
        selected = analyze_project(self.root, health_rule_ids=['MEASURE_DESCRIPTION_MISSING'], health_severities=['info'])
        self.assertEqual([f.rule_id for f in selected.health_findings], ['MEASURE_DESCRIPTION_MISSING'])
        self.assertEqual(original.findings, selected.findings)
        self.assertEqual(original.graph.evidence, selected.graph.evidence)
        self.assertEqual(original.diagnostics, selected.diagnostics)
        self.assertEqual(original.summary, selected.summary)
        self.assertEqual(analyze_project(self.root, health_rule_ids=['MEASURE_DESCRIPTION_MISSING'], health_severities=['warning']).health_findings, ())

    def test_reusable_filter_defaults_empty_duplicates_and_enums(self):
        findings = analyze_project(self.root).health_findings
        self.assertEqual(filter_health_findings(findings), findings)
        self.assertEqual(filter_health_findings(findings, rule_ids=[]), ())
        self.assertEqual(filter_health_findings(findings, severities=[]), ())
        self.assertEqual(filter_health_findings(findings, severities=HealthSeverity.INFO),
                         filter_health_findings(findings, severities=['info', 'info']))
        self.assertEqual(filter_health_findings(findings, rule_ids=[f.rule_id for f in findings]), findings)

    def test_unknown_values_fail_before_project_io(self):
        for options in ({'health_rule_ids': ['TYPO']}, {'health_severities': ['critical']}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                analyze_project('/not/a/project', **options)

    def test_cli_filters_both_exports(self):
        with patch('sys.argv', ['analyzer', str(self.root), '--health-severity', 'info', '--health-rule', 'MEASURE_DESCRIPTION_MISSING']):
            with contextlib.redirect_stdout(io.StringIO()):
                cli()
        text = next(self.root.glob('*_usage_summary_v2.txt')).read_text(encoding='utf-8')
        self.assertIn('[MEASURE_DESCRIPTION_MISSING]', text)
        self.assertNotIn('[RELATIONSHIP_MANY_TO_MANY]', text)
        book = load_workbook(next(self.root.glob('*.xlsx')))
        self.addCleanup(book.close)
        self.assertEqual([r[0] for r in book['Model health'].iter_rows(min_row=2, values_only=True)], ['MEASURE_DESCRIPTION_MISSING'])

    def test_cli_rejects_unknown_rule(self):
        with patch('sys.argv', ['analyzer', str(self.root), '--health-rule', 'TYPO']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                cli()
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(list(self.root.glob('*.xlsx')))

    def test_result_records_canonical_scope_and_counts(self):
        result = analyze_project(self.root, health_rule_ids=(x for x in ['MEASURE_DESCRIPTION_MISSING'] * 2),
                                 health_severities=[HealthSeverity.INFO, 'info'])
        scope = result.health_filter_scope
        self.assertEqual(scope.rule_ids, ('MEASURE_DESCRIPTION_MISSING',))
        self.assertEqual(scope.severities, ('info',))
        self.assertEqual((scope.total_findings, scope.selected_findings), (2, 1))
        unrestricted = analyze_project(self.root).health_filter_scope
        self.assertIsNone(unrestricted.rule_ids)
        self.assertIsNone(unrestricted.severities)
        self.assertEqual((unrestricted.total_findings, unrestricted.selected_findings), (2, 2))

    def test_empty_selection_is_explicit_in_both_reports(self):
        from pbi_usage_analyzer.main import run
        with contextlib.redirect_stdout(io.StringIO()):
            text, excel = run(self.root, health_rule_ids=[])
        report = text.read_text(encoding='utf-8')
        self.assertIn('Health rule filter: None (empty selection)', report)
        self.assertIn('Health findings before filtering: 2', report)
        self.assertIn('Health findings included: 0', report)
        book = load_workbook(excel)
        self.addCleanup(book.close)
        summary = dict(book['Summary'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(summary['Health rule filter'], 'None (empty selection)')
        self.assertEqual(summary['Health findings before filtering'], 2)
        self.assertEqual(summary['Health findings included'], 0)
        self.assertEqual(book['Model health'].max_row, 1)

    def test_legacy_report_call_does_not_claim_unfiltered_scope(self):
        from pbi_usage_analyzer.reporting.text_report import generate_text
        result = analyze_project(self.root)
        text = generate_text(result.project.project_name, result.findings, result.context, result.health_findings)
        self.assertIn('Health filter scope: Not recorded', text)
