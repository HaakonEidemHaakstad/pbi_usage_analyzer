import shutil
import tempfile
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.model import EvidenceType, Status
from tools.validation.export_consistency import consistency_errors


class SpecialDaxTests(unittest.TestCase):
    def setUp(self):
        self.suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'

    def test_special_evidence_types_targets_and_source_locations(self):
        cases = [
            ('21_field_parameter', EvidenceType.FIELD_PARAMETER_DEPENDENCY, 'Selector.tmdl'),
            ('22_rls', EvidenceType.RLS_DEPENDENCY, 'North.tmdl'),
            ('23_calculation_item', EvidenceType.CALCULATION_GROUP_DEPENDENCY, 'Calculations.tmdl'),
        ]
        for name, kind, filename in cases:
            with self.subTest(name=name):
                result = analyze_project(self.suite / name)
                evidence = [e for e in result.graph.evidence if e.evidence_type == kind]
                expected = {'Sales[Region]'} if name == '22_rls' else {'Sales[Region]', 'Sales[Revenue]'}
                self.assertEqual({e.target.label for e in evidence}, expected)
                self.assertTrue(all(Path(e.source_file).name == filename for e in evidence))
                self.assertTrue(all(e.source.table == f'Special:{filename}' for e in evidence))
                self.assertEqual(result.summary.query_dependencies, 0)
                self.assertEqual(consistency_errors(analysis_to_dict(result)), [])

    def test_role_removal_removes_role_only_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'project'
            shutil.copytree(self.suite / '22_rls', project)
            before = analyze_project(project)
            role = before.project.model_folder / 'definition/roles/North.tmdl'
            role.unlink()
            after = analyze_project(project)
            statuses = lambda result: {f.ref.label: f.status for f in result.findings}
            self.assertEqual(statuses(before)['Sales[Region]'], Status.USED)
            self.assertEqual(statuses(after)['Sales[Region]'], Status.LIKELY_UNUSED)
            self.assertEqual(statuses(before)['Sales[Unrelated]'], Status.LIKELY_UNUSED)
            self.assertEqual(statuses(after)['Sales[Unrelated]'], Status.LIKELY_UNUSED)

    def test_parameter_propagation_and_calculation_activation_boundary(self):
        parameter = analyze_project(self.suite / '21_field_parameter')
        calculation = analyze_project(self.suite / '23_calculation_item')
        statuses = lambda result: {f.ref.label: f.status for f in result.findings}
        self.assertEqual(statuses(parameter)['Sales[Revenue]'], Status.USED)
        self.assertEqual(statuses(parameter)['Sales[Amount]'], Status.USED)
        self.assertEqual(statuses(calculation)['Sales[Revenue]'], Status.MANUAL_REVIEW)
        self.assertEqual(statuses(calculation)['Sales[Amount]'], Status.MANUAL_REVIEW)
        self.assertEqual(statuses(calculation)['Sales[Region]'], Status.MANUAL_REVIEW)

    def test_extraction_ignores_comments_strings_and_annotations(self):
        from pbi_usage_analyzer.parsers.special_dax import extract_special_expressions
        text = '''/*
role Fake
    tablePermission Sales = 'Sales'[Unrelated] = 1
*/
table Calculations
    annotation Note = "calculationGroup NAMEOF('Sales'[Unrelated])"
    calculationGroup
        annotation Extra =
            calculationItem Fake = 'Sales'[Unrelated]
        calculationItem Real = CALCULATE('Sales'[Revenue], 'Sales'[Region] = "'Sales'[Unrelated]") // 'Sales'[Unrelated]
role North
    annotation Extra = 'Sales'[Unrelated]
    tablePermission Sales = 'Sales'[Region] = "North" /* 'Sales'[Unrelated] */
'''
        expressions = extract_special_expressions(text)
        self.assertEqual([e.kind for e in expressions], [EvidenceType.CALCULATION_GROUP_DEPENDENCY, EvidenceType.RLS_DEPENDENCY])
        self.assertTrue(all('Unrelated' not in e.expression for e in expressions))

    def test_nameof_promotes_only_arguments_and_skips_m_partitions(self):
        from pbi_usage_analyzer.parsers.special_dax import extract_special_expressions
        text = '''table Selector
    partition Selector = calculated
        source = { ("NAMEOF('Sales'[Unrelated])", NAMEOF ('Sales'[Region]), 'Sales'[Amount]) }
    partition Import = m
        source = NAMEOF('Sales'[Unrelated])
    measure Ordinary = SUM('Sales'[Amount])
    annotation Note = NAMEOF('Sales'[Unrelated])
'''
        expressions = extract_special_expressions(text)
        self.assertEqual(len(expressions), 1)
        self.assertEqual(expressions[0].expression.strip(), "'Sales'[Region]")
        self.assertEqual(expressions[0].kind, EvidenceType.FIELD_PARAMETER_DEPENDENCY)

    def test_fenced_and_multiline_special_expressions(self):
        from pbi_usage_analyzer.parsers.special_dax import extract_special_expressions
        expressions = extract_special_expressions('''role North
    tablePermission Sales =
        'Sales'[Region] = "North"
table Calculations
    calculationGroup
        calculationItem Example = ```
            'Sales'[Revenue] + 1
            ```
            formatStringDefinition = "'Sales'[Unrelated]"
''')
        self.assertEqual(len(expressions), 3)
        self.assertIn("'Sales'[Region]", expressions[0].expression)
        self.assertIn("'Sales'[Revenue]", expressions[1].expression)
        self.assertNotIn('Unrelated', expressions[1].expression)

    def test_inline_expression_continuation_retains_dependencies(self):
        from pbi_usage_analyzer.parsers.special_dax import extract_special_expressions
        expressions = extract_special_expressions('''table Calculations
    calculationGroup
        calculationItem Example = 'Sales'[Revenue]
            + SUM('Sales'[Amount])
            formatStringDefinition = "0"
''')
        self.assertEqual(len(expressions), 2)
        self.assertIn("'Sales'[Amount]", expressions[0].expression)
        self.assertNotIn('formatStringDefinition', expressions[0].expression)

    def test_calculation_format_expression_keeps_real_references(self):
        from pbi_usage_analyzer.parsers.special_dax import extract_special_expressions
        expressions = extract_special_expressions("""table Calculations
    calculationGroup
        calculationItem Example = SELECTEDMEASURE()
            formatStringDefinition = IF('Sales'[Revenue] > 0, "0", "#")
""")
        self.assertEqual(len(expressions), 2)
        self.assertIn("'Sales'[Revenue]", expressions[1].expression)
        self.assertEqual(expressions[1].kind, EvidenceType.CALCULATION_GROUP_DEPENDENCY)
