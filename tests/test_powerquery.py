import unittest
from pbi_usage_analyzer.parsers.powerquery import _find_query_refs


class PowerQueryTests(unittest.TestCase):
    def setUp(self):
        self.tables = {
            "hovedbok": "Hovedbok",
            "hovedbok 2024": "Hovedbok 2024",
            "firma": "Firma",
            "dates": "Dates",
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


if __name__ == "__main__":
    unittest.main()
