"""Why an object has its status, as evidence paths built only from graph evidence.

A path is a tuple of `Evidence`: the first element is the evidence that starts it
(for a use path, root evidence such as a report reference), each later element an
edge whose source is the previous step's object, ending at the explained object.

    Report -> Sales[Revenue] -> DAX -> Sales[Amount]
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..analysis.classify import MANUAL_REVIEW, OWNER_DEPENDENCY, PROPAGATING_EVIDENCE, ROOT_EVIDENCE, propagate_used
from ..model import DependencyGraph, Evidence, EvidenceType, Finding, ObjectRef, Status
from .catalog import EVIDENCE_LABELS, STATUS_INFO

Path = tuple[Evidence, ...]

# When an object has several kinds of root evidence, show the most familiar one.
_ROOT_PRIORITY = (EvidenceType.DIRECT_REPORT_USE, EvidenceType.FIELD_PARAMETER_DEPENDENCY,
                  EvidenceType.RLS_DEPENDENCY, EvidenceType.RELATIONSHIP_DEPENDENCY)

# Evidence that puts an object under manual review by itself (not via lineage).
_REVIEW_CAUSES = MANUAL_REVIEW | OWNER_DEPENDENCY


@dataclass(frozen=True)
class Explanation:
    ref: ObjectRef
    status: Status | None  # None for objects without a cleanup status (tables, queries)
    # Used: shortest path from root evidence to the object.
    use_path: Path
    # Manual review passed on through Power Query lineage: the evidence that puts the
    # origin object under review, then the lineage edges to this object.
    review_path: Path
    # All evidence pointing at the object, in graph order.
    evidence: tuple[Evidence, ...]
    # Evidence from the object to what it references or is loaded from.
    dependencies: tuple[Evidence, ...] = ()


class Explainer:
    """Explains objects of one analysis; build once per result, query many times."""

    def __init__(self, graph: DependencyGraph, findings: list[Finding]):
        self._graph = graph
        self._status = {finding.ref: finding.status for finding in findings}
        self._used = propagate_used(graph)

    def status_of(self, ref: ObjectRef) -> Status | None:
        """Cleanup status of a column or measure; None for other objects."""
        return self._status.get(ref)

    def explain(self, ref: ObjectRef) -> Explanation:
        status = self._status.get(ref)
        return Explanation(
            ref, status,
            self.use_path(ref) if ref in self._used else (),
            self.review_path(ref) if status == Status.MANUAL_REVIEW else (),
            tuple(self._graph.incoming(ref)),
            tuple(self._graph.outgoing(ref)),
        )

    def use_path(self, ref: ObjectRef) -> Path:
        """Shortest path from root evidence to `ref`; empty if `ref` is not used."""
        if ref not in self._used:
            return ()
        via: dict[ObjectRef, Evidence] = {}
        queue, seen = deque([ref]), {ref}
        while queue:
            node = queue.popleft()
            roots = [ev for ev in self._graph.incoming(node) if ev.evidence_type in ROOT_EVIDENCE]
            root = min(roots, key=lambda ev: _ROOT_PRIORITY.index(ev.evidence_type), default=None)
            if root is not None:
                return (root, *self._chain(node, ref, via))
            for ev in self._graph.incoming(node):
                if (ev.evidence_type in PROPAGATING_EVIDENCE and ev.source in self._used
                        and ev.source not in seen):
                    seen.add(ev.source)
                    via[ev.source] = ev
                    queue.append(ev.source)
        return ()

    def review_path(self, ref: ObjectRef) -> Path:
        """For review received through lineage: origin's own evidence, then the edges."""
        if self._status.get(ref) != Status.MANUAL_REVIEW or self._own_review(ref):
            return ()
        via: dict[ObjectRef, Evidence] = {}
        queue, seen = deque([ref]), {ref}
        while queue:
            node = queue.popleft()
            cause = self._own_review(node)
            if cause is not None:
                return (cause, *self._chain(node, ref, via))
            for ev in self._graph.incoming(node):
                if (ev.evidence_type == EvidenceType.POWERQUERY_COLUMN_LINEAGE and ev.source not in seen
                        and self._status.get(ev.source) == Status.MANUAL_REVIEW):
                    seen.add(ev.source)
                    via[ev.source] = ev
                    queue.append(ev.source)
        return ()

    def _own_review(self, ref: ObjectRef) -> Evidence | None:
        return next((ev for ev in self._graph.incoming(ref) if ev.evidence_type in _REVIEW_CAUSES), None)

    @staticmethod
    def _chain(start: ObjectRef, end: ObjectRef, via: dict[ObjectRef, Evidence]) -> list[Evidence]:
        chain, node = [], start
        while node != end:
            edge = via[node]
            chain.append(edge)
            node = edge.target
        return chain


def review_reason(explainer: Explainer, finding: Finding) -> str:
    """Why an object is held for review: a lineage path, or its own evidence with
    the owner's status when the owner is not Used."""
    explanation = explainer.explain(finding.ref)
    if explanation.review_path:
        return "via " + format_path(explanation.review_path)
    reasons = []
    for ev in explanation.evidence:
        if ev.evidence_type not in _REVIEW_CAUSES:
            continue
        reason = ev.reason
        owner = explainer.status_of(ev.source) if ev.source is not None else None
        if owner is not None and owner != Status.USED:
            reason += f" ({ev.source.label} is {STATUS_INFO[owner].label})"
        if reason not in reasons:
            reasons.append(reason)
    return "; ".join(reasons) or " | ".join(finding.reasons) or "Unresolved dependency"


def format_path(path: Path) -> str:
    """`Report -> Sales[Revenue] -> DAX -> Sales[Amount]`; empty for an empty path."""
    if not path:
        return ""
    first = path[0]
    parts = [EVIDENCE_LABELS[first.evidence_type], first.target.label]
    # Start at the owning object when there is one (an unused measure's DAX, a
    # hierarchy); report evidence and synthetic `Special:` owners start at the type.
    if first.source is not None and not first.source.table.startswith("Special:"):
        parts.insert(0, first.source.label)
    for edge in path[1:]:
        parts += [EVIDENCE_LABELS[edge.evidence_type], edge.target.label]
    return " -> ".join(parts)
