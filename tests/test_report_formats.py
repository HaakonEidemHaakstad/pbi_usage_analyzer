"""Unsupported save formats must be reported, never silently produce Likely unused."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.model import Status

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


class ReportFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def statuses(self, result):
        return {f.ref.label: f.status for f in result.findings}

    def test_legacy_report_warns_and_protects_referenced_fields(self):
        result = analyze_project(SUITE / '43_legacy_report_format')
        self.assertEqual([d.code for d in result.diagnostics], ['PBIR_LEGACY_FORMAT'])
        statuses = self.statuses(result)
        self.assertEqual(statuses['Sales[Region]'], Status.MANUAL_REVIEW)
        self.assertEqual(statuses['Sales[Total]'], Status.MANUAL_REVIEW)
        self.assertEqual(statuses['Sales[Unused]'], Status.LIKELY_UNUSED)

    def test_missing_report_definition_is_reported(self):
        project = Path(self.tmp.name) / 'project'
        shutil.copytree(SUITE / '43_legacy_report_format', project)
        (next(project.glob('*.Report')) / 'report.json').unlink()
        result = analyze_project(project)
        self.assertEqual([d.code for d in result.diagnostics], ['PBIR_DEFINITION_MISSING'])

    def test_pbir_projects_get_no_format_diagnostic(self):
        codes = {d.code for d in analyze_project(SUITE / '02_dax_transitive').diagnostics}
        self.assertFalse(codes & {'PBIR_LEGACY_FORMAT', 'PBIR_DEFINITION_MISSING'})

    def test_model_bim_explains_how_to_save_as_tmdl(self):
        project = Path(self.tmp.name) / 'bim'
        (project / 'Bim.Report' / 'definition' / 'pages').mkdir(parents=True)
        (project / 'Bim.SemanticModel').mkdir()
        (project / 'Bim.SemanticModel' / 'model.bim').write_text(json.dumps({'model': {}}), encoding='utf-8')
        with self.assertRaises(FileNotFoundError) as caught:
            analyze_project(project)
        self.assertIn('model.bim', str(caught.exception))
        self.assertIn('TMDL', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
