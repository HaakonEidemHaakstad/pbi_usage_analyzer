from __future__ import annotations

import re

from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, norm_key

QUALIFIED_DAX_REF = re.compile(
    r"""
    (?:'(?P<quoted>(?:[^']|'')+)'|(?P<plain>[A-Za-z_ÆØÅæøå][A-Za-z0-9_ÆØÅæøå .\-]*))
    \s*\[(?P<field>[^\]]+)\]
    """,
    re.VERBOSE,
)
UNQUALIFIED_DAX_REF = re.compile(r"(?<![\w'])\[([^\]]+)\]")


def dax_dependencies(owner: ObjectRef, expression: str, columns: dict[tuple[str, str], ObjectRef], measures: dict[tuple[str, str], ObjectRef]) -> list[Evidence]:
    if not expression:
        return []

    evidence: list[Evidence] = []
    consumed_spans: list[tuple[int, int]] = []
    for match in QUALIFIED_DAX_REF.finditer(expression):
        table = clean_name(match.group("quoted") or match.group("plain")) or ""
        field = clean_name(match.group("field")) or ""
        key = norm_key(table, field)
        target = columns.get(key) or measures.get(key)
        if target:
            evidence.append(Evidence(owner, target, EvidenceType.DAX_DEPENDENCY, f"Referenced by {owner.label}", confidence="high"))
        consumed_spans.append(match.span())

    # Unqualified [Measure] references are resolved first in the owner's table,
    # then uniquely across the model.
    for match in UNQUALIFIED_DAX_REF.finditer(expression):
        if any(a <= match.start() < b for a, b in consumed_spans):
            continue
        field = clean_name(match.group(1)) or ""
        local = measures.get(norm_key(owner.table, field))
        target = local
        if not target:
            candidates = [ref for (t, f), ref in measures.items() if f == field.casefold()]
            if len(candidates) == 1:
                target = candidates[0]
        if target:
            evidence.append(Evidence(owner, target, EvidenceType.DAX_DEPENDENCY, f"Referenced by {owner.label}", confidence="high"))
    return evidence
