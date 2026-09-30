from __future__ import annotations

import re
from pathlib import Path

from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, norm_key

# Handles e.g. fromColumn: 'Hovedbok'.firma and fromColumn: Hovedbok.firma
REF_RE = re.compile(r"(?:(?:'(?P<quoted>(?:[^']|'')+)')|(?P<plain>[^.]+))\.(?P<field>.+)$")


def _parse_ref(value: str) -> tuple[str, str] | None:
    value = value.strip()
    m = REF_RE.match(value)
    if not m:
        return None
    table = clean_name(m.group("quoted") or m.group("plain")) or ""
    field = clean_name(m.group("field")) or ""
    return table, field


def parse_relationships(model_folder: Path, columns: dict[tuple[str, str], ObjectRef]) -> list[Evidence]:
    path = model_folder / "definition" / "relationships.tmdl"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    evidence: list[Evidence] = []
    current: dict[str, str] = {}
    for raw in text.splitlines() + [""]:
        stripped = raw.strip()
        if not stripped:
            if current:
                for side in ("fromColumn", "toColumn"):
                    parsed = _parse_ref(current.get(side, ""))
                    if parsed:
                        ref = columns.get(norm_key(*parsed))
                        if ref:
                            evidence.append(Evidence(None, ref, EvidenceType.RELATIONSHIP_DEPENDENCY, "Used as relationship endpoint", str(path), "high"))
                current = {}
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in {"fromColumn", "toColumn"}:
                current[key] = value.strip()
    return evidence
