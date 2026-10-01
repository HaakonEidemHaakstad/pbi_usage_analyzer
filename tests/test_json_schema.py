import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from pbi_usage_analyzer import analyze_project, analysis_to_dict


class JsonSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        schema = json.loads((cls.root / 'schemas/analysis-result-v1.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)
        cls.suite = cls.root / 'tools/validation/validation_suite'

    def test_all_scenarios_and_filter_variants(self):
        for folder in sorted(self.suite.iterdir()):
            if not folder.is_dir():
                continue
            for options in ({}, {'health_severities': []}, {'health_severities': ['warning']}):
                with self.subTest(scenario=folder.name, options=options):
                    result = analyze_project(folder, **options)
                    document = analysis_to_dict(result)
                    self.validator.validate(document)
                    for kind in ('columns', 'measures'):
                        counts = document['summary'][kind]
                        self.assertEqual(counts['business_total'], sum(counts[k] for k in ('used','manual_review','likely_unused')))
                    self.assertEqual(document['health_filter_scope']['selected_findings'], len(document['health_findings']))

    def test_malformed_documents_are_rejected(self):
        original = analysis_to_dict(analyze_project(self.suite / '20_measure_descriptions'))
        mutations = [
            (('schema_version',), 2),
            (('objects', 0, 'hidden'), 'false'),
            (('objects', 0, 'source_line'), 0),
            (('summary', 'columns', 'used'), -1),
            (('cleanup_findings', 0, 'status_id'), 'UNKNOWN'),
            (('cleanup_findings', 0, 'status'), 'Used'),
            (('health_findings', 0, 'severity'), 'critical'),
            (('health_filter_scope', 'rule_ids'), ['MEASURE_DESCRIPTION_MISSING'] * 2),
            (('health_filter_scope', 'severities'), 'info'),
            (('extra_field',), True),
        ]
        for path, value in mutations:
            with self.subTest(path=path):
                document = copy.deepcopy(original)
                target = document
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertFalse(self.validator.is_valid(document))
        del original['project']
        self.assertFalse(self.validator.is_valid(original))

    def test_diagnostic_locations_and_future_rule_ids(self):
        document = analysis_to_dict(analyze_project(self.suite / '20_measure_descriptions'))
        document['diagnostics'] = [{'code':'PBIR_READ_FAILED','severity':'warning','message':'Invalid JSON',
                                    'source_file':'report.json','line':3,'column':1,'object_ref':None}]
        document['health_findings'][0]['rule_id'] = 'FUTURE_DOCUMENTATION_RULE'
        self.validator.validate(document)
        document['diagnostics'][0]['column'] = 0
        self.assertFalse(self.validator.is_valid(document))
