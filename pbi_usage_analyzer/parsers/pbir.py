from __future__ import annotations

from json import JSONDecodeError
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..diagnostics import Diagnostic, DiagnosticCollection, DiagnosticSeverity
from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, is_internal_table, load_json, norm_key, read_source_text


@dataclass
class ReportParseResult(DiagnosticCollection):
    evidence: list[Evidence] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)
    fallback: list[dict] = field(default_factory=list)
    auto_date: list[dict] = field(default_factory=list)
    raw_hits: list[dict] = field(default_factory=list)
    structured_refs: list[dict] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _source_mappings(obj, mappings: dict[str, str]) -> None:
    if isinstance(obj, dict):
        frm = obj.get("From")
        if isinstance(frm, list):
            for item in frm:
                if isinstance(item, dict):
                    name, entity = item.get("Name"), item.get("Entity")
                    if name and entity:
                        mappings[str(name)] = clean_name(entity) or str(entity)
        for value in obj.values():
            _source_mappings(value, mappings)
    elif isinstance(obj, list):
        for value in obj:
            _source_mappings(value, mappings)


def _table_from_expression(expr, mappings: dict[str, str]) -> str | None:
    if not isinstance(expr, dict):
        return None
    ent = expr.get("Entity")
    if isinstance(ent, dict):
        entity = ent.get("Entity") or ent.get("Name")
        if entity:
            return clean_name(entity)
    src = expr.get("SourceRef")
    if isinstance(src, dict):
        # Query-command form: an alias declared in a From list.
        source = src.get("Source")
        if source:
            return mappings.get(str(source), clean_name(source))
        # visualContainer form: the entity is named directly.
        entity = src.get("Entity")
        if entity:
            return clean_name(entity)
    return None


def _find_refs(obj, mappings: dict[str, str], out: list[tuple[str, str, str]]) -> None:
    if isinstance(obj, dict):
        for typ in ("Column", "Measure", "Hierarchy", "HierarchyLevel"):
            node = obj.get(typ)
            if isinstance(node, dict):
                expr = node.get("Expression")
                # A level's table is on its nested hierarchy; the hierarchy itself is
                # found separately when recursion reaches it.
                if typ == "HierarchyLevel" and isinstance(expr, dict) and isinstance(expr.get("Hierarchy"), dict):
                    expr = expr["Hierarchy"].get("Expression")
                variation = expr.get("PropertyVariationSource") if isinstance(expr, dict) else None
                if isinstance(variation, dict):
                    # Auto-date hierarchy over a business column: that column is used.
                    table = _table_from_expression(variation.get("Expression"), mappings)
                    column = variation.get("Property")
                    if table and column:
                        out.append((table, clean_name(column) or str(column), "Column"))
                    continue
                table = _table_from_expression(expr, mappings)
                field = node.get("Property") or node.get("Name") or node.get("Level")
                if typ == "Hierarchy" and not field and isinstance(node.get("Hierarchy"), str):
                    field = node["Hierarchy"]
                if table and field:
                    out.append((table, clean_name(field) or str(field), typ))
        for value in obj.values():
            _find_refs(value, mappings, out)
    elif isinstance(obj, list):
        for value in obj:
            _find_refs(value, mappings, out)


def _collect_strings(obj, values: list[str], keys: list[str]) -> None:
    if isinstance(obj, str):
        values.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(str(k))
            _collect_strings(v, values, keys)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, values, keys)


def _unique_fallback(field: str, index: dict[tuple[str, str], ObjectRef]) -> ObjectRef | None:
    wanted = (clean_name(field) or "").casefold()
    candidates = [ref for (_, f), ref in index.items() if f == wanted]
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


QUALIFIED_FIELD_TEXT = re.compile(
    r"(?:'(?P<quoted>(?:[^']|'')*)'|(?<![\w'.])(?P<plain>[^\W\d]\w*))\s*\[(?P<field>(?:[^\]]|\]\])*)\]")


def _qualified_field_refs(text: str) -> set[tuple[str, str]]:
    """(table, field) pairs written DAX-style ('Table'[Field] / Table[Field]) in text.

    Names are returned unescaped and compared as given; callers pass casefolded text.
    """
    refs = set()
    for match in QUALIFIED_FIELD_TEXT.finditer(text):
        quoted = match.group("quoted")
        table = quoted.replace("''", "'") if quoted is not None else match.group("plain")
        refs.add((table, match.group("field").replace("]]", "]")))
    return refs


