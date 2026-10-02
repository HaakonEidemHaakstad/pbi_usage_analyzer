"""Command line: several projects, --out folder, .pbip arguments, exit codes."""
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from pbi_usage_analyzer.main import cli

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ('02_dax_transitive', '41_m_usage_aware_lineage'):
            shutil.copytree(SUITE / name, self.tmp / name)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def test_several_projects_into_one_folder(self):
        reports = self.tmp / 'reports'
        code, out, _ = self.run_cli(self.tmp / '02_dax_transitive', self.tmp / '41_m_usage_aware_lineage',
                                    '--out', reports)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in reports.glob('*_usage_summary_v2.txt')),
                         ['02_dax_transitive_usage_summary_v2.txt', '41_m_usage_aware_lineage_usage_summary_v2.txt'])
        self.assertEqual(len(list(reports.glob('*.xlsx'))), 2)
        self.assertIn('Analyzed 2 of 2 projects.', out)
        self.assertFalse(list((self.tmp / '02_dax_transitive').glob('*_usage_*')))  # projects untouched

    def test_default_writes_next_to_the_project_and_accepts_a_pbip_file(self):
        pbip = next((self.tmp / '02_dax_transitive').glob('*.pbip'))
        code, _, _ = self.run_cli(pbip)
        self.assertEqual(code, 0)
        self.assertTrue(list(pbip.parent.glob('*_usage_summary_v2.txt')))

    def test_a_failing_project_does_not_stop_the_others(self):
        code, out, err = self.run_cli(self.tmp / 'missing', self.tmp / '02_dax_transitive', '--out', self.tmp / 'r')
        self.assertEqual(code, 1)
        self.assertIn('Could not analyze', err)
        self.assertIn('Analyzed 1 of 2 projects.', out)
        self.assertTrue(list((self.tmp / 'r').glob('02_dax_transitive_usage_summary_v2.txt')))


if __name__ == '__main__':
    unittest.main()
