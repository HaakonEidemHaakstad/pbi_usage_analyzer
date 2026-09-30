import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.model import ObjectRef, ObjectType
from pbi_usage_analyzer.parsers.dax import DaxIndex, unresolved_references
from pbi_usage_analyzer.util import norm_key

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


class UnresolvedReferenceTests(unittest.TestCase):
    index = DaxIndex.build({norm_key('Sales', 'Amount'): ObjectRef(ObjectType.COLUMN, 'Sales', 'Amount')},
                           {norm_key('Sales', 'Total'): ObjectRef(ObjectType.MEASURE, 'Sales', 'Total')})

    def test_forms(self):
        cases = {
            "SUM('Sales'[Revenue])": [('Sales', 'Revenue', True)],
            'SUM(Sales[Nope])': [('Sales', 'Nope', True)],
            "SUM('Old'[Amount])": [('Old', 'Amount', False)],
            "SUM('SALES'[amount]) + 'sales'[total]": [],
            'VAR a = 1 RETURN [Missing] + NOT [Other]': [],
            "1 // 'Sales'[Ghost]\n + 0 /* Sales[Ghost] */": [],
            '"Sales[Ghost]"': [],
            'SUM(Unknown[Amount])': [],   # plain unknown word: may not be a table reference
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(unresolved_references(expression, self.index), expected)

    def test_scenario_findings(self):
        result = analyze_project(SUITE / '33_dax_unresolved_references')
        findings = {f.scope: f for f in result.health_findings if f.rule_id == 'DAX_REFERENCE_UNRESOLVED'}
        self.assertEqual(set(findings), {'Sales[Bad Calc]', 'Sales[Stale]', 'Sales[Missing Table]'})
        self.assertEqual(findings['Sales[Stale]'].confidence, 'high')
        self.assertEqual(findings['Sales[Missing Table]'].confidence, 'medium')
        self.assertTrue(all(f.severity == HealthSeverity.WARNING for f in findings.values()))
        self.assertIn("'Sales'[Revenue]", ' '.join(findings['Sales[Stale]'].evidence))
        self.assertTrue(findings['Sales[Stale]'].source_file.endswith('Sales.tmdl'))
        self.assertGreater(findings['Sales[Stale]'].line, 0)


if __name__ == '__main__':
    unittest.main()
