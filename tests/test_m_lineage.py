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
        for source in ('Unknown', 'Table.SelectColumns(Unknown, {"A"})', 'Table.AddColumn(Source, "A", each CustomFunction(_))', 'Table.Combine({Source}, {"A"})', 'Table.RemoveColumns(Source, {"A"}, MissingField.UseNull)', 'Source trailing', '"Source"'):
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

    def test_filter_protects_predicate_columns_after_projection(self):
        demand = self.infer('Table.SelectColumns(Table.SelectRows(Source, each [Active] = true and [Amount] > 0), {"Key"})')['Source']
        self.assertTrue(all(demand.accepts(c) for c in ('Active', 'Amount', 'Key')))
        self.assertFalse(demand.accepts('Unrelated'))

    def test_computed_column_maps_to_input_reads(self):
        demand = self.infer('Table.SelectColumns(Table.AddColumn(Source, "Total", each [Price] * [Quantity], type number), {"Total"})')['Source']
        self.assertTrue(demand.accepts('Price'))
        self.assertTrue(demand.accepts('Quantity'))
        self.assertFalse(demand.accepts('Total'))
        self.assertFalse(demand.accepts('Unrelated'))

    def test_chained_computed_columns_and_conditionals(self):
        demand = self.infer('let A = Table.AddColumn(Source, "Gross", each [Net] + [Tax]), B = Table.AddColumn(A, "Final", each if [Active] then [Gross] else 0) in Table.SelectColumns(B, {"Final"})')['Source']
        self.assertTrue(all(demand.accepts(c) for c in ('Net', 'Tax', 'Active')))
        self.assertFalse(demand.accepts('Gross'))
        self.assertFalse(demand.accepts('Final'))

    def test_row_strings_comments_and_quoted_fields(self):
        demand = self.infer('Table.SelectColumns(Table.SelectRows(Source, each [#"Års data"] <> "[Fake]" /* [AlsoFake] */), {})')['Source']
        self.assertTrue(demand.accepts('Års data'))
        self.assertFalse(demand.accepts('Fake'))
        self.assertFalse(demand.accepts('AlsoFake'))

    def test_unsupported_row_expressions_remain_unknown(self):
        for row in ('CustomFunction([A])', 'Record.Field(_, "A")', '[A][B]',
                    '[A]?', 'OtherQuery', '(x) => x[A]', '_',
                    'let X = [A] in X', '[A] +', '[A] [B]', '#"true"',
                    '[A] "and" [B]'):
            with self.subTest(row=row):
                self.assertIsNone(self.infer(f'Table.SelectRows(Source, each {row})'))

    def test_quoted_keywords_and_invalid_numbers_fail_closed(self):
        self.assertIsNone(self.infer('Table.SelectRows(Source, #"each" [A])'))
        self.assertIsNone(self.infer('Table.SelectRows(Source, each [A] > ²)'))
        self.assertIsNone(self.infer('Table.AddColumn(Source, "A", each 1, type #"number")'))

    def test_flat_join_preserves_both_keys_after_projection(self):
        result = self.infer('Table.SelectColumns(Table.Join(Source, {"LeftKey"}, Other, {"RightKey"}, JoinKind.Inner), {"Value"})')
        self.assertTrue(result['Source'].accepts('LeftKey'))
        self.assertTrue(result['Other'].accepts('RightKey'))
        self.assertTrue(result['Other'].accepts('Value'))
        self.assertFalse(result['Source'].accepts('Unused'))
        self.assertFalse(result['Other'].accepts('Unused'))

    def test_nested_join_expansion_resolves_alias_and_source_ownership(self):
        result = self.infer('let Joined = Table.NestedJoin(Source, {"LeftKey"}, Other, {"RightKey"}, "Details", JoinKind.LeftOuter), Alias = Joined, Expanded = Table.ExpandTableColumn(Alias, "Details", {"Name"}, {"CustomerName"}) in Table.SelectColumns(Expanded, {"CustomerName"})')
        self.assertTrue(result['Source'].accepts('LeftKey'))
        self.assertFalse(result['Source'].accepts('Name'))
        self.assertFalse(result['Source'].accepts('CustomerName'))
        self.assertTrue(result['Other'].accepts('RightKey'))
        self.assertTrue(result['Other'].accepts('Name'))
        self.assertFalse(result['Other'].accepts('Unrelated'))

    def test_nested_join_discarded_result_still_protects_keys(self):
        result = self.infer('Table.SelectColumns(Table.NestedJoin(Source, "LeftKey", Other, "RightKey", "Details"), {"Value"})')
        self.assertTrue(result['Other'].accepts('RightKey'))
        self.assertFalse(result['Other'].accepts('Unused'))
        self.assertTrue(result['Source'].accepts('Value'))

    def test_unexpanded_nested_table_retains_all_right_columns(self):
        result = self.infer('Table.NestedJoin(Source, "LeftKey", Other, "RightKey", "Details")')
        self.assertTrue(result['Other'].accepts('AnyColumn'))

    def test_join_unknown_shapes_fall_back(self):
        for source in (
            'Table.Join(Source, {"A"}, Other, {"B", "C"})',
            'Table.Join(Source, {"A"}, Other, {"B"}, DynamicKind)',
            'Table.Join(Source, {"A"}, Other, {"B"}, JoinKind.Inner, 0)',
            'Table.ExpandTableColumn(Source, "Details", {"A"})',
            'Table.ExpandTableColumn(Table.NestedJoin(Source, "A", Other, "B", "Details"), "Wrong", {"Name"})',
            'Table.ExpandTableColumn(Table.NestedJoin(Source, "A", Other, "B", "Details"), "Details", {"Name"}, {"X", "Y"})',
            'let JoinKind.Inner = Other in Table.Join(Source, "A", Other, "B", JoinKind.Inner)',
            'Table.ExpandTableColumn(Table.SelectRows(Table.NestedJoin(Source, "A", Other, "B", "Details"), each [A] > 0), "Details", {"Name"})',
            'let A = B, B = A in Table.ExpandTableColumn(A, "Details", {"Name"})',
            'let Table.NestedJoin = Other in Table.ExpandTableColumn(Table.NestedJoin(Source, "A", Other, "B", "Details"), "Details", {"Name"})',
        ):
            with self.subTest(source=source):
                self.assertIsNone(self.infer(source))

    def test_expanded_schema_and_composite_keys_survive_empty_projection(self):
        result = self.infer('Table.SelectColumns(Table.ExpandTableColumn(Table.NestedJoin(Source, {"A", "B"}, Other, {"C", "D"}, "Details"), "Details", {"Name"}), {})')
        self.assertTrue(all(result['Source'].accepts(c) for c in ('A', 'B')))
        self.assertTrue(all(result['Other'].accepts(c) for c in ('C', 'D', 'Name')))
        self.assertFalse(result['Source'].accepts('Name'))
        self.assertFalse(result['Other'].accepts('Unrelated'))
