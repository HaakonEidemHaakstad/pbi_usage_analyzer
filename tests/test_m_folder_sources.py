import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.health.rules import unfiltered_folder_sources
from pbi_usage_analyzer.parsers.m_queries import MQuery, MQueryKind, folder_listing
from tools.validation.export_consistency import consistency_errors

SCENARIO = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/36_m_folder_sources'


def query(name, source, kind=MQueryKind.PARTITION):
    return MQuery(name, kind, source, f'{name}.tmdl', tuple(range(10, 10 + source.count('\n') + 1)))


def combine(*steps):
    """Folder source reading [Content], with optional extra steps."""
    body = ',\n'.join(('Source = Folder.Files("C:\\x")', *steps,
                       'Read = Table.AddColumn(Source, "D", each Csv.Document([Content]))'))
    return f'let\n{body}\nin Read'


class FolderListingTests(unittest.TestCase):
    def test_no_folder_source(self):
        self.assertIsNone(folder_listing('let S = Csv.Document(File.Contents("C:\\x")) in S'))
        self.assertIsNone(folder_listing('// Folder.Files("C:\\x")\nlet S = "Folder.Files(x)" in S'))

    def test_call_content_and_hidden_filter(self):
        listing = folder_listing(combine('H = Table.SelectRows(Source, each [Attributes]?[Hidden]? <> true)'))
        self.assertEqual(listing.calls, ((2, '"C:\\x"'),))
        self.assertEqual(listing.content_line, 4)
        self.assertEqual((listing.selections, listing.hidden_filter_lines), ((), (3,)))

    def test_file_selections(self):
        cases = {
            'F = Table.SelectRows(Source, each [Extension] = ".csv")': 'Table.SelectRows on file attributes',
            'F = Table.SelectRows(Source, each Text.StartsWith(_[Name], "S"))': 'Table.SelectRows on file attributes',
            'F = Table.SelectRows(Source, each [Attributes][Size] > 0)': 'Table.SelectRows on file attributes',
            'F = Table.SelectRows(Source, MyFilter)': 'Table.SelectRows with an unrecognized predicate',
            'F = Table.Max(Source, "Date modified")': 'Table.Max',
            'F = Table.Distinct(Source, {"Content"})': 'Table.Distinct',
            'F = Source{0}': 'item access {...}',
            'F = #"Source"{[Name = "a.csv"]}': 'item access {...}',
        }
        for step, description in cases.items():
            with self.subTest(step=step):
                self.assertEqual(folder_listing(combine(step)).selections, ((3, description),))

    def test_not_selections(self):
        for step in ('F = Table.SelectRows(Source, each [Amount] > 0)',
                     '// F = Table.SelectRows(Source, each [Name] = "a.csv")',
                     'F = "Table.FirstN(Source, 1)"',
                     'F = Table.TransformColumnTypes(Source, {{"A", type number}})',
                     'F = each {[A]}',
                     'F = Table.Combine({Source})'):
            with self.subTest(step=step):
                self.assertEqual(folder_listing(combine(step)).selections, ())


class FolderRuleUnitTests(unittest.TestCase):
    def test_reported_and_skipped_queries(self):
        queries = (
            query('All', combine()),
            query('Filtered', combine('F = Table.SelectRows(Source, each [Extension] = ".csv")')),
            query('Inventory', 'let Source = Folder.Files("C:\\x") in Table.SelectColumns(Source, {"Name"})'),
            query('Param', 'Folder.Files("C:\\x") meta [IsParameterQuery=true]', MQueryKind.PARAMETER),
            query('Shared', combine('H = Table.SelectRows(Source, each [Attributes]?[Hidden]? <> true)'),
                  MQueryKind.EXPRESSION),
        )
        findings = unfiltered_folder_sources(queries)
        self.assertEqual([(f.scope, f.line) for f in findings], [('All', 11), ('Shared', 11)])
        self.assertEqual(findings[0].evidence[-1], 'No filter on file name, extension, folder path or date')
        self.assertEqual(findings[1].evidence[-1], 'Only the hidden-files filter Power BI adds by default')


class FolderRuleScenarioTests(unittest.TestCase):
    def test_scenario(self):
        result = analyze_project(SCENARIO)
        findings = {f.scope: f for f in result.health_findings if f.rule_id == 'POWERQUERY_FOLDER_UNFILTERED'}
        self.assertEqual(set(findings), {'Sales 2020', 'Targets'})
        sales = findings['Sales 2020']
        self.assertEqual((sales.severity, sales.confidence, sales.line), (HealthSeverity.WARNING, 'medium', 8))
        self.assertTrue(sales.source_file.endswith('Sales 2020.tmdl'))
        self.assertEqual(sales.evidence, (
            'line 8: Folder.Files("C:\\AWCase\\csv\\sales_archive")',
            'line 10: reads file contents ([Content])',
            'Only the hidden-files filter Power BI adds by default'))
        self.assertEqual(findings['Targets'].evidence[-1], 'No filter on file name, extension, folder path or date')
        self.assertEqual(consistency_errors(analysis_to_dict(result)), [])


if __name__ == '__main__':
    unittest.main()
