import unittest
from pbi_usage_analyzer.parsers.powerquery import _find_query_refs


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


if __name__ == "__main__":
    unittest.main()
