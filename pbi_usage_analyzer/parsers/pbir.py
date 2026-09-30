from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, is_internal_table, load_json, norm_key


@dataclass
class ReportParseResult:
    evidence: list[Evidence] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)
    fallback: list[dict] = field(default_factory=list)
    auto_date: list[dict] = field(default_factory=list)
    raw_hits: list[dict] = field(default_factory=list)
    structured_refs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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
    all_json_strings: dict[Path, str] = {}

    for path, scope in files:
        try:
            data = load_json(path)
        except Exception as exc:
            result.warnings.append(f"Kunne ikke lese {path}: {exc}")
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
                continue
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
                    continue
            result.stale.append({"Type": typ, "Table": table, "Field": field, "Source file": str(path.relative_to(report_folder))})

        strings: list[str] = []
        _collect_strings(data, strings)
        all_json_strings[path] = "\n".join(strings).casefold()

    # Conservative raw-report safety net. Require the field token plus either its table
    # token or a unique field name. This is intentionally manual-review evidence only.
    field_counts: dict[str, int] = {}
    for (_, field), ref in columns.items():
        field_counts[field] = field_counts.get(field, 0) + 1

    for (_, _), ref in columns.items():
        if ref in accounted_columns or is_internal_table(ref.table):
            continue
        table_token, field_token = ref.table.casefold(), ref.name.casefold()
        if not field_token:
            continue
        hits: list[str] = []
        for path, blob in all_json_strings.items():
            if field_token in blob and (table_token in blob or field_counts.get(field_token, 0) == 1):
                hits.append(str(path.relative_to(report_folder)))
        if hits:
            result.evidence.append(Evidence(None, ref, EvidenceType.RAW_REPORT_REFERENCE, "Unparsed report reference detected", " | ".join(hits), "low"))
            result.raw_hits.append({"Table": ref.table, "Column": ref.name, "Source files": " | ".join(hits)})
    return result
