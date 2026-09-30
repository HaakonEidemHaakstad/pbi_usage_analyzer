"""Public, presentation-independent project analysis entry point."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analysis.build_graph import AnalysisContext, build_graph
from .analysis.classify import classify
from .health.engine import evaluate_health
from .health.filtering import HealthFilterScope, filter_health_findings, normalize_health_filters
from .health.model import HealthFinding
from .discovery import discover_project
from .diagnostics import Diagnostic, DiagnosticSeverity
from .model import DependencyGraph, Finding, ModelObject, ObjectType, ProjectPaths, Status


@dataclass(frozen=True)
class ObjectCounts:
    used: int
    manual_review: int
    likely_unused: int
    internal: int

    @property
    def business_total(self) -> int:
        return self.used + self.manual_review + self.likely_unused


@dataclass(frozen=True)
class AnalysisSummary:
    columns: ObjectCounts
    measures: ObjectCounts
    query_dependencies: int


@dataclass(frozen=True)
class AnalysisResult:
    project: ProjectPaths
    findings: list[Finding]
    diagnostics: tuple[Diagnostic, ...]
    summary: AnalysisSummary
    context: AnalysisContext
    health_findings: tuple[HealthFinding, ...]
    health_filter_scope: HealthFilterScope

    @property
    def graph(self) -> DependencyGraph:
        return self.context.graph

    @property
    def objects(self) -> tuple[ModelObject, ...]:
        return tuple(self.graph.objects.values())


def analyze_project(path: str | Path, *, health_rule_ids=None, health_severities=None) -> AnalysisResult:
    """Analyze a project folder without console output or report-file writes.

    Discovery and fatal input errors propagate to the caller. Recoverable parser
    warnings are returned as diagnostics. Graph and finding objects are owned by
    this invocation; the result is not a deeply immutable snapshot.
    """
    health_rule_ids, health_severities = normalize_health_filters(health_rule_ids, health_severities)
    project = discover_project(Path(path))
    context = build_graph(project.report_folder, project.model_folder)
    findings = classify(context.graph)

    def counts(kind: ObjectType) -> ObjectCounts:
        statuses = [finding.status for finding in findings if finding.ref.object_type == kind]
        return ObjectCounts(
            used=statuses.count(Status.USED),
            manual_review=statuses.count(Status.MANUAL_REVIEW),
            likely_unused=statuses.count(Status.LIKELY_UNUSED),
            internal=statuses.count(Status.INTERNAL),
        )

    diagnostics = tuple(context.diagnostics)
    summary = AnalysisSummary(
        columns=counts(ObjectType.COLUMN),
        measures=counts(ObjectType.MEASURE),
        query_dependencies=len(context.powerquery.dependencies) if context.powerquery else 0,
    )
    all_health = evaluate_health(context.relationships, context.graph.objects.values())
    selected_health = filter_health_findings(
        all_health, rule_ids=health_rule_ids, severities=health_severities)
    scope = HealthFilterScope(
        rule_ids=None if health_rule_ids is None else tuple(sorted(health_rule_ids)),
        severities=None if health_severities is None else tuple(sorted(health_severities)),
        total_findings=len(all_health), selected_findings=len(selected_health),
    )
    return AnalysisResult(project, findings, diagnostics, summary, context, selected_health, scope)
