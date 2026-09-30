import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project
from pbi_usage_analyzer.model import EvidenceType, ObjectRef, ObjectType, Status
from pbi_usage_analyzer.parsers.dax import dax_dependencies
from pbi_usage_analyzer.parsers.dax_lexer import mask_dax, mask_dax_literals
from pbi_usage_analyzer.util import norm_key


def refs(table, *names, kind=ObjectType.COLUMN):
    return {norm_key(table, name): ObjectRef(kind, table, name) for name in names}


class DaxLexerTests(unittest.TestCase):
    def test_masking_preserves_offsets_lines_and_identifiers(self):
        text = "'A // b'[C -- d] + \"x\"\"[E]\"\"\" // [F]\n/* [G]\n */ [H]"
        masked = mask_dax_literals(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count('\n'), text.count('\n'))
        self.assertIn("'A // b'[C -- d]", masked)
        self.assertIn('[H]', masked)
        for fake in ('[E]', '[F]', '[G]'):
            self.assertNotIn(fake, masked)

    def test_unterminated_literals_are_reported(self):
        for text, kind in (('[A] & "open [B]', 'string'), ('[A] /* open [B]', 'block comment')):
            with self.subTest(kind=kind):
                strict = mask_dax(text)
                self.assertEqual(strict.unterminated, kind)
                self.assertEqual(strict.unterminated_offset, text.index(kind == 'string' and '"' or '/*'))
                self.assertNotIn('[B]', strict.text)
                kept = mask_dax(text, keep_unterminated=True)
                self.assertIn('[B]', kept.text)
        self.assertIsNone(mask_dax('[A] // trailing').unterminated)


class DaxDependencyMaskingTests(unittest.TestCase):
    owner = ObjectRef(ObjectType.MEASURE, 'Sales', 'Owner')

    def targets(self, expression, columns=None, measures=None):
        found = dax_dependencies(self.owner, expression, columns or {}, measures or {})
        return {e.target.name for e in found}

    def test_strings_and_comments_do_not_create_dependencies(self):
        columns = refs('Sales', 'Real', 'Fake')
        measures = refs('Sales', 'Margin', 'Ghost', kind=ObjectType.MEASURE)
        cases = [
            "SUM('Sales'[Real]) & \"'Sales'[Fake] [Ghost]\"",
            "SUM('Sales'[Real]) // 'Sales'[Fake] [Ghost]",
            "SUM('Sales'[Real]) -- Sales[Fake] [Ghost]",
            "SUM('Sales'[Real]) /* 'Sales'[Fake]\n [Ghost] */",
            "SUM('Sales'[Real]) & \"say \"\"[Ghost]\"\" 'Sales'[Fake]\"",
        ]
        for expression in cases:
            with self.subTest(expression=expression):
                self.assertEqual(self.targets(expression + '\n + [Margin]', columns, measures), {'Real', 'Margin'})

    def test_identifiers_containing_comment_or_quote_text_still_resolve(self):
        columns = refs('Sales // 2024', 'Amount -- net')
        columns.update(refs("Bob's", 'Value'))
        measures = refs('Sales', 'Profit "net" /* x */', kind=ObjectType.MEASURE)
        expression = "SUM('Sales // 2024'[Amount -- net]) + [Profit \"net\" /* x */] + SUM('Bob''s'[Value])"
        self.assertEqual(self.targets(expression, columns, measures),
                         {'Amount -- net', 'Profit "net" /* x */', 'Value'})

    def test_escaped_closing_brackets_resolve(self):
        columns = refs('Sales', 'Size [cm]')
        measures = refs('Sales', 'Rate [%]', kind=ObjectType.MEASURE)
        expression = "SUM('Sales'[Size [cm]]]) * [Rate [%]]]"
        self.assertEqual(self.targets(expression, columns, measures), {'Size [cm]', 'Rate [%]'})

    def test_unterminated_literal_keeps_later_evidence(self):
        columns = refs('Sales', 'Real', 'Later')
        for expression in ("SUM('Sales'[Real]) & \"open 'Sales'[Later]",
                           "SUM('Sales'[Real]) /* open 'Sales'[Later]"):
            with self.subTest(expression=expression):
                self.assertEqual(self.targets(expression, columns), {'Real', 'Later'})


class DaxLexicalScenarioTests(unittest.TestCase):
    def setUp(self):
        suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        self.result = analyze_project(suite / '25_dax_lexical_scope')
        self.statuses = {f.ref.label: f.status for f in self.result.findings}

    def test_commented_and_quoted_references_do_not_protect_objects(self):
        self.assertEqual(self.statuses['Sales[Amount]'], Status.USED)
        self.assertEqual(self.statuses['Sales[Cost]'], Status.USED)
        self.assertEqual(self.statuses['Sales[Discount]'], Status.USED)
        self.assertEqual(self.statuses['Sales[Legacy]'], Status.LIKELY_UNUSED)
        self.assertEqual(self.statuses['Sales[Old Margin]'], Status.LIKELY_UNUSED)
        self.assertEqual(self.statuses['Sales[Commented Only]'], Status.LIKELY_UNUSED)

    def test_malformed_expression_keeps_evidence_and_reports_diagnostic(self):
        self.assertEqual(self.statuses['Sales[Draft Source]'], Status.MANUAL_REVIEW)
        diagnostics = [d for d in self.result.diagnostics if d.code == 'DAX_UNTERMINATED_LITERAL']
        self.assertEqual([d.object_ref.label for d in diagnostics], ['Sales[Draft]'])
        self.assertTrue(diagnostics[0].source_file.endswith('Sales.tmdl'))

    def test_transitive_dependency_survives_masking(self):
        edges = {(e.source.label, e.target.label) for e in self.result.graph.evidence
                 if e.evidence_type == EvidenceType.DAX_DEPENDENCY}
        self.assertIn(('Sales[Margin]', 'Sales[Net]'), edges)
        self.assertIn(('Sales[Net]', 'Sales[Discount]'), edges)
        self.assertNotIn(('Sales[Margin]', 'Sales[Old Margin]'), edges)


if __name__ == '__main__':
    unittest.main()
