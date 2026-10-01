import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.health.rules import duplicate_measures
from pbi_usage_analyzer.model import ModelObject, ObjectRef, ObjectType
from pbi_usage_analyzer.parsers.dax_lexer import normalize_dax
from tools.validation.export_consistency import consistency_errors

SCENARIO = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/37_duplicate_measures'


def measure(table, name, expression, line=1):
    return ModelObject(ObjectRef(ObjectType.MEASURE, table, name), source_file=f'{table}.tmdl',
                       expression=expression, source_line=line, description='')


class NormalizeDaxTests(unittest.TestCase):
    def test_lexical_differences_are_ignored(self):
        base = normalize_dax("SUMX(Sales, Sales[Qty] * 'Sales'[Price])")
        for variant in ("sumx( 'Sales' ,\n\tSALES[ qty ]*Sales[price] )",
                        "SUMX(Sales, /* note */ Sales[Qty] * Sales[Price]) // trailing",
                        "SUMX(Sales, -- dash comment\n Sales[Qty] * Sales[Price])"):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_dax(variant), base)

    def test_meaningful_differences_are_kept(self):
        base = normalize_dax('IF([A] > 0, "Yes")')
        for variant in ('IF([A] > 0, "YES")', 'IF([A] >= 0, "Yes")', 'IF([B] > 0, "Yes")',
                        "IF('T x'[A] > 0, \"Yes\")"):
            with self.subTest(variant=variant):
                self.assertNotEqual(normalize_dax(variant), base)
        self.assertNotEqual(normalize_dax("VAR a = 1 RETURN a"), normalize_dax("VAR a = 1 RETURNa"))

    def test_quoted_tables_with_spaces_and_escapes(self):
        self.assertEqual(normalize_dax("SUM('Sales Data'[Amount])"), normalize_dax("sum( 'sales data' [amount] )"))
        self.assertEqual(normalize_dax("SUM('Bob''s'[X])"), "sum('bob''s'[x])")
        self.assertEqual(normalize_dax('"a""b"'), '"a""b"')

    def test_unterminated_input(self):
        for text in ('SUM([A]) & "open', 'SUM([A]) /* open', "SUM('Sales[A])", 'SUM([A)'):
            with self.subTest(text=text):
                self.assertIsNone(normalize_dax(text))


class DuplicateRuleUnitTests(unittest.TestCase):
    def test_groups_constants_and_internal_tables(self):
        objects = (
            measure('Sales', 'A', 'SUM(Sales[X])', 3),
            measure('Sales', 'B', 'sum(Sales[X])', 5),
            measure('Other', 'C', 'SUM( Sales[X] )', 7),
            measure('Sales', 'Zero 1', '0'),
            measure('Sales', 'Zero 2', '0'),
            measure('LocalDateTable_1', 'D', 'SUM(Sales[X])'),
            measure('Sales', 'Unknown line', 'SUM(Sales[X])', None),
            ModelObject(ObjectRef(ObjectType.COLUMN, 'Sales', 'Calc'), expression='SUM(Sales[X])', source_line=9),
        )
        findings = duplicate_measures(objects)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual((finding.scope, finding.line, finding.severity), ('Sales[A]', 3, HealthSeverity.INFO))
        self.assertEqual(finding.evidence, ('Sales[A] (Sales.tmdl line 3)', 'Sales[B] (Sales.tmdl line 5)',
                                            'Other[C] (Other.tmdl line 7)', 'Expression: SUM(Sales[X])'))


class DuplicateRuleScenarioTests(unittest.TestCase):
    def test_scenario(self):
        result = analyze_project(SCENARIO)
        findings = {f.scope: f for f in result.health_findings if f.rule_id == 'MEASURE_DUPLICATE_EXPRESSION'}
        self.assertEqual(set(findings), {'Budget[Budget Revenue]', 'Budget[Plain]'})
        revenue = findings['Budget[Budget Revenue]']
        self.assertEqual(revenue.evidence[:3], ('Budget[Budget Revenue] (Budget.tmdl line 6)',
                                                'Sales[Total Revenue] (Sales.tmdl line 8)',
                                                'Sales[Copy of Total Revenue] (Sales.tmdl line 10)'))
        self.assertEqual(len(findings['Budget[Plain]'].evidence), 3)   # Plain, Commented, expression
        self.assertEqual(consistency_errors(analysis_to_dict(result)), [])


if __name__ == '__main__':
    unittest.main()
