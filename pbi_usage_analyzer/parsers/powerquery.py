from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..diagnostics import Diagnostic, DiagnosticCollection, DiagnosticSeverity
from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import clean_name, norm, read_source_text
from .m_lineage import ColumnDemand, ColumnLineage, parse_column_lineage


@dataclass
class PowerQueryResult(DiagnosticCollection):
    evidence: list[Evidence] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Complete source-name projections for the bounded M shape below.
    projected_columns: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    column_demands: dict[tuple[str, str], ColumnDemand] = field(default_factory=dict)
    # Per owner query, the lineage of every M partition when all are supported.
    lineages: dict[str, tuple[ColumnLineage, ...]] = field(default_factory=dict)


def _strip_comments_and_strings(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        if in_string:
            if text[i] == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            out.append(" ")
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            if j == -1:
                out.extend(" " * (len(text) - i))
                break
            out.extend(" " * (j - i))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                out.extend(" " * (len(text) - i))
                break
            out.extend(" " * (j + 2 - i))
            i = j + 2
            continue
        if text[i] == '"':
            in_string = True
            out.append(" ")
            i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _extract_partition_m_sources(text: str) -> list[str]:
    """Extract source = blocks only from partition definitions.

    TMDL commonly stores M as:
        partition X = m
            mode: import
            source =
                let
                    ...
                in
                    ...
    """
    lines = text.splitlines()
    sources: list[str] = []
    partition_indent = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped and partition_indent is not None and indent <= partition_indent:
            partition_indent = None
        if stripped.lower().startswith("partition "):
            partition_indent = indent if re.search(r"=\s*m\s*$", stripped, re.I) else None
            i += 1
            continue
        if partition_indent is not None and stripped.startswith("source ="):
            source_indent = len(line) - len(line.lstrip())
            inline = stripped[len("source ="):].strip()
            collected = [inline] if inline else []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= source_indent:
                    break
                collected.append(nxt.strip())
                i += 1
            sources.append("\n".join(collected).strip())
            continue
        i += 1
    return [s for s in sources if s]


def _selected_columns(source: str, dependency: str) -> set[str] | None:
    """Recognize a complete source -> SelectColumns -> output expression only.

    Full matching prevents dead steps, comments, strings and later transforms
    from being mistaken for complete lineage. Other shapes remain unresolved.
    """
    identifier = r'(?:#"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*)'
    literal = r'"(?:[^"]|"")*"'
    match = re.fullmatch(
        rf'\s*let\s+(?P<step>{identifier})\s*=\s*(?P<query>{identifier})\s*,\s*'
        rf'(?P<selected>{identifier})\s*=\s*Table\.SelectColumns\(\s*'
        rf'(?P<input>{identifier})\s*,\s*\{{\s*(?P<fields>{literal}(?:\s*,\s*{literal})*)\s*\}}\s*\)'
        rf'\s*in\s+(?P<output>{identifier})\s*', source,
    )
    if not match:
        return None

    def decode(value: str) -> str:
        return value[2:-1].replace('""', '"') if value.startswith('#"') else value

    if (decode(match['step']) != decode(match['input'])
            or decode(match['selected']) != decode(match['output'])
            or decode(match['step']) == decode(match['selected'])
            or decode(match['query']) in {decode(match['step']), decode(match['selected'])}
            or norm(decode(match['query'])) != norm(dependency)):
        return None
    return {m.group()[1:-1].replace('""', '"') for m in re.finditer(literal, match['fields'])}


def _local_let_names(m_source: str) -> set[str]:
    cleaned = _strip_comments_and_strings(m_source)
    names: set[str] = set()
    # Step names before '=' at line starts, including #"Step Name".
    for line in cleaned.splitlines():
        stripped = line.strip().rstrip(",")
        m = re.match(r'(?:(#"(?P<q>[^"]+)")|(?P<p>[A-Za-z_][A-Za-z0-9_]*))\s*=', stripped)
        if m:
            names.add(norm(m.group("q") or m.group("p")))
    return names


def _find_query_refs(m_source: str, owner_table: str, model_tables: dict[str, str]) -> set[str]:
    # Quoted identifiers (#"Query Name") are syntactically distinct from M string
    # literals, so capture them before removing strings/comments.
    quoted_identifiers = [m.group(1).replace('""', '"') for m in re.finditer(r'#"((?:[^"]|"")+)"', m_source)]
    cleaned = _strip_comments_and_strings(m_source)
    local_names = _local_let_names(m_source)
    refs: set[str] = set()

    # Strong reference syntax: #"Query Name"
    for candidate in quoted_identifiers:
        candidate = clean_name(candidate) or ""
        key = norm(candidate)
        if key in model_tables and key != norm(owner_table) and key not in local_names:
            refs.add(model_tables[key])

    # Simple identifier references are much more ambiguous. Only accept if the full
    # identifier is a model query name, is not a local step, and is not immediately
    # preceded by '[' or followed by '=' / '[' / '('. M identifiers are
    # case-sensitive and may contain dots, so `type date` and `Date.From` are not
    # the query `Date`; `#date` is an intrinsic.
    for key, display in model_tables.items():
        if key == norm(owner_table) or key in local_names:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", display):
            continue
        pattern = rf"(?<![\[\w.#]){re.escape(display)}(?![\w.])(?!\s*[=\[(])"
        if re.search(pattern, cleaned):
            refs.add(display)
    return refs


def parse_power_query_dependencies(model_folder: Path, table_names: set[str]) -> PowerQueryResult:
    result = PowerQueryResult()
    tables_folder = model_folder / "definition" / "tables"
    model_tables = {norm(t): t for t in table_names}
    for path in sorted(tables_folder.glob("*.tmdl")):
        text, _ = read_source_text(path)
        owner = None
        for line in text.splitlines():
            if line.strip().lower().startswith("table "):
                owner = clean_name(line.strip()[len("table "):])
                break
        if not owner:
            continue
        sources = _extract_partition_m_sources(text)
        parsed = [parse_column_lineage(source, model_tables, owner) for source in sources]
        inferred = [None if lineage is None else lineage.demands() for lineage in parsed]
        complete = bool(sources) and all(demands is not None for demands in inferred)
        if complete:
            result.lineages[owner] = tuple(parsed)
        for source, demands in zip(sources, inferred):
            dependencies = demands.keys() if demands is not None else _find_query_refs(source, owner, model_tables)
            for dependency in sorted(dependencies):
                owner_ref = ObjectRef(ObjectType.QUERY, owner)
                dep_ref = ObjectRef(ObjectType.QUERY, dependency)
                ev = Evidence(owner_ref, dep_ref, EvidenceType.POWERQUERY_QUERY_DEPENDENCY, f"Query '{owner}' references query '{dependency}'", str(path), "high")
                selected = _selected_columns(source, dependency)
                if len(sources) == 1 and selected is not None:
                    result.projected_columns[(owner, dependency)] = selected
                result.evidence.append(ev)
                result.dependencies.append({"Query": owner, "Depends on query": dependency, "Source file": str(path)})
                if complete:
                    key = (owner, dependency)
                    demand = demands[dependency]
                    if key in result.column_demands:
                        demand = result.column_demands[key].union(demand)
                    result.column_demands[key] = demand
        if not complete and any(ev.source.table == owner for ev in result.evidence):
            result.diagnostics.append(Diagnostic(
                "M_LINEAGE_INCOMPLETE", DiagnosticSeverity.WARNING,
                f"Query {owner}: column lineage is incomplete; unsupported M expressions "
                "retain conservative query-level evidence.",
                source_file=str(path), object_ref=ObjectRef(ObjectType.QUERY, owner),
            ))
    return result
