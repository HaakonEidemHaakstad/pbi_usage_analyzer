from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ..diagnostics import Diagnostic, DiagnosticCollection, DiagnosticSeverity
from ..model import DependencyGraph, Evidence, EvidenceType, ModelObject, ObjectRef, ObjectType
from ..parsers.dax import dax_dependencies
from ..parsers.dax_lexer import mask_dax
from ..parsers.special_dax import special_dax_evidence
from ..parsers.pbir import ReportParseResult, parse_report
from ..parsers.powerquery import PowerQueryResult, parse_power_query_dependencies
from ..parsers.relationships import Relationship, parse_relationship_metadata, relationship_evidence
from ..parsers.tmdl import TmdlModel, parse_model
from ..util import is_internal_table, norm_key, read_source_text


class AnalysisContext(DiagnosticCollection):
    def __init__(self) -> None:
        self.graph = DependencyGraph()
        self.relationships: list[Relationship] = []
        self.tmdl: TmdlModel | None = None
        self.report: ReportParseResult | None = None
        self.powerquery: PowerQueryResult | None = None
        self.diagnostics: list[Diagnostic] = []


def build_graph(report_folder: Path, model_folder: Path) -> AnalysisContext:
    ctx = AnalysisContext()
    tmdl = parse_model(model_folder)
    ctx.tmdl = tmdl
    ctx.graph.add_objects(tmdl.objects)
    ctx.diagnostics.extend(tmdl.diagnostics)

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
            unterminated = mask_dax(obj.expression).unterminated
            if unterminated:
                ctx.diagnostics.append(Diagnostic(
                    "DAX_UNTERMINATED_LITERAL", DiagnosticSeverity.WARNING,
                    f"DAX expression for {ref.label} has an unterminated {unterminated}; "
                    "references after it were kept as dependency evidence.",
                    source_file=obj.source_file, object_ref=ref,
                ))
            for ev in dax_dependencies(ref, obj.expression, columns, measures):
                ctx.graph.add_evidence(ev)

    # Evidence hidden by unparseable or undecodable TMDL stays reviewable.
    for path in tmdl.failed_files:
        owner = ObjectRef(ObjectType.TABLE, path.stem)
        for ev in dax_dependencies(owner, read_source_text(path)[0], columns, measures):
            ctx.graph.add_evidence(Evidence(
                None, ev.target, EvidenceType.INCOMPLETE_SOURCE,
                f"Referenced in unparsed TMDL file {path.name}", str(path), "low"))
    for ref, obj in ctx.graph.objects.items():
        if ref.object_type in {ObjectType.COLUMN, ObjectType.MEASURE} and "\ufffd" in ref.table + ref.name:
            ctx.graph.add_evidence(Evidence(
                None, ref, EvidenceType.INCOMPLETE_SOURCE,
                "Name contains undecodable bytes; references to it cannot be matched",
                obj.source_file, "low"))

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
    ctx.relationships = parse_relationship_metadata(model_folder)
    for ev in relationship_evidence(ctx.relationships, columns):
        ctx.graph.add_evidence(ev)

    # Parse relevant declaration expressions before resolving special evidence.
    for path in sorted((model_folder / "definition").rglob("*.tmdl")):
        for evidence in special_dax_evidence(path, columns, measures):
            ctx.graph.add_evidence(evidence)

    report = parse_report(report_folder, columns, measures, hierarchies)
    ctx.report = report
    ctx.diagnostics.extend(report.diagnostics)
    for ev in report.evidence:
        ctx.graph.add_evidence(ev)

    pq = parse_power_query_dependencies(model_folder, table_names)
    ctx.powerquery = pq
    ctx.diagnostics.extend(pq.diagnostics)
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
                ctx.diagnostics.append(Diagnostic(
                    "AUTODATE_BACKING_COLUMN_UNRESOLVED", DiagnosticSeverity.WARNING,
                    f"Auto-date query {ev.source.table} references {upstream}, but its backing "
                    "column could not be resolved from M; inspect the query and relationships.",
                    source_file=ev.source_file, object_ref=ev.source,
                ))
            else:
                for name in sorted(selected):
                    # M selects source names, which may differ from model display names.
                    matches = [col for col in columns_by_table.get(upstream.casefold(), [])
                               if norm_key(upstream, ctx.graph.objects[col].source_column or col.name)
                               == norm_key(upstream, name)]
                    if not matches:
                        ctx.diagnostics.append(Diagnostic(
                            "AUTODATE_SOURCE_COLUMN_UNRESOLVED", DiagnosticSeverity.WARNING,
                            f"Unresolved auto-date source column: {upstream}[{name}]",
                            source_file=ev.source_file, object_ref=ev.source))
                    for col in matches:
                        ctx.graph.add_evidence(Evidence(
                            ev.source, col, EvidenceType.POWERQUERY_COLUMN_DEPENDENCY,
                            f"Auto-date query {ev.source.table} -> Table.SelectColumns -> {col.label}",
                            ev.source_file, "medium",
                        ))
            continue
        demand = pq.column_demands.get((ev.source.table, upstream)) if ev.source else None
        for col in columns_by_table.get(upstream.casefold(), []):
            if demand is not None:
                source_name = ctx.graph.objects[col].source_column or col.name
                if not demand.accepts(source_name):
                    continue
                ctx.graph.add_evidence(Evidence(
                    ev.source, col, EvidenceType.POWERQUERY_COLUMN_DEPENDENCY,
                    f"Query {ev.source.table} -> supported M lineage -> {col.label} "
                    "(output or required schema column)", ev.source_file, "medium",
                ))
            else:
                ctx.graph.add_evidence(Evidence(ev.source, col, EvidenceType.POWERQUERY_QUERY_DEPENDENCY, f"Upstream query '{upstream}' is referenced by '{ev.source.table if ev.source else ''}'", ev.source_file, "medium"))

    # Internal objects remain inspectable, separate from business cleanup candidates.
    for ref in ctx.graph.objects:
        if is_internal_table(ref.table):
            ctx.graph.add_evidence(Evidence(None, ref, EvidenceType.INTERNAL_OBJECT, "Power BI internal/auto-generated table", confidence="high"))

    return ctx
