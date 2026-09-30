from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, norm_key, read_source_text

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


@dataclass(frozen=True)
class Relationship:
    name: str
    from_column: tuple[str, str] | None
    to_column: tuple[str, str] | None
    cross_filtering_behavior: str
    is_active: str
    source_file: str
    line: int
    from_cardinality: str = ""
    to_cardinality: str = ""


def parse_relationship_metadata(model_folder: Path) -> list[Relationship]:
    path = model_folder / "definition" / "relationships.tmdl"
    if not path.exists():
        return []
    relationships = []
    name = None
    properties = {}
    header_indent = 0
    property_indent = None
    line_number = 0

    def finish():
        if name is not None:
            relationships.append(Relationship(
                name, _parse_ref(properties.get("fromColumn", "")),
                _parse_ref(properties.get("toColumn", "")),
                properties.get("crossFilteringBehavior", ""),
                properties.get("isActive", "true"), str(path), line_number,
                properties.get("fromCardinality", ""), properties.get("toCardinality", "")))

    for number, raw in enumerate(read_source_text(path)[0].splitlines(), 1):
        stripped = raw.strip()
        indent = len(raw.expandtabs(4)) - len(raw.expandtabs(4).lstrip())
        if not stripped or stripped.startswith("//"):
            continue
        if indent == 0 and stripped.startswith("relationship "):
            finish()
            name = clean_name(stripped[len("relationship "):]) or ""
            properties = {}
            header_indent = indent
            property_indent = None
            line_number = number
        elif name is not None and indent > header_indent:
            if property_indent is None:
                property_indent = indent
            if indent == property_indent and ":" in stripped:
                key, value = stripped.split(":", 1)
                if key in {"fromColumn", "toColumn", "crossFilteringBehavior", "isActive", "fromCardinality", "toCardinality"}:
                    properties[key] = value.strip()
        else:
            finish()
            name = None
    finish()
    return relationships


def relationship_evidence(relationships: list[Relationship], columns: dict[tuple[str, str], ObjectRef]) -> list[Evidence]:
    evidence = []
    for relationship in relationships:
        for endpoint in (relationship.from_column, relationship.to_column):
            if endpoint:
                ref = columns.get(norm_key(*endpoint))
                if ref:
                    evidence.append(Evidence(None, ref, EvidenceType.RELATIONSHIP_DEPENDENCY,
                                             "Used as relationship endpoint", relationship.source_file, "high"))
    return evidence


def parse_relationships(model_folder: Path, columns: dict[tuple[str, str], ObjectRef]) -> list[Evidence]:
    return relationship_evidence(parse_relationship_metadata(model_folder), columns)
