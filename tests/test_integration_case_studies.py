"""Optional real-project regressions for the AdventureWorks case studies.

Each project is built by hand in Power BI Desktop (docs/CASE_STUDY_BUILD_GUIDE.md)
and lives outside the repository; its verified expectations are stored here. Set
the environment variable to the folder containing the .pbip file to run a check.
"""
import json
import os
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project

INTEGRATION = Path(__file__).resolve().parent / 'integration'


class CaseStudyMixin:
    env_var = ''
    expected_file = ''

    def test_statuses_diagnostics_and_findings(self):
        expected = json.loads((INTEGRATION / self.expected_file).read_text(encoding='utf-8'))
        result = analyze_project(Path(os.environ[self.env_var]))
        business = {f'{f.ref.object_type.value}|{f.ref.table}|{f.ref.name}': f.status.value
                    for f in result.findings if not f.status.value.startswith('Internal')}
        self.assertEqual(business, expected['expected_status'])
        self.assertEqual(sum(f.status.value.startswith('Internal') for f in result.findings),
                         expected['internal_objects'])
        self.assertEqual([d.code for d in result.diagnostics], expected['expected_diagnostics'])
        self.assertEqual([{'rule_id': h.rule_id, 'scope': h.scope} for h in result.health_findings],
                         expected['expected_findings'])
        # Every conservative difference from the independent review is explained.
        for key in expected['manual_review_notes']:
            self.assertEqual(expected['expected_status'][key], 'Needs manual review', key)


@unittest.skipUnless(os.environ.get('PBI_AW_MESS_PROJECT'),
                     'set PBI_AW_MESS_PROJECT to run the AW Mess case-study check')
class AwMessCaseStudyTests(CaseStudyMixin, unittest.TestCase):
    env_var = 'PBI_AW_MESS_PROJECT'
    expected_file = 'aw_mess_expected.json'


if __name__ == '__main__':
    unittest.main()
