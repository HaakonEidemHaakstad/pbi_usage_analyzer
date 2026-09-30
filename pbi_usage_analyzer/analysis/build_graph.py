from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ..model import DependencyGraph, Evidence, EvidenceType, ModelObject, ObjectRef, ObjectType
from ..parsers.dax import dax_dependencies
from ..parsers.pbir import ReportParseResult, parse_report
from ..parsers.powerquery import PowerQueryResult, parse_power_query_dependencies
from ..parsers.relationships import parse_relationships
from ..parsers.tmdl import TmdlModel, parse_model
from ..util import is_internal_table, norm_key


class AnalysisContext:
    def __init__(self) -> None:
        self.graph = DependencyGraph()
        self.tmdl: TmdlModel | None = None
        self.report: ReportParseResult | None = None
        self.powerquery: PowerQueryResult | None = None
        self.warnings: list[str] = []


def build_graph(report_folder: Path, model_folder: Path) -> AnalysisContext:
    ctx = AnalysisContext()
    tmdl = parse_model(model_folder)
    ctx.tmdl = tmdl
    ctx.graph.add_objects(tmdl.objects)
    ctx.warnings.extend(tmdl.warnings)

    columns: dict[tuple[str, str], ObjectRef] = {}
    measures: dict[tuple[str, str], ObjectRef] = {}
    hierarchies: dict[tuple[str, str], ObjectRef] = {}
    table_names: set[str] = set()
    query_objects: list[ModelObject] = []

    # Do not mutate graph.objects while iterating over it. Query objects are
    # collected first and added after the model-object pass.
    for ref, obj in list(ctx.graph.objects.items()):
        if ref.object_type == ObjectType.COLUMN:
            columns[norm_key(ref.table, ref.name)] = ref
        elif ref.object_type == ObjectType.MEASURE:
            measures[norm_key(ref.table, ref.name)] = ref
        elif ref.object_type == ObjectType.HIERARCHY:
            hierarchies[norm_key(ref.table, ref.name)] = ref
        elif ref.object_type == ObjectType.TABLE:
            table_names.add(ref.table)
            query_objects.append(
                ModelObject(
                    ref=ObjectRef(ObjectType.QUERY, ref.table),
                    source_file=obj.source_file,
                )
            )

    ctx.graph.add_objects(query_objects)

    # DAX edges.
    for ref, obj in list(ctx.graph.objects.items()):
        if ref.object_type in {ObjectType.COLUMN, ObjectType.MEASURE} and obj.expression:
            for ev in dax_dependencies(ref, obj.expression, columns, measures):
                ctx.graph.add_evidence(ev)

    # Hierarchy edges.
    for hierarchy, members in tmdl.hierarchies.items():
        for member in members:
            actual = columns.get(norm_key(member.table, member.name))
            if actual:
                ctx.graph.add_evidence(Evidence(hierarchy, actual, EvidenceType.HIERARCHY_DEPENDENCY, f"Hierarchy {hierarchy.label} uses {actual.label}", confidence="high"))

    # Sort-by edges.
    for ref, obj in list(ctx.graph.objects.items()):
        if ref.object_type == ObjectType.COLUMN and obj.sort_by_column:
            target = columns.get(norm_key(ref.table, obj.sort_by_column))
            if target:
                ctx.graph.add_evidence(Evidence(ref, target, EvidenceType.SORT_DEPENDENCY, f"SortByColumn for {ref.label}", obj.source_file, "high"))

    # Relationships.
    for ev in parse_relationships(model_folder, columns):
        ctx.graph.add_evidence(ev)

    # Field parameters / NAMEOF, roles/RLS, calculation groups: scan only relevant TMDL areas,
    # but mark as explicit evidence when a valid DAX reference is resolvable.
    for path in (model_folder / "definition").rglob("*.tmdl"):
        text = path.read_text(encoding="utf-8")
        lower = text.casefold()
        special_types: list[EvidenceType] = []
        if "nameof(" in lower:
            special_types.append(EvidenceType.FIELD_PARAMETER_DEPENDENCY)
        if "calculationgroup" in lower or "calculation group" in lower:
            special_types.append(EvidenceType.CALCULATION_GROUP_DEPENDENCY)
        if "role " in lower or "roles" in path.parts:
            special_types.append(EvidenceType.RLS_DEPENDENCY)
        if special_types:
            fake_owner = ObjectRef(ObjectType.TABLE, f"Special:{path.name}")
            for ev in dax_dependencies(fake_owner, text, columns, measures):
                for et in special_types:
                    ctx.graph.add_evidence(Evidence(fake_owner, ev.target, et, f"Referenced by {et.value} in {path.name}", str(path), "medium"))

    report = parse_report(report_folder, columns, measures, hierarchies)
    ctx.report = report
    ctx.warnings.extend(report.warnings)
    for ev in report.evidence:
        ctx.graph.add_evidence(ev)

    pq = parse_power_query_dependencies(model_folder, table_names)
    ctx.powerquery = pq
    ctx.warnings.extend(pq.warnings)
    for ev in pq.evidence:
        ctx.graph.add_evidence(ev)

    # Query-level dependencies conservatively protect the upstream table's columns from
    # deletion recommendations, but only as manual-review evidence. This is deliberately
    # weaker than proven column-level M lineage.
    columns_by_table: dict[str, list[ObjectRef]] = defaultdict(list)
    for ref in ctx.graph.objects:
        if ref.object_type == ObjectType.COLUMN:
            columns_by_table[ref.table.casefold()].append(ref)
    for ev in pq.evidence:
        upstream = ev.target.table
        if ev.source and is_internal_table(ev.source.table):
            selected = pq.projected_columns.get((ev.source.table, upstream))
            if selected is None:
                ctx.warnings.append(
                    f"Auto-date query {ev.source.table} references {upstream}, but its backing "
                    "column could not be resolved from M; inspect the query and relationships."
                )
            else:
                for name in sorted(selected):
                    # M selects source names, which may differ from model display names.
                    matches = [col for col in columns_by_table.get(upstream.casefold(), [])
                               if norm_key(upstream, ctx.graph.objects[col].source_column or col.name)
                               == norm_key(upstream, name)]
                    if not matches:
                        ctx.warnings.append(f"Unresolved auto-date source column: {upstream}[{name}]")
                    for col in matches:
                        ctx.graph.add_evidence(Evidence(
                            ev.source, col, EvidenceType.POWERQUERY_COLUMN_DEPENDENCY,
                            f"Auto-date query {ev.source.table} -> Table.SelectColumns -> {col.label}",
                            ev.source_file, "medium",
                        ))
            continue
        for col in columns_by_table.get(upstream.casefold(), []):
            ctx.graph.add_evidence(Evidence(ev.source, col, EvidenceType.POWERQUERY_QUERY_DEPENDENCY, f"Upstream query '{upstream}' is referenced by '{ev.source.table if ev.source else ''}'", ev.source_file, "medium"))

    # Internal objects remain inspectable, separate from business cleanup candidates.
    for ref in ctx.graph.objects:
        if is_internal_table(ref.table):
            ctx.graph.add_evidence(Evidence(None, ref, EvidenceType.INTERNAL_OBJECT, "Power BI internal/auto-generated table", confidence="high"))

    return ctx
