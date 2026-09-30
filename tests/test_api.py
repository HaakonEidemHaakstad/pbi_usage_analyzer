import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pbi_usage_analyzer import AnalysisResult, DiagnosticSeverity, analyze_project
from pbi_usage_analyzer.analysis.build_graph import build_graph
from pbi_usage_analyzer.analysis.classify import classify
from pbi_usage_analyzer.discovery import discover_project
from pbi_usage_analyzer.main import run


class AnalysisApiTests(unittest.TestCase):
    def setUp(self):
        self.suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / 'project'
        shutil.copytree(self.suite / '08_autodate_scope_guard', self.project)

    def test_api_is_silent_and_does_not_write_files(self):
        before = {p.relative_to(self.project): p.read_bytes()
                  for p in self.project.rglob('*') if p.is_file()}
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = analyze_project(str(self.project))
        self.assertIsInstance(result, AnalysisResult)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(before, {p.relative_to(self.project): p.read_bytes()
                                 for p in self.project.rglob('*') if p.is_file()})
        self.assertEqual(result.project.root, self.project)
        self.assertEqual(result.summary.columns.business_total, 3)
        self.assertEqual(result.summary.columns.internal, 2)
        self.assertEqual(result.summary.columns.likely_unused, 2)
        self.assertEqual(result.summary.columns.manual_review, 1)
        self.assertEqual(result.objects, tuple(result.graph.objects.values()))
        self.assertTrue(result.graph.evidence)

    def test_all_fixtures_match_existing_pipeline(self):
        for folder in sorted(self.suite.iterdir()):
            if not folder.is_dir():
                continue
            with self.subTest(scenario=folder.name):
                paths = discover_project(folder)
                context = build_graph(paths.report_folder, paths.model_folder)
                result = analyze_project(folder)
                self.assertEqual(result.findings, classify(context.graph))
                self.assertEqual(result.graph.evidence, context.graph.evidence)
                self.assertEqual([d.message for d in result.diagnostics], context.warnings)
                self.assertTrue(all(d.severity == DiagnosticSeverity.WARNING for d in result.diagnostics))
                self.assertEqual(result.summary.query_dependencies, len(context.powerquery.dependencies))

    def test_repeated_calls_do_not_share_graph_state(self):
        first = analyze_project(self.project)
        first.graph.objects.clear()
        first.findings.clear()
        second = analyze_project(self.project)
        self.assertTrue(second.objects)
        self.assertTrue(second.findings)

    def test_invalid_project_errors_propagate(self):
        with self.assertRaises(NotADirectoryError):
            analyze_project(self.project / 'missing')
        with self.assertRaises(RuntimeError):
            analyze_project(Path(self.tmp.name))

    def test_cli_uses_api_and_still_exports_reports(self):
        with patch('pbi_usage_analyzer.main.analyze_project', wraps=analyze_project) as analyze:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                text, excel = run(self.project)
            analyze.assert_called_once_with(self.project)
        self.assertTrue(text.is_file())
        self.assertTrue(excel.is_file())
        self.assertIn('Columns: 3\n', output.getvalue())
        self.assertIn('2 of 3 columns', text.read_text())
