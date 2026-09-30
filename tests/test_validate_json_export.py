import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from tools.validation.validate_json_export import json_pointer


class ValidateJsonExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).resolve().parents[1]
        cls.script = cls.repo / 'tools/validation/validate_json_export.py'
        cls.document = analysis_to_dict(analyze_project(cls.repo / 'tools/validation/validation_suite/20_measure_descriptions'))

    def invoke(self, content, *, isolated=False):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'saved export.json'
            if content is not None:
                path.write_bytes(content)
            command = [sys.executable]
            if isolated:
                command.append('-S')
            result = subprocess.run([*command, str(self.script), str(path)], cwd=folder,
                                    capture_output=True, text=True)
            if content is not None:
                self.assertEqual(path.read_bytes(), content)
            return result

    def test_valid_export_from_other_working_directory(self):
        result = self.invoke(json.dumps(self.document).encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Valid export (schema version 1)', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_invalid_schema_values_show_json_pointer(self):
        document = json.loads(json.dumps(self.document))
        document['health_findings'][0]['severity'] = 'critical'
        result = self.invoke(json.dumps(document).encode())
        self.assertEqual(result.returncode, 1)
        self.assertIn('/health_findings/0/severity', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_malformed_json_reports_line_and_column(self):
        result = self.invoke(b'{\n "broken":\n}')
        self.assertEqual(result.returncode, 1)
        self.assertIn(':3:1:', result.stderr)

    def test_duplicate_nonstandard_and_non_utf8_inputs_fail(self):
        for content in (b'{"schema_version":1,"schema_version":1}', b'{"value":NaN}', b'\xff'):
            with self.subTest(content=content):
                result = self.invoke(content)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Invalid JSON', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_missing_file_and_dependency_are_tool_errors(self):
        self.assertEqual(self.invoke(None).returncode, 2)
        result = self.invoke(b'{}', isolated=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requirements-dev.txt', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_unknown_version_is_invalid_export(self):
        document = dict(self.document, schema_version=2)
        result = self.invoke(json.dumps(document).encode())
        self.assertEqual(result.returncode, 1)
        self.assertIn('/schema_version', result.stderr)

    def test_json_pointer_escapes_keys(self):
        self.assertEqual(json_pointer(['a/b', '~name', 0]), '/a~1b/~0name/0')
        self.assertEqual(json_pointer([]), '<root>')

    def test_schema_valid_but_inconsistent_export_is_rejected(self):
        document = json.loads(json.dumps(self.document))
        document['summary']['measures']['business_total'] = 999
        result = self.invoke(json.dumps(document).encode())
        self.assertEqual(result.returncode, 1)
        self.assertIn('/summary/measures/business_total', result.stderr)
        self.assertIn('Inconsistent export', result.stderr)
