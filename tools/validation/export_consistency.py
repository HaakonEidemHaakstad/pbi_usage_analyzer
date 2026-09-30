"""Cross-field checks for schema-valid version 1 exports; no analyzer imports."""
from collections import Counter


def consistency_errors(document):
    """Return (JSON Pointer, message) pairs. Call only after schema validation."""
    errors = []

    def ref_key(ref):
        return (ref['object_type'], ref['table'], ref['name'])

    objects = set()
    classified = set()
    for index, obj in enumerate(document['objects']):
        key = ref_key(obj['ref'])
        if key in objects:
            errors.append((f'/objects/{index}/ref', 'Duplicate object reference'))
        objects.add(key)
    counts = {'Column': Counter(), 'Measure': Counter()}
    for index, finding in enumerate(document['cleanup_findings']):
        key = ref_key(finding['ref'])
        if key not in objects:
            errors.append((f'/cleanup_findings/{index}/ref', 'Object reference is absent from objects'))
        if key in classified:
            errors.append((f'/cleanup_findings/{index}/ref', 'Duplicate cleanup finding'))
        classified.add(key)
        if key[0] not in counts:
            errors.append((f'/cleanup_findings/{index}/ref', 'Cleanup findings must describe columns or measures'))
        else:
            counts[key[0]][finding['status_id']] += 1
    for index, obj in enumerate(document['objects']):
        key = ref_key(obj['ref'])
        if key[0] in counts and key not in classified:
            errors.append((f'/objects/{index}/ref', 'Column or measure has no cleanup finding'))

    statuses = {'used':'USED', 'manual_review':'MANUAL_REVIEW',
                'likely_unused':'LIKELY_UNUSED', 'internal':'INTERNAL'}
    for kind, section in [('Column', 'columns'), ('Measure', 'measures')]:
        expected = {name: counts[kind][status] for name, status in statuses.items()}
        expected['business_total'] = sum(expected[k] for k in ('used', 'manual_review', 'likely_unused'))
        for name, count in expected.items():
            if document['summary'][section][name] != count:
                errors.append((f'/summary/{section}/{name}', f'Expected {count} from cleanup findings'))

    special_types = {'FIELD_PARAMETER_DEPENDENCY', 'RLS_DEPENDENCY', 'CALCULATION_GROUP_DEPENDENCY'}
    for index, evidence in enumerate(document['dependency_evidence']):
        if ref_key(evidence['target']) not in objects:
            errors.append((f'/dependency_evidence/{index}/target', 'Target is absent from objects'))
        source = evidence['source']
        if source is not None and ref_key(source) not in objects:
            # These are synthetic evidence owners, not semantic-model objects.
            special_owner = (source['object_type'] == 'Table' and source['table'].startswith('Special:')
                             and evidence['evidence_type'] in special_types)
            if source['object_type'] != 'ReportField' and not special_owner:
                errors.append((f'/dependency_evidence/{index}/source', 'Source is absent from objects'))
    queries = sum(e['evidence_type'] == 'POWERQUERY_QUERY_DEPENDENCY' and e['target']['object_type'] == 'Query'
                  for e in document['dependency_evidence'])
    if document['summary']['query_dependencies'] != queries:
        errors.append(('/summary/query_dependencies', f'Expected {queries} query dependency evidence records'))

    scope = document['health_filter_scope']
    health = document['health_findings']
    if scope['selected_findings'] != len(health):
        errors.append(('/health_filter_scope/selected_findings', f'Expected {len(health)} exported health findings'))
    if scope['total_findings'] < scope['selected_findings']:
        errors.append(('/health_filter_scope/total_findings', 'Total cannot be smaller than selected count'))
    if scope['rule_ids'] is None and scope['severities'] is None and scope['total_findings'] != len(health):
        errors.append(('/health_filter_scope/total_findings', 'Unfiltered total must equal exported finding count'))
    for index, finding in enumerate(health):
        if scope['rule_ids'] is not None and finding['rule_id'] not in scope['rule_ids']:
            errors.append((f'/health_findings/{index}/rule_id', 'Finding does not match recorded rule filter'))
        if scope['severities'] is not None and finding['severity'] not in scope['severities']:
            errors.append((f'/health_findings/{index}/severity', 'Finding does not match recorded severity filter'))
    return sorted(errors)
