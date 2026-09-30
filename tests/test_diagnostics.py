import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pbi_usage_analyzer import Diagnostic, DiagnosticSeverity, analyze_project
from pbi_usage_analyzer.discovery import discover_project
from pbi_usage_analyzer.model import ObjectRef, ObjectType
from pbi_usage_analyzer.parsers.tmdl import parse_model
from pbi_usage_analyzer.reporting.text_report import generate_text


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        fixture = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/08_autodate_scope_guard'
        shutil.copytree(fixture, self.root)
        self.paths = discover_project(self.root)
        self.internal = self.paths.model_folder / 'definition/tables/LocalDateTable_test.tmdl'

    def test_json_error_has_exact_location_and_preserves_report_warning(self):
        source = self.paths.report_folder / 'definition/report.json'
        source.write_text('{\n  "broken":\n}', encoding='utf-8')
        result = analyze_project(self.root)
        diagnostic, = [d for d in result.diagnostics if d.code == 'PBIR_READ_FAILED']
        self.assertIsInstance(diagnostic, Diagnostic)
        self.assertEqual(diagnostic.severity, DiagnosticSeverity.WARNING)
        self.assertEqual(diagnostic.source_file, str(source))
        self.assertEqual((diagnostic.line, diagnostic.column), (3, 1))
        self.assertIsNone(diagnostic.object_ref)
        self.assertIn(diagnostic.message, generate_text(result.project.project_name, result.findings, result.context))
        self.assertEqual(result.context.warnings, [d.message for d in result.diagnostics])

    def test_tmdl_failure_has_file_without_invented_line(self):
        with patch('pbi_usage_analyzer.parsers.tmdl.parse_table_file', side_effect=ValueError('invalid definition')):
            result = parse_model(self.paths.model_folder)
        self.assertTrue(result.diagnostics)
        for diagnostic in result.diagnostics:
            self.assertEqual(diagnostic.code, 'TMDL_PARSE_FAILED')
            self.assertTrue(Path(diagnostic.source_file).is_file())
            self.assertIsNone(diagnostic.line)
            self.assertIsNone(diagnostic.column)
        self.assertEqual(result.warnings, [d.message for d in result.diagnostics])

    def test_incomplete_m_and_unresolved_backing_column_keep_provenance(self):
        self.internal.write_text(self.internal.read_text().replace('Table.SelectColumns(Source, {"Date"})', 'CustomFunction(Source)'))
        result = analyze_project(self.root)
        codes = {d.code for d in result.diagnostics}
        self.assertIn('M_LINEAGE_INCOMPLETE', codes)
        self.assertIn('AUTODATE_BACKING_COLUMN_UNRESOLVED', codes)
        for diagnostic in result.diagnostics:
            self.assertEqual(diagnostic.source_file, str(self.internal))
            self.assertEqual(diagnostic.object_ref, ObjectRef(ObjectType.QUERY, 'LocalDateTable_test'))
            self.assertIsNone(diagnostic.line)
        self.assertEqual(result.context.warnings, [d.message for d in result.diagnostics])

    def test_unresolved_source_column_points_to_referencing_query(self):
        self.internal.write_text(self.internal.read_text().replace('{"Date"}', '{"MissingDate"}'))
        result = analyze_project(self.root)
        diagnostic, = [d for d in result.diagnostics if d.code == 'AUTODATE_SOURCE_COLUMN_UNRESOLVED']
        self.assertEqual(diagnostic.source_file, str(self.internal))
        self.assertEqual(diagnostic.object_ref, ObjectRef(ObjectType.QUERY, 'LocalDateTable_test'))
        self.assertEqual(diagnostic.message, 'Unresolved auto-date source column: Sales[MissingDate]')
