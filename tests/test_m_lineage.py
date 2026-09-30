import unittest

from pbi_usage_analyzer.parsers.m_lineage import ColumnDemand, infer_column_demands
from pbi_usage_analyzer.util import norm


class MLineageTests(unittest.TestCase):
    def infer(self, source):
        return infer_column_demands(source, {norm(t): t for t in ('Source', 'Other', 'Års data')}, 'Output')

    def test_forward_aliases_nested_projection_and_comments(self):
        result = self.infer('let Final = Table.SelectColumns(Start, {"BELØP "}), Start = #"Års data" /* outer /* nested */ end */ in Final')
        self.assertTrue(result['Års data'].accepts('beløp'))
        self.assertFalse(result['Års data'].accepts('Other'))

    def test_remove_keeps_schema_requirement_by_default(self):
        result = self.infer('Table.SelectColumns(Table.RemoveColumns(Source, {"Removed"}), {"Kept"})')['Source']
        self.assertTrue(result.accepts('Removed'))
        self.assertTrue(result.accepts('Kept'))
        self.assertFalse(result.accepts('Unrelated'))

    def test_ignore_missing_allows_removed_column_pruning(self):
        result = self.infer('Table.RemoveColumns(Source, {"Removed"}, MissingField.Ignore)')['Source']
        self.assertFalse(result.accepts('Removed'))
        self.assertTrue(result.accepts('Unknown future column'))

    def test_combine_merges_demands_for_same_query(self):
        result = self.infer('Table.Combine({Table.RemoveColumns(Source, {"A", "B"}, MissingField.Ignore), Table.SelectColumns(Source, {"A"})})')['Source']
        self.assertTrue(result.accepts('A'))
        self.assertFalse(result.accepts('B'))
        self.assertTrue(result.accepts('C'))

    def test_select_after_combine(self):
        result = self.infer('Table.SelectColumns(Table.Combine({Source, Other}), {"Key"})')
        self.assertEqual(set(result), {'Source', 'Other'})
        self.assertTrue(all(d.accepts('Key') and not d.accepts('Other') for d in result.values()))

    def test_unknown_and_unsupported_shapes_fail_closed(self):
        for source in ('Unknown', 'Table.SelectColumns(Unknown, {"A"})', 'Table.AddColumn(Source, "A", each 1)', 'Table.Combine({Source}, {"A"})', 'Table.RemoveColumns(Source, {"A"}, MissingField.UseNull)', 'Source trailing', '"Source"'):
            with self.subTest(source=source):
                self.assertIsNone(self.infer(source))

    def test_cycles_and_case_sensitive_local_steps(self):
        for source in ('let A = B, B = A in A', 'let Source = Source in Source', 'let Step = Source in step', 'Output'):
            with self.subTest(source=source):
                self.assertIsNone(self.infer(source))

    def test_comments_dead_steps_and_empty_queries(self):
        self.assertEqual(self.infer('Table.Combine({}) // Source'), {})
        self.assertEqual(set(self.infer('let Dead = Other, Live = Source in Live')), {'Source'})
        self.assertIsNone(self.infer('Source /* unclosed'))

    def test_quoted_identifiers_and_doubled_quotes(self):
        result = self.infer('let #"my ""step" = Source in Table.SelectColumns(#"my ""step", {"a""b"})')
        self.assertTrue(result['Source'].accepts('a"b'))

    def test_empty_demand_retains_query_reference(self):
        self.assertEqual(self.infer('Table.SelectColumns(Source, {})')['Source'].included, frozenset())

    def test_union_preserves_schema_requirements(self):
        merged = ColumnDemand(frozenset({'a'}), required=frozenset({'b'})).union(ColumnDemand(frozenset({'c'})))
        self.assertTrue(all(merged.accepts(c) for c in ('a', 'b', 'c')))
        self.assertFalse(merged.accepts('d'))

    def test_depth_limit_is_conservative(self):
        self.assertIsNone(self.infer('(' * 100 + 'Source' + ')' * 100))

    def test_shadowed_library_functions_fail_closed(self):
        self.assertIsNone(self.infer('let #"Table.SelectColumns" = Source in Table.SelectColumns(Source, {"A"})'))

    def test_default_select_preserves_schema_after_later_projection(self):
        result = self.infer('Table.SelectColumns(Table.SelectColumns(Source, {"A", "B"}), {"A"})')['Source']
        self.assertTrue(result.accepts('B'))
        self.assertFalse(result.accepts('C'))

    def test_rename_maps_output_back_to_source(self):
        demand = self.infer('Table.SelectColumns(Table.RenameColumns(Source, {{"Old", "New"}}), {"New"})')['Source']
        self.assertTrue(demand.accepts('Old'))
        self.assertFalse(demand.accepts('Unrelated'))
        self.assertFalse(demand.accepts('New'))

    def test_rename_ignore_preserves_both_possible_sources(self):
        demand = self.infer('Table.SelectColumns(Table.RenameColumns(Source, {"Old", "New"}, MissingField.Ignore), {"New"})')['Source']
        self.assertTrue(demand.accepts('Old'))
        self.assertTrue(demand.accepts('New'))
        self.assertFalse(demand.accepts('Unrelated'))

    def test_separate_rename_steps_compose(self):
        demand = self.infer('let A = Table.RenameColumns(Source, {{"Old", "Middle"}}), B = Table.RenameColumns(A, {{"Middle", "New"}}) in Table.SelectColumns(B, {"New"})')['Source']
        self.assertTrue(demand.accepts('Old'))
        self.assertFalse(demand.accepts('Middle'))
        self.assertFalse(demand.accepts('Unrelated'))

    def test_type_transform_preserves_operational_columns(self):
        demand = self.infer('Table.SelectColumns(Table.TransformColumnTypes(Source, {{"Amount", type number}, {"Key", Int64.Type}}, "en-US"), {"Amount"})')['Source']
        self.assertTrue(demand.accepts('Amount'))
        self.assertTrue(demand.accepts('Key'))
        self.assertFalse(demand.accepts('Unrelated'))

    def test_rename_exclusions_follow_output_names(self):
        demand = self.infer('Table.RemoveColumns(Table.RenameColumns(Source, {"Old", "New"}, MissingField.Ignore), {"New"}, MissingField.Ignore)')['Source']
        self.assertFalse(demand.accepts('Old'))
        self.assertTrue(demand.accepts('Other'))

    def test_type_single_pair_and_nullable_scalar(self):
        demand = self.infer('Table.SelectColumns(Table.TransformColumnTypes(Source, {"A", type nullable number}), {})')['Source']
        self.assertTrue(demand.accepts('A'))
        self.assertFalse(demand.accepts('B'))

    def test_rename_and_type_unsupported_forms_fall_back(self):
        for expression in (
            'Table.RenameColumns(Source, {{"A", "B"}, {"B", "C"}})',
            'Table.RenameColumns(Source, {{"A", "X"}, {"B", "X"}})',
            'Table.RenameColumns(Source, DynamicNames)',
            'Table.TransformColumnTypes(Source, {{"A", CustomType}})',
            'Table.TransformColumnTypes(Source, {{"A", type table}})',
            'Table.TransformColumnTypes(Source, {{"A", type text}}, [Culture="en-US"])',
            'let Int64.Type = Other in Table.TransformColumnTypes(Source, {{"A", Int64.Type}})',
        ):
            with self.subTest(expression=expression):
                self.assertIsNone(self.infer(expression))
