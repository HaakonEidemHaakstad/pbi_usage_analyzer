import unittest
from pbi_usage_analyzer.parsers.powerquery import _find_query_refs, _table_refs


class PowerQueryTests(unittest.TestCase):
    def setUp(self):
        self.tables = {
            "hovedbok": "Hovedbok",
            "hovedbok 2024": "Hovedbok 2024",
            "firma": "Firma",
            "dates": "Dates",
            "date": "Date",
        }

    def test_append_reference(self):
        src = '''
        let
            Source = Excel.Workbook(Web.Contents("url"), null, true),
            #"Tilføyet spørring" = Table.Combine({Source, #"Hovedbok 2024"})
        in
            #"Tilføyet spørring"
        '''
        refs = _find_query_refs(src, "Hovedbok", self.tables)
        self.assertIn("Hovedbok 2024", refs)

    def test_strings_and_comments_do_not_create_dependency(self):
        src = '''
        let
            Source = "Firma",
            // Dates should not count
            Note = "Hovedbok 2024"
        in
            Source
        '''
        refs = _find_query_refs(src, "Hovedbok", self.tables)
        self.assertEqual(refs, set())

    def test_local_step_does_not_create_dependency(self):
        src = '''
        let
            Firma = 1,
            Result = Firma + 1
        in
            Result
        '''
        refs = _find_query_refs(src, "Hovedbok", self.tables)
        self.assertNotIn("Firma", refs)

    def test_type_keywords_and_library_names_are_not_queries(self):
        # M is case-sensitive: `type date` and `Date.From` are not the query `Date`.
        src = '''
        let
            Kilde = Csv.Document(File.Contents("x.csv")),
            Typed = Table.TransformColumnTypes(Kilde, {{"ReturnDate", type date}}),
            Added = Table.AddColumn(Typed, "Y", each Date.Year([ReturnDate]) + #date(2024, 1, 1))
        in
            Added
        '''
        self.assertEqual(_find_query_refs(src, "Returns Data", self.tables), set())

    def test_exact_case_simple_reference_still_counts(self):
        src = '''
        let
            Source = Table.NestedJoin(Firma, {"Id"}, Date, {"Id"}, "D", JoinKind.LeftOuter)
        in
            Source
        '''
        self.assertEqual(_find_query_refs(src, "Hovedbok", self.tables), {"Firma", "Date"})


    def test_quoted_identifier_in_comment_is_not_a_reference(self):
        src = 'let\n    // was #"Hovedbok 2024"\n    S = Firma /* #"Dates" */\nin\n    S'
        self.assertEqual(_find_query_refs(src, "Hovedbok", self.tables), {"Firma"})


class SharedQueryReferenceTests(unittest.TestCase):
    """Load-disabled (shared expression) queries between partitions and loaded tables."""

    tables = {"raw": "Raw", "archive": "Archive", "out": "Out"}

    def refs(self, source, shared):
        return _table_refs(source, "Out", self.tables, shared)

    def test_paths_through_shared_queries(self):
        shared = {"Staging": 'Table.SelectColumns(Raw, {"A"})', "Deep": '#"Staging"'}
        self.assertEqual(self.refs('CustomFunction(#"Deep", Archive)', shared),
                         {"Raw": ("Deep", "Staging"), "Archive": ()})

    def test_unreached_and_commented_shared_queries_do_not_count(self):
        shared = {"Orphan": "Raw", "Noted": "Archive"}
        self.assertEqual(self.refs('let S = X // #"Noted"\nin S', shared), {})

    def test_cycles_terminate(self):
        shared = {"A": '#"B"', "B": 'Table.Combine({#"A", Raw})'}
        self.assertEqual(self.refs('#"A"', shared), {"Raw": ("A", "B")})

    def test_owner_and_strings_are_excluded(self):
        shared = {"Loop": 'Table.Combine({Out, "Raw"})'}
        self.assertEqual(self.refs('#"Loop"', shared), {})

    def test_local_step_named_like_shared_query_is_not_a_reference(self):
        shared = {"Staging": "Raw"}
        # Step names are recognized at line starts, as Power BI writes them.
        self.assertEqual(self.refs('let\n    Staging = Archive\nin\n    Staging', shared), {"Archive": ()})


if __name__ == "__main__":
    unittest.main()
