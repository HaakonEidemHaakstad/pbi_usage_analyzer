import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pbi_usage_analyzer import analyze_project, analysis_to_dict, generate_json, write_json
from pbi_usage_analyzer.main import cli


class JsonReportTests(unittest.TestCase):
    def setUp(self):
        self.suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        shutil.copytree(self.suite / '20_measure_descriptions', self.root)

    def test_round_trip_schema_and_filter_scope(self):
        result = analyze_project(self.root, health_severities=[])
        document = json.loads(generate_json(result))
        self.assertEqual(document, analysis_to_dict(result))
        self.assertEqual(document['schema_version'], 1)
        self.assertEqual(document['health_findings'], [])
        self.assertEqual(document['health_filter_scope']['severities'], [])
        self.assertIsNone(document['health_filter_scope']['rule_ids'])
        self.assertEqual(document['health_filter_scope']['total_findings'], 2)
        self.assertEqual(document['summary']['measures']['business_total'], 4)
        self.assertEqual(document['summary']['measures']['internal'], 1)
        self.assertEqual({f['status_id'] for f in document['cleanup_findings']}, {'LIKELY_UNUSED', 'INTERNAL'})
        self.assertNotIn('context', document)

    def test_every_fixture_serializes_without_mutation(self):
        for folder in sorted(self.suite.iterdir()):
            if not folder.is_dir():
                continue
            with self.subTest(folder=folder.name):
                result = analyze_project(folder)
                before = list(result.graph.evidence)
                first = generate_json(result)
                self.assertEqual(first, generate_json(result))
                document = json.loads(first)
                self.assertEqual(len(document['objects']), len(result.objects))
                self.assertEqual(len(document['dependency_evidence']), len(before))
                self.assertEqual(before, result.graph.evidence)
                self.assertEqual(len(document['diagnostics']), len(result.diagnostics))

    def test_unicode_and_file_write(self):
        result = analyze_project(self.root)
        result.project.project_name = 'Økonomi 日本語'
        output = Path(self.tmp.name) / 'analysis.json'
        write_json(output, result)
        self.assertIn('Økonomi 日本語', output.read_text(encoding='utf-8'))
        self.assertEqual(json.loads(output.read_text())['project']['project_name'], 'Økonomi 日本語')

    def test_cli_json_export_uses_selected_scope(self):
        with patch('sys.argv', ['analyzer', str(self.root), '--json', '--health-severity', 'warning']):
            with contextlib.redirect_stdout(io.StringIO()):
                cli()
        output, = self.root.glob('*_usage_analysis_v2.json')
        document = json.loads(output.read_text())
        self.assertEqual(document['health_filter_scope']['severities'], ['warning'])
        self.assertEqual(document['health_findings'], [])
        self.assertTrue(list(self.root.glob('*.xlsx')))
        self.assertTrue(list(self.root.glob('*_usage_summary_v2.txt')))
