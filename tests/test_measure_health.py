import tempfile
import unittest
from pathlib import Path

from pbi_usage_analyzer.health.rules import missing_measure_descriptions
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.parsers.tmdl import parse_table_file


class MeasureHealthTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Measures.tmdl'
            path.write_text(text, encoding='utf-8')
            return parse_table_file(path)[0]

    def test_descriptions_and_blank_descriptions_are_distinguished(self):
        objects = self.parse("table Sales\n    /// Revenue in local currency.\n    /// Excludes tax.\n    measure Revenue = 1\n    measure Missing = 2\n    ///   \n    measure Blank = 3\n")
        self.assertEqual(objects[0].description, 'Revenue in local currency.\nExcludes tax.')
        findings = missing_measure_descriptions(objects)
        self.assertEqual([f.scope for f in findings], ['Sales[Missing]', 'Sales[Blank]'])
        self.assertEqual([f.line for f in findings], [5, 7])
        self.assertTrue(all(f.severity == HealthSeverity.INFO for f in findings))

    def test_table_comments_and_dax_strings_do_not_document_measure(self):
        objects = self.parse('/// Table description\ntable Sales\n    // Ordinary comment\n    measure Missing = "/// not documentation"\n')
        self.assertEqual(len(missing_measure_descriptions(objects)), 1)
        self.assertEqual(objects[0].expression, '"/// not documentation"')

    def test_internal_and_uncertain_descriptions_are_skipped(self):
        for name in ('LocalDateTable_test', 'DateTableTemplate_test'):
            self.assertEqual(missing_measure_descriptions(self.parse(f'table {name}\n    measure Helper = 1\n')), [])
        objects = self.parse('table Sales\n    measure Legacy = 1\n        description: Some documentation\n')
        self.assertIsNone(objects[0].description)
        self.assertEqual(missing_measure_descriptions(objects), [])

    def test_description_attaches_only_to_adjacent_measure(self):
        objects = self.parse('table Sales\n    /// Not adjacent\n\n    measure Missing = 1\n    /// Column documentation\n    column Value\n        sourceColumn: Value\n    measure AlsoMissing = 2\n')
        self.assertEqual([f.scope for f in missing_measure_descriptions(objects)], ['Sales[Missing]', 'Sales[AlsoMissing]'])
