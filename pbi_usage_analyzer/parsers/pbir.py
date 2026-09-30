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
        source = src.get("Source")
        if source:
            return mappings.get(str(source), clean_name(source))
    return None


def _find_refs(obj, mappings: dict[str, str], out: list[tuple[str, str, str]]) -> None:
    if isinstance(obj, dict):
        for typ in ("Column", "Measure", "Hierarchy", "HierarchyLevel"):
            node = obj.get(typ)
            if isinstance(node, dict):
                table = _table_from_expression(node.get("Expression"), mappings)
                field = node.get("Property") or node.get("Name") or node.get("Level")
                if table and field:
                    out.append((table, clean_name(field) or str(field), typ))
        for value in obj.values():
            _find_refs(value, mappings, out)
    elif isinstance(obj, list):
        for value in obj:
            _find_refs(value, mappings, out)


def _collect_strings(obj, values: list[str]) -> None:
    if isinstance(obj, str):
        values.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            values.append(str(k))
            _collect_strings(v, values)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, values)


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


def _measure_hit_files(ref: ObjectRef, file_strings: dict[Path, set[str]],
                       file_refs: dict[Path, set[tuple[str, str]]], unique_name: bool) -> list[Path]:
    """Files whose readable JSON credibly references a measure outside parsed nodes.

    Measure names are often ordinary words, so substrings are not enough: require
    `Table.Measure` as a whole string, DAX-style `Table[Measure]` text, or the exact
    measure name as a whole string when it is unique in the model and the same
    file names its table.
    """
    table, name = ref.table.casefold(), ref.name.casefold()
    qualified = f"{table}.{name}"
    hits = []
    for path, strings in file_strings.items():
        if (qualified in strings or (table, name) in file_refs[path]
                or (unique_name and name in strings and table in strings)):
            hits.append(path)
    return hits


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
    file_strings: dict[Path, set[str]] = {}
    file_refs: dict[Path, set[tuple[str, str]]] = {}
    all_json_strings: dict[Path, str] = {}
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

        strings: list[str] = []
        _collect_strings(data, strings)
        all_json_strings[path] = "\n".join(strings).casefold()
        file_strings[path] = {value.strip().casefold() for value in strings}
        file_refs[path] = _qualified_field_refs(all_json_strings[path])

    # Conservative raw-report safety net. Require the field token plus either its table
    # token or a unique field name. This is intentionally manual-review evidence only.
    field_counts: dict[str, int] = {}
    for (_, field), ref in columns.items():
        field_counts[field] = field_counts.get(field, 0) + 1

    def hit_files(ref: ObjectRef, blobs: dict[Path, str], counts: dict[str, int]) -> list[str]:
        table_token, field_token = ref.table.casefold(), ref.name.casefold()
        if not field_token:
            return []
        return [str(path.relative_to(report_folder)) for path, blob in blobs.items()
                if field_token in blob and (table_token in blob or counts.get(field_token, 0) == 1)]

    for (_, _), ref in columns.items():
        if ref in accounted_columns or is_internal_table(ref.table):
            continue
        hits = hit_files(ref, {**all_json_strings, **unreadable_text}, field_counts)
        if hits:
            result.evidence.append(Evidence(None, ref, EvidenceType.RAW_REPORT_REFERENCE, "Unparsed report reference detected", " | ".join(hits), "low"))
            result.raw_hits.append({"Type": ref.object_type.value, "Table": ref.table, "Field": ref.name, "Source files": " | ".join(hits)})

    # Measures: unreadable files have no structure, so their raw text uses the
    # column rule. Readable files use the stricter measure rule for measures that
    # structured parsing did not account for.
    measure_counts: dict[str, int] = {}
    for (_, field), ref in measures.items():
        measure_counts[field] = measure_counts.get(field, 0) + 1
    for (_, _), ref in measures.items():
        if is_internal_table(ref.table):
            continue
        hits = hit_files(ref, unreadable_text, measure_counts)
        if hits:
            result.evidence.append(Evidence(None, ref, EvidenceType.RAW_REPORT_REFERENCE, "Reference in unreadable report file", " | ".join(hits), "low"))
            result.raw_hits.append({"Type": ref.object_type.value, "Table": ref.table, "Field": ref.name, "Source files": " | ".join(hits)})
        if ref in accounted_measures:
            continue
        name = ref.name.casefold()
        unique = measure_counts.get(name, 0) + field_counts.get(name, 0) == 1
        readable = [str(path.relative_to(report_folder))
                    for path in _measure_hit_files(ref, file_strings, file_refs, unique)]
        if readable:
            result.evidence.append(Evidence(None, ref, EvidenceType.RAW_REPORT_REFERENCE, "Unparsed report measure reference detected", " | ".join(readable), "low"))
            result.raw_hits.append({"Type": ref.object_type.value, "Table": ref.table, "Field": ref.name, "Source files": " | ".join(readable)})
    return result
