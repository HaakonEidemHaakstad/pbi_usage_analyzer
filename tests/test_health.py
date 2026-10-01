import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.discovery import discover_project
from pbi_usage_analyzer.main import run
from pbi_usage_analyzer.parsers.relationships import parse_relationship_metadata


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        fixture = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/03_relationship_only'
        shutil.copytree(fixture, self.root)
        self.model = discover_project(self.root).model_folder
        self.source = self.model / 'definition/relationships.tmdl'

    def test_rule_is_advisory_and_does_not_change_cleanup(self):
        before = analyze_project(self.root)
        self.source.write_text(self.source.read_text(encoding='utf-8') + '    crossFilteringBehavior: bothDirections\n', encoding='utf-8')
        after = analyze_project(self.root)
        self.assertEqual(before.findings, after.findings)
        self.assertEqual(before.graph.evidence, after.graph.evidence)
        finding, = after.health_findings
        self.assertEqual(finding.rule_id, 'RELATIONSHIP_BIDIRECTIONAL')
        self.assertEqual(finding.scope, 'Rel1')
        self.assertEqual(finding.source_file, str(self.source))
        self.assertEqual(finding.line, 1)
        self.assertIn('Fact[Key]', finding.evidence)
        self.assertIn('does not establish a defect', finding.explanation)
        self.assertTrue(finding.recommendation)

    def test_inactive_unknown_and_annotation_values_do_not_trigger(self):
        original = self.source.read_text(encoding='utf-8')
        for extra in ('', '    crossFilteringBehavior: oneDirection\n',
                      '    crossFilteringBehavior: automatic\n',
                      '    crossFilteringBehavior: bothDirections\n    isActive: false\n',
                      '    annotation Note =\n        crossFilteringBehavior: bothDirections\n',
                      '    // crossFilteringBehavior: bothDirections\n'):
            with self.subTest(extra=extra):
                self.source.write_text(original + extra, encoding='utf-8')
                self.assertEqual(analyze_project(self.root).health_findings, ())

    def test_headers_and_blank_lines_preserve_all_endpoints(self):
        self.source.write_text("relationship 'First relation'\n    fromColumn: Fact.Key\n\n    toColumn: Dim.Key\nrelationship Second\n    fromColumn: Fact.Value\n    toColumn: Dim.Label\n", encoding='utf-8')
        relationships = parse_relationship_metadata(self.model)
        self.assertEqual([r.name for r in relationships], ['First relation', 'Second'])
        self.assertEqual([r.line for r in relationships], [1, 5])
        result = analyze_project(self.root)
        self.assertEqual(result.summary.columns.used, 4)

    def test_cli_exports_health_text_and_excel(self):
        self.source.write_text(self.source.read_text(encoding='utf-8') + '    crossFilteringBehavior: bothDirections\n', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            text, excel = run(self.root)
        self.assertIn('[RELATIONSHIP_BIDIRECTIONAL]', text.read_text(encoding='utf-8'))
        book = load_workbook(excel)
        self.addCleanup(book.close)
        self.assertEqual(book['Model health'].cell(2, 1).value, 'RELATIONSHIP_BIDIRECTIONAL')
        self.assertEqual(book['Model health'].cell(2, 5).value, 'Rel1')

    def test_explicit_many_to_many_preserves_cleanup_and_evidence(self):
        before = analyze_project(self.root)
        self.source.write_text(self.source.read_text(encoding='utf-8') + '    fromCardinality: many\n    toCardinality: many\n', encoding='utf-8')
        after = analyze_project(self.root)
        self.assertEqual(before.findings, after.findings)
        self.assertEqual(before.graph.evidence, after.graph.evidence)
        finding, = after.health_findings
        self.assertEqual(finding.rule_id, 'RELATIONSHIP_MANY_TO_MANY')
        self.assertEqual(finding.scope, 'Rel1')
        self.assertIn('fromCardinality: many', finding.evidence)
        self.assertIn('toCardinality: many', finding.evidence)
        self.assertEqual((finding.source_file, finding.line), (str(self.source), 1))

    def test_many_to_many_as_power_bi_writes_it(self):
        # TMDL omits the default fromCardinality (many); observed in a Power BI Desktop export.
        self.source.write_text(self.source.read_text(encoding='utf-8') + '    toCardinality: many\n', encoding='utf-8')
        finding, = analyze_project(self.root).health_findings
        self.assertEqual(finding.rule_id, 'RELATIONSHIP_MANY_TO_MANY')
        self.assertIn('fromCardinality: many (default, omitted in TMDL)', finding.evidence)

    def test_many_to_many_requires_many_on_both_ends(self):
        original = self.source.read_text(encoding='utf-8')
        for extra in ('',                                       # many-to-one (both defaults)
                      '    fromCardinality: many\n',            # still many-to-one
                      '    fromCardinality: one\n',             # one-to-one
                      '    fromCardinality: one\n    toCardinality: many\n',
                      '    fromCardinality: many\n    toCardinality: unknown\n',
                      '    annotation Note =\n        fromCardinality: many\n        toCardinality: many\n',
                      '    fromCardinality: many\n    toCardinality: many\n    isActive: false\n'):
            with self.subTest(extra=extra):
                self.source.write_text(original + extra, encoding='utf-8')
                self.assertEqual(analyze_project(self.root).health_findings, ())

    def test_many_to_many_and_bidirectional_are_separate_exported_findings(self):
        self.source.write_text(self.source.read_text(encoding='utf-8') + '    fromCardinality: many\n    toCardinality: many\n    crossFilteringBehavior: bothDirections\n', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            text, excel = run(self.root)
        self.assertIn('[RELATIONSHIP_MANY_TO_MANY]', text.read_text(encoding='utf-8'))
        book = load_workbook(excel)
        self.addCleanup(book.close)
        self.assertEqual([row[0] for row in book['Model health'].iter_rows(min_row=2, values_only=True)],
                         ['RELATIONSHIP_BIDIRECTIONAL', 'RELATIONSHIP_MANY_TO_MANY'])
