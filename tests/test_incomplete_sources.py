import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from pbi_usage_analyzer.model import EvidenceType, Status
from pbi_usage_analyzer.parsers import tmdl
from pbi_usage_analyzer.util import read_source_text
from tools.validation.export_consistency import consistency_errors

SUITE = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'


def statuses(result):
    return {f.ref.label: f.status for f in result.findings}


class ReadSourceTextTests(unittest.TestCase):
    def test_bom_and_invalid_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.tmdl'
            path.write_bytes(b'\xef\xbb\xbftable A')
            self.assertEqual(read_source_text(path), ('table A', False))
            path.write_bytes(b'table B\xf8')
            self.assertEqual(read_source_text(path), ('table B�', True))


class IncompleteSourceScenarioTests(unittest.TestCase):
    def setUp(self):
        self.result = analyze_project(SUITE / '27_incomplete_sources')

    def test_diagnostics_and_evidence(self):
        codes = sorted(d.code for d in self.result.diagnostics)
        self.assertEqual(codes, ['PBIR_READ_FAILED', 'TMDL_DECODE_REPLACED'])
        by_target = {}
        for ev in self.result.graph.evidence:
            by_target.setdefault(ev.target.label, set()).add(ev.evidence_type)
        self.assertIn(EvidenceType.INCOMPLETE_SOURCE, by_target['Other[Bel�p]'])
        self.assertEqual(by_target['Sales[Revenue]'], {EvidenceType.RAW_REPORT_REFERENCE})
        self.assertEqual(by_target['Sales[Region]'], {EvidenceType.RAW_REPORT_REFERENCE})
        self.assertNotIn('Other[Plain]', by_target)
        self.assertEqual(consistency_errors(analysis_to_dict(self.result)), [])

    def test_damage_does_not_protect_unrelated_objects(self):
        found = statuses(self.result)
        self.assertEqual(found['Sales[Unused]'], Status.LIKELY_UNUSED)
        self.assertEqual(found['Other[Plain]'], Status.LIKELY_UNUSED)


class ParseFailureTests(unittest.TestCase):
    def test_failed_table_file_references_become_manual_review(self):
        original = tmdl.parse_table_file

        def failing(path):
            if path.name == 'Extra.tmdl':
                raise ValueError('synthetic parser failure')
            return original(path)

        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'project'
            shutil.copytree(SUITE / '01_direct_visual', project)
            extra = next(project.glob('*.SemanticModel')) / 'definition/tables/Extra.tmdl'
            extra.write_text("table Extra\n    measure M = SUM('Sales'[Unused])\n", encoding='utf-8')
            with mock.patch.object(tmdl, 'parse_table_file', failing):
                result = analyze_project(project)
        self.assertIn('TMDL_PARSE_FAILED', [d.code for d in result.diagnostics])
        found = statuses(result)
        self.assertEqual(found['Sales[Unused]'], Status.MANUAL_REVIEW)
        self.assertEqual(found['Sales[Amount]'], Status.USED)
        kinds = {ev.evidence_type for ev in result.graph.evidence if ev.target.label == 'Sales[Unused]'}
        self.assertEqual(kinds, {EvidenceType.INCOMPLETE_SOURCE})

    def test_invalid_relationship_file_does_not_abort(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'project'
            shutil.copytree(SUITE / '03_relationship_only', project)
            path = next(project.glob('*.SemanticModel')) / 'definition/relationships.tmdl'
            path.write_bytes(path.read_bytes() + b'\n// \xff\n')
            result = analyze_project(project)
        self.assertIn('TMDL_DECODE_REPLACED', [d.code for d in result.diagnostics])


if __name__ == '__main__':
    unittest.main()
