import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.model import Status
from pbi_usage_analyzer.parsers.tmdl import extract_expression


def block(*lines, indent='\t\t\t'):
    return [indent + line for line in lines]


class ExpressionBoundaryTests(unittest.TestCase):
    def test_colon_text_in_dax_does_not_end_expression(self):
        cases = [
            ('VAR label = "Total: "', 'RETURN SUM(Sales[Amount])'),
            ('// note: legacy', 'SUM(Sales[Amount])'),
            ('-- status: draft', 'SUM(Sales[Amount])'),
            ('/*', 'status: draft', 'owner:', '*/ SUM(Sales[Amount])'),
            ('VAR x = "multi', 'status: draft"', 'RETURN SUM(Sales[Amount])'),
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                expression = extract_expression('', block(*lines) + ['\t\tformatString: 0'], 1)
                self.assertTrue(expression.endswith('SUM(Sales[Amount])'), expression)
                self.assertNotIn('formatString', expression)

    def test_properties_still_end_expression(self):
        properties = [
            'formatString: #,0', 'lineageTag: 1a2b', 'displayFolder: Sales[Folder]',
            'description: Sales[Text]', 'annotation Note = Sales[Other]',
            'changedProperty = Name', 'extendedProperty Parameter =', 'isHidden',
            'formatStringDefinition = "0"', 'dataCategory:Uncategorized',
        ]
        for prop in properties:
            for indent in ('\t\t', '        '):
                with self.subTest(prop=prop, indent=repr(indent)):
                    lines = block('SUM(Sales[Amount])', indent=indent + '\t') + [indent + prop]
                    base = len(indent) - (1 if indent == '\t\t' else 4)
                    self.assertEqual(extract_expression('', lines, base), 'SUM(Sales[Amount])')

    def test_fenced_and_inline_expressions_unchanged(self):
        fenced = block('// note: x', 'SUM(Sales[Amount])', '```') + ['\t\tformatString: 0']
        self.assertEqual(extract_expression('```', fenced, 1), '// note: x\nSUM(Sales[Amount])')
        self.assertEqual(extract_expression('SUM(Sales[A])', block('ignored'), 1), 'SUM(Sales[A])')


class ExpressionBoundaryScenarioTests(unittest.TestCase):
    def test_scenario_statuses(self):
        suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        result = analyze_project(suite / '26_tmdl_expression_boundaries')
        statuses = {f.ref.label: f.status for f in result.findings}
        for label in ('Sales[Amount]', 'Sales[Cost]', 'Sales[Quantity]', 'Sales[Line Total]'):
            self.assertEqual(statuses[label], Status.USED, label)
        self.assertEqual(statuses['Sales[Folder Text]'], Status.LIKELY_UNUSED)


if __name__ == '__main__':
    unittest.main()
