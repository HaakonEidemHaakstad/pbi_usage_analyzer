"""Immutable table rows over an analysis result, with stable keys and filters.

Front ends render these rows instead of walking the graph. Filters follow the
health-filter semantics: `None` is unrestricted, an empty selection matches
nothing, values within one selection are ORed and selections are ANDed.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..api import AnalysisResult
from ..health.model import HealthFinding, HealthSeverity
from ..model import ObjectRef, ObjectType, Status
from .catalog import STATUS_INFO, category_label, rule_info


def object_key(ref: ObjectRef) -> str:
    """Stable key of a model object, e.g. `Column|Sales|Amount`."""
    return f"{ref.object_type.value}|{ref.table}|{ref.name}"


def health_key(finding: HealthFinding, project_root: Path | None = None) -> str:
    """Stable key of a health finding: rule, scope and source file.

    The file is relative to the project root when inside it, so the key survives
    moving the project folder.
    """
    source = Path(finding.source_file) if finding.source_file else None
    if source is not None and project_root is not None:
        try:
            source = source.resolve().relative_to(project_root.resolve())
        except ValueError:
            pass
    return f"{finding.rule_id}|{finding.scope}|{source.as_posix() if source else ''}"


@dataclass(frozen=True)
class ObjectRow:
    key: str
    ref: ObjectRef
    object_type: ObjectType
    table: str
    name: str
    status: Status
    status_label: str
    internal: bool
    hidden: bool
    calculated: bool
    data_type: str | None
    source_file: str
    source_line: int | None
    evidence_types: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class HealthRow:
    key: str
    rule_id: str
    rule_name: str
    category: str
    category_label: str
    severity: HealthSeverity
    confidence: str
    scope: str  # identity, part of the key
    # What to show for the scope: relationship endpoints instead of the
    # relationship's (usually GUID) name; otherwise the scope itself.
    scope_label: str
    object_ref: ObjectRef | None
    title: str
    explanation: str
    evidence: tuple[str, ...]
    recommendation: str
    source_file: str
    line: int | None


@dataclass(frozen=True)
class DiagnosticRow:
    code: str
    severity: str
    message: str
    source_file: str
    line: int | None
    column: int | None
    object_ref: ObjectRef | None


@dataclass(frozen=True)
class QueryDependencyRow:
    query: str
    depends_on: str
    # Load-disabled queries the reference passes through, in order.
    via: tuple[str, ...]
    source_file: str


def object_rows(result: AnalysisResult) -> tuple[ObjectRow, ...]:
    """Columns and measures with a cleanup status, in classifier order."""
    rows = []
    for finding in result.findings:
        obj = result.graph.object(finding.ref)
        rows.append(ObjectRow(
            key=object_key(finding.ref), ref=finding.ref, object_type=finding.ref.object_type,
            table=finding.ref.table, name=finding.ref.name, status=finding.status,
            status_label=STATUS_INFO[finding.status].label,
            internal=finding.status == Status.INTERNAL,
            hidden=bool(obj and obj.hidden), calculated=bool(obj and obj.calculated),
            data_type=obj.data_type if obj else None,
            source_file=obj.source_file if obj else "", source_line=obj.source_line if obj else None,
            evidence_types=tuple(finding.evidence_types), reasons=tuple(finding.reasons),
        ))
    return tuple(rows)


def _relationship_labels(result: AnalysisResult) -> dict[str, str]:
    labels = {}
    for relationship in result.context.relationships:
        if relationship.from_column and relationship.to_column:
            (from_table, from_column), (to_table, to_column) = relationship.from_column, relationship.to_column
            labels[relationship.name] = f"{from_table}[{from_column}] → {to_table}[{to_column}]"
    return labels


def health_rows(result: AnalysisResult) -> tuple[HealthRow, ...]:
    root = result.project.root
    relationships = _relationship_labels(result)

    def scope_label(finding: HealthFinding) -> str:
        if finding.category == "relationships":
            return relationships.get(finding.scope, finding.scope)
        return finding.scope

    return tuple(HealthRow(
        key=health_key(f, root), rule_id=f.rule_id, rule_name=rule_info(f.rule_id).name,
        category=f.category, category_label=category_label(f.category), severity=f.severity,
        confidence=f.confidence, scope=f.scope, scope_label=scope_label(f), object_ref=f.object_ref,
        title=f.title,
        explanation=f.explanation, evidence=tuple(f.evidence), recommendation=f.recommendation,
        source_file=f.source_file, line=f.line,
    ) for f in result.health_findings)


def diagnostic_rows(result: AnalysisResult) -> tuple[DiagnosticRow, ...]:
    return tuple(DiagnosticRow(d.code, d.severity.value, d.message, d.source_file, d.line, d.column,
                               d.object_ref) for d in result.diagnostics)


def query_dependency_rows(result: AnalysisResult) -> tuple[QueryDependencyRow, ...]:
    powerquery = result.context.powerquery
    if powerquery is None:
        return ()
    return tuple(QueryDependencyRow(row["Query"], row["Depends on query"], tuple(row["Via"]),
                                    row["Source file"]) for row in powerquery.dependencies)


def _selected(value, selection) -> bool:
    return selection is None or value in set(selection)


def filter_objects(rows: Iterable[ObjectRow], *, statuses: Iterable[Status] | None = None,
                   types: Iterable[ObjectType] | None = None, tables: Iterable[str] | None = None,
                   text: str = "", include_internal: bool = False,
                   exclude_keys: Iterable[str] = ()) -> tuple[ObjectRow, ...]:
    """Rows matching every selection; `text` is a case-insensitive table/name search.
    `exclude_keys` drops rows by key (e.g. acknowledged objects)."""
    statuses, types, tables = (None if s is None else tuple(s) for s in (statuses, types, tables))
    needle = text.strip().casefold()
    excluded = frozenset(exclude_keys)
    return tuple(row for row in rows
                 if row.key not in excluded and (include_internal or not row.internal)
                 and _selected(row.status, statuses) and _selected(row.object_type, types)
                 and _selected(row.table, tables)
                 and (not needle or needle in row.table.casefold() or needle in row.name.casefold()))


def filter_health(rows: Iterable[HealthRow], *, rule_ids: Iterable[str] | None = None,
                  severities: Iterable[HealthSeverity] | None = None,
                  categories: Iterable[str] | None = None, text: str = "",
                  exclude_keys: Iterable[str] = ()) -> tuple[HealthRow, ...]:
    """Rows matching every selection; `text` searches rule, scope and title.
    `exclude_keys` drops rows by key (e.g. acknowledged findings)."""
    rule_ids, severities, categories = (None if s is None else tuple(s) for s in (rule_ids, severities, categories))
    needle = text.strip().casefold()
    excluded = frozenset(exclude_keys)
    return tuple(row for row in rows
                 if row.key not in excluded and _selected(row.rule_id, rule_ids) and _selected(row.severity, severities)
                 and _selected(row.category, categories)
                 and (not needle or any(needle in value.casefold()
                                        for value in (row.rule_id, row.rule_name, row.scope,
                                                      row.scope_label, row.title))))


def unused_by_table(rows: Iterable[ObjectRow], object_type: ObjectType = ObjectType.COLUMN
                    ) -> tuple[tuple[str, int, int], ...]:
    """(table, Likely unused count, business total) for tables with candidates, most first."""
    business = [row for row in rows if row.object_type == object_type and not row.internal]
    totals = Counter(row.table for row in business)
    unused = Counter(row.table for row in business if row.status == Status.LIKELY_UNUSED)
    return tuple((table, count, totals[table]) for table, count in unused.most_common())