UNQUALIFIED_FIELD_TEXT = re.compile(r"(?<![\w'\]])\[((?:[^\]]|\]\])*)\]")


@dataclass(frozen=True)
class ReportText:
    """Casefolded text of one readable report file for the raw safety net."""
    blob: str                       # string values and keys, newline-joined
    values: frozenset[str]          # whole string values, stripped
    qualified: frozenset[tuple[str, str]]  # DAX-style Table[Field] pairs
    bracketed: frozenset[str]       # unqualified [Field] names

    @classmethod
    def from_strings(cls, values: list[str], keys: list[str]) -> "ReportText":
        blob = "\n".join(values + keys).casefold()
        return cls(blob, frozenset(v.strip().casefold() for v in values), frozenset(_qualified_field_refs(blob)),
                   frozenset(m.group(1).replace("]]", "]") for m in UNQUALIFIED_FIELD_TEXT.finditer(blob)))


def _dotted_occurs(blob: str, needle: str) -> bool:
    """`Table.Field` in text, not preceded or followed by more identifier text."""
    start = blob.find(needle)
    while start >= 0:
        end = start + len(needle)
        before = blob[start - 1] if start else " "
        after = blob[end] if end < len(blob) else " "
        if not (before.isalnum() or before in "_.") and not (after.isalnum() or after == "_"):
            return True
        start = blob.find(needle, start + 1)
    return False


def _readable_hit_files(ref: ObjectRef, texts: dict[Path, ReportText]) -> list[Path]:
    """Files whose readable JSON credibly references a field outside parsed nodes.

    Names are often ordinary words, so substrings are not evidence. Require a
    qualified form (`Table.Field` with boundaries, `'Table'[Field]`/`Table[Field]`),
    or the exact name as a whole string value or unqualified `[Field]` in a file
    that also has the table name as a whole string value. JSON keys only count
    within qualified forms.
    """
    table, name = ref.table.casefold(), ref.name.casefold()
    if not name:
        return []
    dotted = f"{table}.{name}"
    return [path for path, text in texts.items()
            if (table, name) in text.qualified or _dotted_occurs(text.blob, dotted)
            or ((name in text.values or name in text.bracketed) and table in text.values)]


