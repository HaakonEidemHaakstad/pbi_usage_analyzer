import copy
import unittest
from pathlib import Path

from pbi_usage_analyzer import analyze_project, analysis_to_dict
from tools.validation.export_consistency import consistency_errors


class ExportConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = Path(__file__).resolve().parents[1] / 'tools/validation/validation_suite'
        cls.document = analysis_to_dict(analyze_project(cls.suite / '20_measure_descriptions'))

    def test_all_scenarios_and_filter_variants(self):
        for folder in sorted(self.suite.iterdir()):
            if not folder.is_dir():
                continue
            for filters in ({}, {'health_severities': []}, {'health_severities': ['info']}):
                with self.subTest(folder=folder.name, filters=filters):
                    self.assertEqual(consistency_errors(analysis_to_dict(analyze_project(folder, **filters))), [])

    def test_inconsistent_counts_and_filters(self):
        for path, value in [
            (('summary', 'measures', 'used'), 100),
            (('summary', 'measures', 'business_total'), 100),
            (('summary', 'query_dependencies'), 5),
            (('health_filter_scope', 'selected_findings'), 0),
            (('health_filter_scope', 'total_findings'), 0),
            (('health_filter_scope', 'rule_ids'), []),
            (('health_filter_scope', 'severities'), ['warning']),
        ]:
            with self.subTest(path=path):
                document = copy.deepcopy(self.document)
                target = document
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                self.assertTrue(consistency_errors(document))

    def test_duplicate_missing_and_dangling_objects(self):
        for mutate in (
            lambda d: d['objects'].append(d['objects'][0]),
            lambda d: d['cleanup_findings'].append(d['cleanup_findings'][0]),
            lambda d: d['cleanup_findings'].pop(),
            lambda d: d['objects'].clear(),
        ):
            document = copy.deepcopy(self.document)
            mutate(document)
            self.assertTrue(consistency_errors(document))

    def test_evidence_endpoints_and_external_owners(self):
        document = analysis_to_dict(analyze_project(self.suite / '03_relationship_only'))
        evidence = document['dependency_evidence'][0]
        evidence['source'] = {'object_type':'Table','table':'Missing','name':''}
        self.assertTrue(consistency_errors(document))
        evidence['source'] = {'object_type':'ReportField','table':'Report','name':'Visual'}
        self.assertEqual(consistency_errors(document), [])
        evidence['source'] = {'object_type':'Table','table':'Special:roles.tmdl','name':''}
        evidence['evidence_type'] = 'RLS_DEPENDENCY'
        self.assertEqual(consistency_errors(document), [])
        evidence['target'] = {'object_type':'Column','table':'Missing','name':'Key'}
        self.assertTrue(consistency_errors(document))
