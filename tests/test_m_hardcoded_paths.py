import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.health.model import HealthSeverity
from pbi_usage_analyzer.parsers.m_queries import MQueryKind, collect_m_queries, m_string_literals
from tools.validation.export_consistency import consistency_errors

SCENARIO = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite/34_m_hardcoded_paths'
MODEL = SCENARIO / '34_m_hardcoded_paths.SemanticModel'


class MQueryCollectionTests(unittest.TestCase):
    def test_partitions_expressions_and_parameters(self):
        queries = {q.name: q for q in collect_m_queries(MODEL)}
        self.assertEqual(set(queries), {'Sales', 'Budget', 'DataFolder', 'Sales Archive'})
        self.assertEqual(queries['Sales'].kind, MQueryKind.PARTITION)
        self.assertEqual(queries['DataFolder'].kind, MQueryKind.PARAMETER)
        self.assertEqual(queries['Sales Archive'].kind, MQueryKind.EXPRESSION)
        self.assertTrue(queries['Sales Archive'].source.startswith('let'))
        self.assertNotIn('lineageTag', queries['Sales Archive'].source)
        self.assertEqual(queries['Sales Archive'].line, 5)   # first body line, after CRLF header
        self.assertEqual(queries['Sales'].line, 7)


class MStringLiteralTests(unittest.TestCase):
    def test_comments_and_quoted_identifiers_are_skipped(self):
        source = ('let\n  // "C:\\in comment"\n  /* "D:\\block" */ #"E:\\id" = "a ""q"" b",\n'
                  '  Y = "F:\\x"\nin Y')
        self.assertEqual([(value, line) for value, line in m_string_literals(source)],
                         [('a "q" b', 3), ('F:\\x', 4)])


class HardcodedPathRuleTests(unittest.TestCase):
    def setUp(self):
        self.result = analyze_project(SCENARIO)
        self.findings = {f.scope: f for f in self.result.health_findings if f.rule_id == 'POWERQUERY_HARDCODED_PATH'}

    def test_findings(self):
        self.assertEqual(set(self.findings), {'Sales', 'Sales Archive'})
        sales = self.findings['Sales']
        self.assertEqual(sales.severity, HealthSeverity.WARNING)
        self.assertEqual(sales.line, 9)
        self.assertTrue(sales.source_file.endswith('Sales.tmdl'))
        self.assertTrue(any('C:\\Users\\ann\\OneDrive\\Data\\sales.csv' in e and 'user profile' in e
                            for e in sales.evidence))
        self.assertFalse(any('Archive' in e for e in sales.evidence))      # comment only
        archive = self.findings['Sales Archive']
        self.assertEqual(archive.line, 6)
        self.assertTrue(archive.source_file.endswith('expressions.tmdl'))
        self.assertTrue(any('\\\\fileserver\\finance\\sales' in e for e in archive.evidence))
        self.assertFalse(any('not a path' in e for e in archive.evidence))  # quoted identifier
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])


if __name__ == '__main__':
    unittest.main()
