import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.model import EvidenceType, ObjectRef, ObjectType, Status
from pbi_usage_analyzer.parsers.dax import dax_dependencies
from pbi_usage_analyzer.util import norm_key
from tools.validation.export_consistency import consistency_errors

AMBIGUOUS = EvidenceType.DAX_UNQUALIFIED_COLUMN_REFERENCE


def index(kind, *labels):
    refs = {}
    for label in labels:
        table, name = label.rstrip(']').split('[')
        refs[norm_key(table, name)] = ObjectRef(kind, table, name)
    return refs


class UnqualifiedColumnTests(unittest.TestCase):
    columns = index(ObjectType.COLUMN, 'Sales[Quantity]', 'Sales[Price]', 'Sales[Amount]',
                    'Budget[Amount]', 'Budget[Target]', 'LocalDateTable_1[Year]')
    measures = index(ObjectType.MEASURE, 'Sales[Rate]', 'Sales[Margin]')

    def edges(self, owner, expression, **kwargs):
        found = dax_dependencies(owner, expression, self.columns, self.measures, **kwargs)
        return {(e.target.label, e.evidence_type) for e in found}

    def test_calculated_column_row_context(self):
        owner = ObjectRef(ObjectType.COLUMN, 'Sales', 'Line Total')
        self.assertEqual(self.edges(owner, '[Quantity] * [Price] * [Rate]', row_table='Sales'), {
            ('Sales[Quantity]', EvidenceType.DAX_DEPENDENCY),
            ('Sales[Price]', EvidenceType.DAX_DEPENDENCY),
            ('Sales[Rate]', EvidenceType.DAX_DEPENDENCY),
        })

    def test_measure_unqualified_column_is_manual_review_evidence(self):
        owner = ObjectRef(ObjectType.MEASURE, 'Sales', 'Total')
        self.assertEqual(self.edges(owner, 'SUMX(Sales, [Quantity])'), {('Sales[Quantity]', AMBIGUOUS)})

    def test_ambiguous_name_narrowed_by_mentioned_table(self):
        owner = ObjectRef(ObjectType.MEASURE, 'Sales', 'Total')
        self.assertEqual(self.edges(owner, "SUMX('Budget', [Amount])"), {('Budget[Amount]', AMBIGUOUS)})
        self.assertEqual(self.edges(owner, 'SUMX(FILTER(ALL(Sales), 1), [Amount])'), {('Sales[Amount]', AMBIGUOUS)})
        self.assertEqual(self.edges(owner, 'SUMX(VALUES(x), [Amount])'),
                         {('Sales[Amount]', AMBIGUOUS), ('Budget[Amount]', AMBIGUOUS)})

    def test_table_mentions_ignore_strings_comments_and_other_identifiers(self):
        owner = ObjectRef(ObjectType.MEASURE, 'Sales', 'Total')
        expression = 'SUMX(Budget, [Amount]) & "Sales" // Sales\n + [SalesAmount] + BudgetX'
        self.assertEqual(self.edges(owner, expression), {('Budget[Amount]', AMBIGUOUS)})

    def test_measures_take_precedence_and_internal_tables_are_skipped(self):
        owner = ObjectRef(ObjectType.MEASURE, 'Budget', 'Total')
        self.assertEqual(self.edges(owner, '[Margin] + [Year] + [Missing]'),
                         {('Sales[Margin]', EvidenceType.DAX_DEPENDENCY)})

    def test_row_context_column_is_not_also_ambiguous(self):
        owner = ObjectRef(ObjectType.COLUMN, 'Budget', 'Gap')
        self.assertEqual(self.edges(owner, '[Target] - [Amount]', row_table='Budget'), {
            ('Budget[Target]', EvidenceType.DAX_DEPENDENCY),
            ('Budget[Amount]', EvidenceType.DAX_DEPENDENCY),
        })


class KeywordBeforeBracketTests(unittest.TestCase):
    """Words before `[` are not a table unless they end in a known table name."""
    columns = index(ObjectType.COLUMN, 'Sales[Flag]')
    measures = index(ObjectType.MEASURE, 'Sales[Margin]', 'Sales[Discount]')

    def test_keywords_and_variables_do_not_swallow_references(self):
        owner = ObjectRef(ObjectType.MEASURE, 'Sales', 'X')
        cases = {
            'VAR a = 1\nRETURN\n    [Margin]': {'Sales[Margin]'},
            'VAR Total = 1 RETURN Total - [Discount]': {'Sales[Discount]'},
            'NOT [Margin]': {'Sales[Margin]'},
            'FILTER(Sales, NOT Sales[Flag])': {'Sales[Flag]'},
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                found = dax_dependencies(owner, expression, self.columns, self.measures)
                self.assertEqual({e.target.label for e in found}, expected)
                self.assertTrue(all(e.evidence_type == EvidenceType.DAX_DEPENDENCY for e in found))

    def test_stale_quoted_reference_is_not_reinterpreted(self):
        owner = ObjectRef(ObjectType.MEASURE, 'Sales', 'X')
        self.assertEqual(dax_dependencies(owner, "SUM('Old'[Flag])", self.columns, self.measures), [])


class UnqualifiedScenarioTests(unittest.TestCase):
    def setUp(self):
        suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        self.result = analyze_project(suite / '28_dax_unqualified_columns')
        self.statuses = {f.ref.label: f.status for f in self.result.findings}

    def test_statuses(self):
        expected = {
            'Sales[Line Total]': Status.USED,
            'Sales[Quantity]': Status.USED,
            'Sales[Price]': Status.USED,
            'Sales[Region]': Status.USED,
            'Sales[Summary]': Status.USED,
            'Sales[Cost Total]': Status.USED,
            'Sales[Cost]': Status.USED,
            'Sales[Amount]': Status.MANUAL_REVIEW,
            'Budget[Amount]': Status.LIKELY_UNUSED,
            'Sales[Unused]': Status.LIKELY_UNUSED,
        }
        for label, status in expected.items():
            self.assertEqual(self.statuses[label], status, label)

    def test_rls_row_context_and_export_consistency(self):
        rls = [e for e in self.result.graph.evidence if e.evidence_type == EvidenceType.RLS_DEPENDENCY]
        self.assertEqual({e.target.label for e in rls}, {'Sales[Region]'})
        self.assertFalse(any(e.evidence_type == AMBIGUOUS and e.source.table.startswith('Special:')
                             for e in self.result.graph.evidence))
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])


if __name__ == '__main__':
    unittest.main()