def parse_report(report_folder: Path, columns: dict[tuple[str, str], ObjectRef], measures: dict[tuple[str, str], ObjectRef], hierarchies: dict[tuple[str, str], ObjectRef]) -> ReportParseResult:
    result = ReportParseResult()
    definition = report_folder / "definition"
    files: list[tuple[Path, str]] = []
    if (definition / "report.json").exists():
        files.append((definition / "report.json", "Report"))
    pages = definition / "pages"
    if pages.exists():
        for page in sorted(p for p in pages.iterdir() if p.is_dir()):
            if (page / "page.json").exists():
                files.append((page / "page.json", "Page"))
            visuals = page / "visuals"
            if visuals.exists():
                for visual in sorted(p for p in visuals.iterdir() if p.is_dir()):
                    if (visual / "visual.json").exists():
                        files.append((visual / "visual.json", "Visual"))

    accounted_columns: set[ObjectRef] = set()
    accounted_measures: set[ObjectRef] = set()
    texts: dict[Path, ReportText] = {}
    unreadable_text: dict[Path, str] = {}

    for path, scope in files:
        try:
            data = load_json(path)
        except Exception as exc:
            result.diagnostics.append(Diagnostic(
                "PBIR_READ_FAILED", DiagnosticSeverity.WARNING,
                f"Could not read {path}: {exc}. Its raw text was scanned for "
                "manual-review evidence only.", source_file=str(path),
                line=exc.lineno if isinstance(exc, JSONDecodeError) else None,
                column=exc.colno if isinstance(exc, JSONDecodeError) else None))
            try:
                unreadable_text[path] = read_source_text(path)[0].casefold()
            except OSError:
                pass
            continue
        mappings: dict[str, str] = {}
        _source_mappings(data, mappings)
        refs: list[tuple[str, str, str]] = []
        _find_refs(data, mappings, refs)
        seen = set()
        for table, field, typ in refs:
            key3 = (table.casefold(), field.casefold(), typ)
            if key3 in seen:
                continue
            seen.add(key3)
            result.structured_refs.append({"Scope": scope, "Table": table, "Field": field, "Field type": typ, "Source file": str(path.relative_to(report_folder))})
            if is_internal_table(table):
                continue
            idx = columns if typ == "Column" else measures if typ == "Measure" else hierarchies if typ == "Hierarchy" else None
            target = idx.get(norm_key(table, field)) if idx else None
            if typ == "HierarchyLevel":
                # Level names normally match their backing column; the enclosing
                # hierarchy reference protects every level regardless.
                target = columns.get(norm_key(table, field))
            if target:
                result.evidence.append(Evidence(None, target, EvidenceType.DIRECT_REPORT_USE, f"{scope}-level report reference", str(path), "high"))
                if target.object_type == ObjectType.COLUMN:
                    accounted_columns.add(target)
                elif target.object_type == ObjectType.MEASURE:
                    accounted_measures.add(target)
                continue
            # These localized Power BI identifiers are input data, not UI text.
            if typ in {"Hierarchy", "HierarchyLevel"} and field.casefold() in {"år", "måned", "kvartal", "dag", "datohierarki"}:
                result.auto_date.append({"Type": typ, "Table": table, "Field": field, "Source file": str(path.relative_to(report_folder))})
                continue
            if idx is not None:
                fb = _unique_fallback(field, idx)
                if fb:
                    result.evidence.append(Evidence(None, fb, EvidenceType.FALLBACK_MATCH, f"Fallback match from {table}[{field}]", str(path), "medium"))
                    result.fallback.append({"Type": typ, "Report table": table, "Report field": field, "Matched model table": fb.table, "Matched model field": fb.name})
                    if fb.object_type == ObjectType.COLUMN:
                        accounted_columns.add(fb)
                    elif fb.object_type == ObjectType.MEASURE:
                        accounted_measures.add(fb)
                    continue
            result.stale.append({"Type": typ, "Table": table, "Field": field, "Source file": str(path.relative_to(report_folder))})

        values: list[str] = []
        keys: list[str] = []
        _collect_strings(data, values, keys)
        texts[path] = ReportText.from_strings(values, keys)

    # Conservative raw-report safety net; manual-review evidence only. Readable files
    # use the qualified/whole-name rule. Unreadable files have no structure, so their
    # raw text uses a looser substring rule: field token plus its table token or a
    # field name unique among fields of that kind.
    def unreadable_hits(ref: ObjectRef, counts: dict[str, int]) -> list[Path]:
        table_token, field_token = ref.table.casefold(), ref.name.casefold()
        if not field_token:
            return []
        return [path for path, blob in unreadable_text.items()
                if field_token in blob and (table_token in blob or counts.get(field_token, 0) == 1)]

    def record(ref: ObjectRef, paths: list[Path], reason: str) -> None:
        files = " | ".join(str(path.relative_to(report_folder)) for path in paths)
        result.evidence.append(Evidence(None, ref, EvidenceType.RAW_REPORT_REFERENCE, reason, files, "low"))
        result.raw_hits.append({"Type": ref.object_type.value, "Table": ref.table, "Field": ref.name, "Source files": files})

    column_counts: dict[str, int] = {}
    for (_, field), ref in columns.items():
        column_counts[field] = column_counts.get(field, 0) + 1
    for (_, _), ref in columns.items():
        if ref in accounted_columns or is_internal_table(ref.table):
            continue
        hits = _readable_hit_files(ref, texts) + unreadable_hits(ref, column_counts)
        if hits:
            record(ref, hits, "Unparsed report reference detected")

    measure_counts: dict[str, int] = {}
    for (_, field), ref in measures.items():
        measure_counts[field] = measure_counts.get(field, 0) + 1
    for (_, _), ref in measures.items():
        if is_internal_table(ref.table):
            continue
        hits = unreadable_hits(ref, measure_counts)
        if hits:
            record(ref, hits, "Reference in unreadable report file")
        if ref in accounted_measures:
            continue
        hits = _readable_hit_files(ref, texts)
        if hits:
            record(ref, hits, "Unparsed report measure reference detected")
    return result
