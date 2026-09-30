from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, is_internal_table, norm_key
from .dax_lexer import mask_dax

QUALIFIED_DAX_REF = re.compile(
    r"""
    (?:'(?P<quoted>(?:[^']|'')+)'|(?P<plain>[A-Za-z_ÆØÅæøå][A-Za-z0-9_ÆØÅæøå .\-]*))
    \s*\[(?P<field>(?:[^\]]|\]\])+)\]
    """,
    re.VERBOSE,
)
UNQUALIFIED_DAX_REF = re.compile(r"(?<![\w'])\[((?:[^\]]|\]\])+)\]")
BRACKETED = re.compile(r"\[(?:[^\]]|\]\])*\]")
QUOTED_TABLE = re.compile(r"'((?:[^']|'')*)'")
IDENTIFIER = re.compile(r"[^\W\d]\w*")


def _field_name(raw: str) -> str:
    return clean_name(raw.replace("]]", "]")) or ""


def _qualified_table(match: re.Match, tables: set[str]) -> str | None:
    """Return the table of a qualified reference, or None if it is not one.

    Unquoted DAX table names cannot contain spaces, so text such as
    ``RETURN [Margin]`` or ``NOT Sales[Flag]`` is resolved by taking the longest
    trailing word sequence that names a known table.
    """
    quoted = match.group("quoted")
    if quoted is not None:
        # The pattern excludes the outer apostrophes; restore them so '' unescapes.
        return clean_name(f"'{quoted}'") or ""
    words = match.group("plain").split()
    for i in range(len(words)):
        candidate = " ".join(words[i:])
        if candidate.casefold() in tables:
            return candidate
    return None


def _mentioned_tables(expression: str) -> set[str]:
    """Casefolded table-like names in masked DAX, excluding bracketed names."""
    text = BRACKETED.sub(lambda m: " " * len(m.group()), expression)
    names = {(clean_name(f"'{m.group(1)}'") or "").casefold() for m in QUOTED_TABLE.finditer(text)}
    text = QUOTED_TABLE.sub(lambda m: " " * len(m.group()), text)
    return names | {m.group().casefold() for m in IDENTIFIER.finditer(text)}


@dataclass(frozen=True)
class DaxIndex:
    """Name lookups for DAX resolution, built once per analysis."""
    columns: dict[tuple[str, str], ObjectRef]
    measures: dict[tuple[str, str], ObjectRef]
    tables: frozenset[str]
    measures_by_name: dict[str, tuple[ObjectRef, ...]]
    business_columns_by_name: dict[str, tuple[ObjectRef, ...]]

    @classmethod
    def build(cls, columns: dict[tuple[str, str], ObjectRef], measures: dict[tuple[str, str], ObjectRef]) -> "DaxIndex":
        measures_by_name: dict[str, list[ObjectRef]] = {}
        for (_, field), ref in measures.items():
            measures_by_name.setdefault(field, []).append(ref)
        columns_by_name: dict[str, list[ObjectRef]] = {}
        for (_, field), ref in columns.items():
            if not is_internal_table(ref.table):
                columns_by_name.setdefault(field, []).append(ref)
        return cls(columns, measures, frozenset(t for t, _ in columns) | frozenset(t for t, _ in measures),
                   {k: tuple(v) for k, v in measures_by_name.items()},
                   {k: tuple(v) for k, v in columns_by_name.items()})


def dax_dependencies(owner: ObjectRef, expression: str, columns: dict[tuple[str, str], ObjectRef],
                     measures: dict[tuple[str, str], ObjectRef], *, row_table: str | None = None,
                     index: DaxIndex | None = None) -> list[Evidence]:
    """Extract DAX references from an expression owned by ``owner``.

    ``row_table`` names a table whose row context is certain for the whole
    expression (calculated columns, RLS table permissions). Unqualified column
    names outside that context cannot be bound reliably without a DAX grammar
    and produce manual-review evidence only. Pass a prebuilt ``index`` (for the
    same ``columns``/``measures``) when resolving many expressions.
    """
    if not expression:
        return []

    # Strings and comments cannot reference model objects. Malformed trailing
    # literals stay unmasked so uncertain lexing never removes evidence.
    expression = mask_dax(expression, keep_unterminated=True).text
    if index is None:
        index = DaxIndex.build(columns, measures)
    tables = index.tables
    evidence: list[Evidence] = []
    consumed_spans: list[tuple[int, int]] = []
    for match in QUALIFIED_DAX_REF.finditer(expression):
        table = _qualified_table(match, tables)
        if table is None:
            continue
        field = _field_name(match.group("field"))
        key = norm_key(table, field)
        target = columns.get(key) or measures.get(key)
        if target:
            evidence.append(Evidence(owner, target, EvidenceType.DAX_DEPENDENCY, f"Referenced by {owner.label}", confidence="high"))
        consumed_spans.append((match.start("field") - 1, match.end()))

    mentioned: set[str] | None = None
    for match in UNQUALIFIED_DAX_REF.finditer(expression):
        if any(a <= match.start() < b for a, b in consumed_spans):
            continue
        field = _field_name(match.group(1))
        # Measures resolve first in the owner's table, then uniquely across the model.
        target = measures.get(norm_key(owner.table, field))
        if not target:
            candidates = index.measures_by_name.get(field.casefold(), ())
            if len(candidates) == 1:
                target = candidates[0]
        if target:
            evidence.append(Evidence(owner, target, EvidenceType.DAX_DEPENDENCY, f"Referenced by {owner.label}", confidence="high"))
        column = columns.get(norm_key(row_table, field)) if row_table else None
        if column:
            evidence.append(Evidence(owner, column, EvidenceType.DAX_DEPENDENCY,
                                     f"Referenced by {owner.label} in {row_table} row context", confidence="high"))
        if target or column:
            continue
        candidates = index.business_columns_by_name.get(field.casefold(), ())
        if not candidates:
            continue
        if mentioned is None:
            mentioned = _mentioned_tables(expression)
        # Prefer tables the expression names (e.g. an iterator's table argument).
        narrowed = [ref for ref in candidates if ref.table.casefold() in mentioned]
        for ref in narrowed or candidates:
            evidence.append(Evidence(owner, ref, EvidenceType.DAX_UNQUALIFIED_COLUMN_REFERENCE,
                                     f"Unqualified [{field}] in {owner.label}; row context not resolved",
                                     confidence="low"))
    return evidence
