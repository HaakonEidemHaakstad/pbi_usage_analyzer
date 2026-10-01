from __future__ import annotations

from collections import deque

from ..model import DependencyGraph, EvidenceType, Finding, ObjectRef, ObjectType, Status

HIGH_CONFIDENCE_USE = {
    EvidenceType.DIRECT_REPORT_USE,
    EvidenceType.DAX_DEPENDENCY,
    EvidenceType.RELATIONSHIP_DEPENDENCY,
    EvidenceType.HIERARCHY_DEPENDENCY,
    EvidenceType.SORT_DEPENDENCY,
    EvidenceType.GROUP_BY_DEPENDENCY,
    EvidenceType.FIELD_PARAMETER_DEPENDENCY,
    EvidenceType.RLS_DEPENDENCY,
    EvidenceType.CALCULATION_GROUP_DEPENDENCY,
    EvidenceType.FALLBACK_MATCH,
}
MANUAL_REVIEW = {
    EvidenceType.RAW_REPORT_REFERENCE,
    EvidenceType.POWERQUERY_QUERY_DEPENDENCY,
    EvidenceType.POWERQUERY_COLUMN_DEPENDENCY,
    EvidenceType.INCOMPLETE_SOURCE,
    EvidenceType.DAX_UNQUALIFIED_COLUMN_REFERENCE,
}


def _root_used(graph: DependencyGraph) -> set[ObjectRef]:
    roots: set[ObjectRef] = set()
    for ev in graph.evidence:
        if ev.evidence_type in {EvidenceType.DIRECT_REPORT_USE, EvidenceType.RELATIONSHIP_DEPENDENCY, EvidenceType.FIELD_PARAMETER_DEPENDENCY, EvidenceType.RLS_DEPENDENCY}:
            roots.add(ev.target)
    return roots


def propagate_used(graph: DependencyGraph) -> set[ObjectRef]:
    """Follow semantic-model dependency edges from proven roots.

    DAX/hierarchy/sort edges only make the target definitely used when their source is
    already used. Relationship/RLS/report edges are roots themselves.
    """
    used = _root_used(graph)
    queue = deque(used)
    while queue:
        source = queue.popleft()
        for ev in graph.outgoing(source):
            if ev.evidence_type in {
                EvidenceType.DAX_DEPENDENCY,
                EvidenceType.HIERARCHY_DEPENDENCY,
                EvidenceType.SORT_DEPENDENCY,
                EvidenceType.GROUP_BY_DEPENDENCY,
                EvidenceType.FIELD_PARAMETER_DEPENDENCY,
                EvidenceType.RLS_DEPENDENCY,
                EvidenceType.CALCULATION_GROUP_DEPENDENCY,
            } and ev.target not in used:
                used.add(ev.target)
                queue.append(ev.target)
    return used


def classify(graph: DependencyGraph) -> list[Finding]:
    used = propagate_used(graph)
    findings: list[Finding] = []
    for ref, obj in sorted(graph.objects.items(), key=lambda x: (x[0].object_type.value, x[0].table.casefold(), x[0].name.casefold())):
        if ref.object_type not in {ObjectType.COLUMN, ObjectType.MEASURE}:
            continue
        incoming = graph.incoming(ref)
        reasons = []
        types = []
        for ev in incoming:
            if ev.reason not in reasons:
                reasons.append(ev.reason)
            if ev.evidence_type.value not in types:
                types.append(ev.evidence_type.value)

        if any(ev.evidence_type == EvidenceType.INTERNAL_OBJECT for ev in incoming):
            status = Status.INTERNAL
        elif ref in used:
            status = Status.USED
        elif any(ev.evidence_type in MANUAL_REVIEW for ev in incoming):
            status = Status.MANUAL_REVIEW
        elif any(ev.evidence_type in {EvidenceType.DAX_DEPENDENCY, EvidenceType.HIERARCHY_DEPENDENCY, EvidenceType.SORT_DEPENDENCY,
                                       EvidenceType.GROUP_BY_DEPENDENCY, EvidenceType.CALCULATION_GROUP_DEPENDENCY}
                 for ev in incoming):
            # A model dependency exists, but its owner is not proven to be active.
            status = Status.MANUAL_REVIEW
        else:
            status = Status.LIKELY_UNUSED
        findings.append(Finding(ref, status, reasons, types))
    return findings
