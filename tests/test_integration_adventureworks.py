"""Optional real-project regression for the AdventureWorks PBIP sample.

Set PBI_AW_PROJECT to the folder containing `AdventureWorks Report.pbip`. The
project is not part of the repository; expected statuses are.
"""
import json
import os
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project

EXPECTED = Path(__file__).resolve().parent / 'integration' / 'adventureworks_expected.json'


@unittest.skipUnless(os.environ.get('PBI_AW_PROJECT'), 'set PBI_AW_PROJECT to run the AdventureWorks integration check')
class AdventureWorksIntegrationTests(unittest.TestCase):
    def test_statuses_and_diagnostics(self):
        expected = json.loads(EXPECTED.read_text(encoding='utf-8'))
        result = analyze_project(Path(os.environ['PBI_AW_PROJECT']))
        actual = {f'{f.ref.object_type.value}|{f.ref.table}|{f.ref.name}': f.status.value for f in result.findings}
        self.assertEqual(actual, expected['expected_status'])
        self.assertEqual([d.code for d in result.diagnostics], expected['expected_diagnostics'])
        # Every rule except documentation opportunities, which fire on all 24 measures.
        actual_findings = [{'rule_id': f.rule_id, 'scope': f.scope} for f in result.health_findings
                           if f.rule_id != 'MEASURE_DESCRIPTION_MISSING']
        self.assertEqual(actual_findings, [{k: v for k, v in f.items() if k != 'note'}
                                           for f in expected['expected_findings']])


if __name__ == '__main__':
    unittest.main()
