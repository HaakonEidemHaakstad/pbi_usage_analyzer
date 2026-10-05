"""Deterministic text briefing of one analysis for an AI assistant.

The briefing is built only from an `AnalysisResult` (plus, optionally, the
previous run and the user's acknowledgements) through the `views` layer, so it
cannot disagree with the reports or the GUI. The same input gives byte-identical
text: no timestamps except the previous run's own, and source files relative to
the project root.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..api import AnalysisResult, ObjectCounts
from ..health.model import HealthSeverity
from ..model import ObjectType, Status
from ..util import is_internal_table
from ..views.catalog import CATEGORY_LABELS, CHANGE_LABELS, SEVERITY_LABELS, STATUS_INFO, rule_info
from ..views.explain import Explainer, review_reason
from ..views.history import Acknowledgement, RunSnapshot, snapshot
from ..views.rows import ObjectRow, diagnostic_rows, health_rows, object_rows, query_dependency_rows, \
    relationship_labels
from ..views.assessment import EFFECT_LABELS, AttemptAssessment, RunCounts, assess_attempt

BRIEFING_FORMAT = 1


@dataclass(frozen=True)
class BriefingSection:
    key: str  # stable identifier, e.g. "health"
    title: str
    body: str


@dataclass(frozen=True)
class Briefing:
    project_name: str
    sections: tuple[BriefingSection, ...]
    # Set when the briefing was built with a previous run.
    assessment: AttemptAssessment | None = None

    def section(self, key: str) -> BriefingSection | None:
        return next((section for section in self.sections if section.key == key), None)

    def text(self) -> str:
        parts = [f"# Analysis briefing: {self.project_name}", f"Briefing format {BRIEFING_FORMAT}."]
        for section in self.sections:
            parts.append(f"## {section.title}\n\n{section.body}")
        return "\n\n".join(parts) + "\n"


def _relative(path: str, root: Path) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def _location(path: str, line: int | None, root: Path) -> str:
    relative = _relative(path, root)
    return f"{relative}:{line}" if relative and line else relative


def _counts_line(name: str, counts: ObjectCounts) -> str:
    return (f"- {name}: {counts.business_total} business objects: {counts.used} Used, "
            f"{counts.manual_review} Needs manual review, {counts.likely_unused} Likely unused "
            f"({counts.internal} internal objects excluded).")


def _object_label(row: ObjectRow) -> str:
    flags = [row.object_type.value.lower()]
    if row.calculated and row.object_type == ObjectType.COLUMN:
        flags.append("calculated")
    if row.hidden:
        flags.append("hidden")
    if row.data_type:
        flags.append(row.data_type)
    return f"{row.ref.label} ({', '.join(flags)})"


def _project(result: AnalysisResult, rows: tuple[ObjectRow, ...]) -> BriefingSection:
    business_tables = sorted({row.table for row in rows if not row.internal})
    internal_tables = sorted({row.table for row in rows if row.internal or is_internal_table(row.table)}
                             - set(business_tables))
    queries = Counter(query.kind.value for query in result.context.m_queries)
    health = Counter(finding.severity for finding in result.health_findings)
    scope = result.health_filter_scope
    lines = [
        f"- Project: {result.project.project_name}",
        f"- Analyzer version: {_version()}",
        f"- Tables: {len(business_tables)} business tables, {len(internal_tables)} internal auto-date tables.",
        _counts_line("Columns", result.summary.columns),
        _counts_line("Measures", result.summary.measures),
        f"- Relationships: {len(result.context.relationships)}.",
        f"- Power Query: {queries['partition']} loaded queries (partitions), {queries['expression']} "
        f"load-disabled shared queries, {queries['parameter']} parameters; "
        f"{result.summary.query_dependencies} query dependencies.",
        f"- Model-health findings: {len(result.health_findings)} "
        f"({health[HealthSeverity.WARNING]} warnings, {health[HealthSeverity.INFO]} info).",
        f"- Diagnostics (parser warnings that limit coverage): {len(result.diagnostics)}.",
    ]
    if scope.rule_ids is not None or scope.severities is not None:
        lines.append(f"- Note: a health filter was applied; {scope.selected_findings} of {scope.total_findings} "
                     "findings are included. Do not conclude that unlisted rules found nothing.")
    return BriefingSection("project", "Project", "\n".join(lines))


def _version() -> str:
    from .. import __version__
    return __version__


def _cleanup(rows: tuple[ObjectRow, ...]) -> BriefingSection:
    # Status counts are in the project section; status meanings in the system prompt.
    unused = Counter(row.table for row in rows if row.status == Status.LIKELY_UNUSED)
    totals = Counter(row.table for row in rows if not row.internal)
    if not unused:
        return BriefingSection("cleanup", "Cleanup candidates per table", "No Likely unused objects.")
    lines = ["Likely unused objects per table (columns and measures, of the table's business objects):"]
    lines += [f"- {table}: {count} of {totals[table]}" for table, count in
              sorted(unused.items(), key=lambda item: (-item[1], item[0].casefold()))]
    return BriefingSection("cleanup", "Cleanup candidates per table", "\n".join(lines))


def _health(result: AnalysisResult) -> BriefingSection:
    root = result.project.root
    by_rule = defaultdict(list)
    for row in health_rows(result):
        by_rule[row.rule_id].append(row)
    if not by_rule:
        return BriefingSection("health", "Model-health findings",
                               "No model-health rule reported anything for the included rules.")
    blocks = []
    for rule_id, rule_rows in by_rule.items():
        info = rule_info(rule_id)
        shared_explanation = len({row.explanation for row in rule_rows}) == 1
        shared_recommendation = len({row.recommendation for row in rule_rows}) == 1
        lines = [f"### {SEVERITY_LABELS[info.severity]}: {info.name} ({rule_id}), "
                 f"category {CATEGORY_LABELS.get(info.category, info.category)}, {len(rule_rows)} finding(s)",
                 f"Rule: {info.summary}"]
        if shared_explanation:
            lines.append(f"Explanation: {rule_rows[0].explanation}")
        if shared_recommendation:
            lines.append(f"Recommendation: {rule_rows[0].recommendation}")
        for row in rule_rows:
            lines.append(f"- Scope: {row.scope_label}")
            lines.append(f"  Title: {row.title}")
            lines.append(f"  Confidence: {row.confidence}")
            location = _location(row.source_file, row.line, root)
            if location:
                lines.append(f"  Location: {location}")
            if not shared_explanation:
                lines.append(f"  Explanation: {row.explanation}")
            if row.evidence:
                lines.append("  Evidence:")
                lines += [f"    - {item}" for item in row.evidence]
            if not shared_recommendation:
                lines.append(f"  Recommendation: {row.recommendation}")
        blocks.append("\n".join(lines))
    return BriefingSection("health", "Model-health findings", "\n\n".join(blocks))


def _by_table(rows: Iterable[ObjectRow]) -> dict[str, list[ObjectRow]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.table].append(row)
    return dict(sorted(grouped.items(), key=lambda item: item[0].casefold()))


def _likely_unused(rows: tuple[ObjectRow, ...]) -> BriefingSection:
    candidates = _by_table(row for row in rows if row.status == Status.LIKELY_UNUSED)
    if not candidates:
        return BriefingSection("likely_unused", "Likely unused objects", "None.")
    lines = []
    for table, table_rows in candidates.items():
        lines.append(f"{table}:")
        lines += [f"- {_object_label(row)}" for row in table_rows]
    return BriefingSection("likely_unused", "Likely unused objects", "\n".join(lines))


def _manual_review(result: AnalysisResult, rows: tuple[ObjectRow, ...]) -> BriefingSection:
    findings = {finding.ref: finding for finding in result.findings}
    review = [row for row in rows if row.status == Status.MANUAL_REVIEW]
    if not review:
        return BriefingSection("manual_review", "Objects needing manual review", "None.")
    explainer = Explainer(result.graph, result.findings)
    lines = [f"- {_object_label(row)}: {review_reason(explainer, findings[row.ref])}" for row in review]
    return BriefingSection("manual_review", "Objects needing manual review", "\n".join(lines))


def _diagnostics(result: AnalysisResult) -> BriefingSection:
    root = result.project.root
    rows = diagnostic_rows(result)
    if not rows:
        return BriefingSection("diagnostics", "Diagnostics", "None.")
    lines = []
    for row in rows:
        location = _location(row.source_file, row.line, root)
        lines.append(f"- {row.code} ({row.severity}){' at ' + location if location else ''}: {row.message}")
    return BriefingSection("diagnostics", "Diagnostics", "\n".join(lines))


def _structure(result: AnalysisResult, rows: tuple[ObjectRow, ...]) -> BriefingSection:
    lines = ["Tables (business objects; Used / Needs manual review / Likely unused):"]
    for table, table_rows in _by_table(row for row in rows if not row.internal).items():
        parts = []
        for kind, name in ((ObjectType.COLUMN, "columns"), (ObjectType.MEASURE, "measures")):
            of_kind = [row for row in table_rows if row.object_type == kind]
            if of_kind:
                statuses = Counter(row.status for row in of_kind)
                parts.append(f"{len(of_kind)} {name} ({statuses[Status.USED]} / {statuses[Status.MANUAL_REVIEW]}"
                             f" / {statuses[Status.LIKELY_UNUSED]})")
        lines.append(f"- {table}: {', '.join(parts)}")

    labels = relationship_labels(result.context.relationships)
    internal = [relationship for relationship in result.context.relationships
                if any(end and is_internal_table(end[0]) for end in (relationship.from_column, relationship.to_column))]
    business = [relationship for relationship in result.context.relationships if relationship not in internal]
    lines += ["", "Relationships:"]
    if not business:
        lines.append("- None between business tables.")
    for relationship in business:
        label = labels.get(relationship.name, f"{relationship.name} (endpoints not parsed)")
        lines.append(
            f"- {label}: from {relationship.from_cardinality or 'many (default)'} to "
            f"{relationship.to_cardinality or 'one (default)'}, cross-filter "
            f"{relationship.cross_filtering_behavior or 'oneDirection (default)'}, active "
            f"{relationship.is_active or 'true (default)'}")
    if internal:
        lines.append(f"- Plus {len(internal)} relationship(s) to internal auto-date tables, which Power BI creates "
                     "for date columns while Auto date/time is on.")

    lines += ["", "Power Query queries:"]
    if not result.context.m_queries:
        lines.append("- None.")
    lines += [f"- {query.name} ({query.kind.value})" for query in result.context.m_queries]
    dependencies = query_dependency_rows(result)
    if dependencies:
        lines += ["", "Query dependencies:"]
        for row in dependencies:
            via = f" (through load-disabled {', '.join(row.via)})" if row.via else ""
            lines.append(f"- {row.query} reads {row.depends_on}{via}")
    return BriefingSection("structure", "Model structure", "\n".join(lines))


def _expressions(result: AnalysisResult) -> BriefingSection:
    blocks = []
    objects = sorted((obj for obj in result.objects
                      if obj.expression and obj.ref.object_type in (ObjectType.MEASURE, ObjectType.COLUMN)
                      and not is_internal_table(obj.ref.table)),
                     key=lambda obj: (obj.ref.object_type != ObjectType.MEASURE, obj.ref.table.casefold(),
                                      obj.ref.name.casefold()))
    for obj in objects:
        kind = "Measure" if obj.ref.object_type == ObjectType.MEASURE else "Calculated column"
        blocks.append(f"### {kind} {obj.ref.label}\n```dax\n{obj.expression.strip()}\n```")
    for query in result.context.m_queries:
        if is_internal_table(query.name):
            continue
        blocks.append(f"### M query {query.name} ({query.kind.value})\n```m\n{query.source.strip()}\n```")
    return BriefingSection("expressions", "Expressions", "\n\n".join(blocks) if blocks else "None.")


def _acknowledged(acknowledgements: Iterable[Acknowledgement]) -> BriefingSection:
    lines = ["The user has reviewed these items (object keys are `Type|Table|Name`; finding keys are "
             "`RULE_ID|scope|file`). Treat them as decided; do not raise them as new problems."]
    for item in acknowledgements:
        note = f": {item.note}" if item.note else ""
        lines.append(f"- {item.key} (acknowledged {item.acknowledged_at}){note}")
    return BriefingSection("acknowledged", "Acknowledged by the user", "\n".join(lines))


def _counts_change(before: RunCounts, after: RunCounts) -> list[str]:
    lines = []
    for name, old, new in (("Columns", before.columns, after.columns), ("Measures", before.measures, after.measures)):
        parts = [f"{STATUS_INFO[status].label} {old[status]} -> {new[status]}"
                 for status in (Status.USED, Status.MANUAL_REVIEW, Status.LIKELY_UNUSED)]
        lines.append(f"- {name}: {', '.join(parts)}")
    lines.append(f"- Model-health findings: {before.findings} -> {after.findings}")
    for rule_id in sorted(before.findings_by_rule.keys() | after.findings_by_rule.keys()):
        old, new = before.findings_by_rule.get(rule_id, 0), after.findings_by_rule.get(rule_id, 0)
        if old != new:
            lines.append(f"  - {rule_id}: {old} -> {new}")
    return lines


def _changes(assessment: AttemptAssessment) -> BriefingSection:
    lines = [f"Previous analysis: {assessment.before_analyzed_at}.", "", "Counts before -> after:"]
    lines += _counts_change(assessment.before, assessment.after)
    lines += ["", "Changes with the analyzer's deterministic assessment, most serious first:"]
    if not assessment.changes:
        lines.append("- No changes.")
    for item in assessment.changes:
        change = item.change
        values = " -> ".join(value for value in (change.before, change.after) if value)
        lines.append(f"- [{EFFECT_LABELS[item.effect]}] {CHANGE_LABELS[change.kind.value]}: {change.label}"
                     f"{' (' + values + ')' if values else ''}. {item.note}")
        if change.before_path:
            lines.append(f"  Before: {change.before_path}")
        if change.after_path:
            lines.append(f"  After: {change.after_path}")
    return BriefingSection("changes", "Changes since the previous analysis", "\n".join(lines))


def build_briefing(result: AnalysisResult, *, previous: RunSnapshot | None = None,
                   acknowledgements: Iterable[Acknowledgement] | None = None,
                   include_expressions: bool = True) -> Briefing:
    """Briefing of `result`; with `previous`, also the changes and their assessment."""
    rows = object_rows(result)
    sections = [_project(result, rows), _cleanup(rows), _health(result), _likely_unused(rows),
                _manual_review(result, rows), _diagnostics(result), _structure(result, rows)]
    if include_expressions:
        sections.append(_expressions(result))
    acknowledged = sorted(acknowledgements or (), key=lambda item: item.key)
    if acknowledged:
        sections.append(_acknowledged(acknowledged))
    assessment = None
    if previous is not None:
        assessment = assess_attempt(previous, snapshot(result))
        sections.append(_changes(assessment))
    return Briefing(result.project.project_name, tuple(sections), assessment)
