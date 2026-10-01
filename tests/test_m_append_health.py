import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.health.rules import annual_appends, loaded_append_inputs
from pbi_usage_analyzer.parsers.m_queries import MQuery, MQueryKind, appended_query_refs
from tools.validation.export_consistency import consistency_errors

SCENARIO = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/35_m_append_health'


def query(name, source, kind=MQueryKind.PARTITION):
    return MQuery(name, kind, source, f'{name}.tmdl', tuple(range(10, 10 + source.count('\n') + 1)))


class AppendedQueryRefsTests(unittest.TestCase):
    def test_bare_identifiers_with_lines(self):
        source = 'let\n  S = Table.Combine( {#"A ""x"" 2020", B,\n  C} )\nin S'
        self.assertEqual(appended_query_refs(source), [('A "x" 2020', 2), ('B', 2), ('C', 2)])

    def test_comments_strings_and_nested_expressions_are_not_appends(self):
        source = ('let\n  // Table.Combine({A})\n  /* Table.Combine({B}) */ T = "Table.Combine({C})",\n'
                  '  S = Table.Combine({Table.FirstN(D, 1), E[x], #"F, }" , {G}})\nin S')
        self.assertEqual(appended_query_refs(source), [('F, }', 4)])

    def test_local_steps_shadow_queries(self):
        source = 'let\n  A = #table({}, {}),\n  #"B C" = A,\n  S = Table.Combine({A, #"B C", D})\nin S'
        self.assertEqual(appended_query_refs(source), [('D', 4)])

    def test_field_access_and_comparisons_are_not_bindings(self):
        source = 'let S = Table.Combine({A, B}), F = Table.SelectRows(S, each [A] = 1 and B <> 2) in F'
        self.assertEqual(appended_query_refs(source), [('A', 1), ('B', 1)])

    def test_unterminated_list_and_qualified_name(self):
        self.assertEqual(appended_query_refs('Table.Combine({A, B'), [])
        self.assertEqual(appended_query_refs('My.Table.Combine({A})'), [])


class AppendRuleUnitTests(unittest.TestCase):
    def test_only_loaded_into_loaded_is_reported(self):
        queries = (
            query('Sales', 'Table.Combine({Y2020, Y2021, Expr, Param})'),
            query('Y2020', '#table({}, {})'),
            query('Y2021', '#table({}, {})'),
            query('Expr', '#table({}, {})', MQueryKind.EXPRESSION),
            query('Param', '"x" meta [IsParameterQuery=true]', MQueryKind.PARAMETER),
            query('Staging', 'Table.Combine({Y2020})', MQueryKind.EXPRESSION),
        )
        findings = loaded_append_inputs(queries)
        self.assertEqual([f.scope for f in findings], ['Y2020', 'Y2021'])
        self.assertEqual(findings[0].line, 10)
        self.assertEqual(findings[0].evidence[0], "Appended by query 'Sales' (Table.Combine, Sales.tmdl line 10)")

    def test_year_confidence_and_self_reference(self):
        queries = (
            query('Hovedbok', 'let\n  F = #table({}, {}),\n  C = Table.Combine({F, #"Hovedbok 2024"})\nin C'),
            query('Hovedbok 2024', '#table({}, {})', MQueryKind.EXPRESSION),
            query('Self 2020', 'Table.Combine({#"Self 2020", Q20201})'),
            query('Q20201', '#table({}, {})'),
        )
        findings = annual_appends(queries)
        self.assertEqual([(f.scope, f.confidence, f.line) for f in findings], [('Hovedbok', 'medium', 12)])
        self.assertEqual(findings[0].severity, HealthSeverity.INFO)


class AppendRuleScenarioTests(unittest.TestCase):
    def setUp(self):
        self.result = analyze_project(SCENARIO)
        self.findings = {(f.rule_id, f.scope): f for f in self.result.health_findings}

    def test_loaded_input(self):
        finding = self.findings[('POWERQUERY_APPEND_INPUT_LOADED', 'Sales 2022')]
        self.assertEqual(finding.severity, HealthSeverity.WARNING)
        self.assertTrue(finding.source_file.endswith('Sales 2022.tmdl'))
        self.assertEqual(finding.line, 7)   # first M line (`let`)
        self.assertIn("Appended by query 'Sales' (Table.Combine, Sales.tmdl line 10)", finding.evidence)

    def test_annual_appends(self):
        sales = self.findings[('POWERQUERY_ANNUAL_APPEND', 'Sales')]
        self.assertEqual(sales.confidence, 'high')
        self.assertEqual(len(sales.evidence), 2)   # Sales 2022 and sales_2023; not #"sales 2022"
        returns = self.findings[('POWERQUERY_ANNUAL_APPEND', 'Returns')]
        self.assertEqual((returns.confidence, returns.line), ('medium', 9))
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])


if __name__ == '__main__':
    unittest.main()
