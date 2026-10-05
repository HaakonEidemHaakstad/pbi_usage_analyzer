"""UI-agnostic presentation model over `AnalysisResult` (labels, evidence paths, rows).

Shared by the reports and future front ends; contains no analysis and no GUI code.
"""
from .catalog import (CATEGORY_LABELS, CHANGE_LABELS, EVIDENCE_LABELS, LIKELY_UNUSED_CAVEAT, SEVERITY_LABELS,
                      STATUS_INFO, StatusInfo, category_label, rule_info)
from .assessment import (EFFECT_LABELS, EFFECT_SUMMARIES, AssessedChange, AttemptAssessment, Effect, RunCounts,
                         assess_attempt, effect_summary, run_counts)
from .explain import Explainer, Explanation, format_path, review_reason
from .history import (Acknowledgement, Change, ChangeKind, ProjectState, RunSnapshot, compare_runs,
                      snapshot)
from .rows import (DiagnosticRow, HealthRow, ObjectRow, QueryDependencyRow, diagnostic_rows,
                   filter_health, filter_objects, health_key, health_rows, object_key, object_rows,
                   query_dependency_rows, relationship_labels, unused_by_table)

__all__ = [
    "CATEGORY_LABELS", "CHANGE_LABELS", "EVIDENCE_LABELS", "LIKELY_UNUSED_CAVEAT", "SEVERITY_LABELS", "STATUS_INFO",
    "StatusInfo", "category_label", "rule_info",
    "EFFECT_LABELS", "EFFECT_SUMMARIES", "AssessedChange", "AttemptAssessment", "Effect", "RunCounts",
    "assess_attempt", "effect_summary", "run_counts",
    "Explainer", "Explanation", "format_path", "review_reason",
    "Acknowledgement", "Change", "ChangeKind", "ProjectState", "RunSnapshot", "compare_runs", "snapshot",
    "DiagnosticRow", "HealthRow", "ObjectRow", "QueryDependencyRow", "diagnostic_rows",
    "filter_health", "filter_objects", "health_key", "health_rows", "object_key", "object_rows",
    "query_dependency_rows", "relationship_labels", "unused_by_table",
]
