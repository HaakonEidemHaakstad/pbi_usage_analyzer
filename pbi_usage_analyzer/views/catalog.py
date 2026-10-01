"""Display text for statuses, evidence types and health rules, shared by front ends.

Front ends key their state by `Status`, `EvidenceType` and rule IDs and take all
text from here, so the GUI and the reports use the same wording. English only;
the tables keep translation possible.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..health.engine import RULE_INFO, RuleInfo
from ..health.model import HealthSeverity
from ..model import EvidenceType, Status


@dataclass(frozen=True)
class StatusInfo:
    status: Status
    label: str
    summary: str
    explanation: str


LIKELY_UNUSED_CAVEAT = (
    "This is a cleanup candidate, not proof that deletion is safe: static analysis cannot see "
    "other reports on the same semantic model, external tools, or Power BI constructs the "
    "analyzer does not support. Remove a few objects at a time and validate in Power BI Desktop.")
STATUS_INFO = {info.status: info for info in (
    StatusInfo(
        Status.USED, "Used", "Proven use, directly or through dependencies.",
        "The report, a relationship, row-level security or a field parameter uses this object, "
        "or it is reached from such a use through DAX, hierarchies, sort-by or group-by columns, "
        "calculation groups or Power Query column lineage."),
    StatusInfo(
        Status.MANUAL_REVIEW, "Needs manual review", "Credible evidence of use, but not proven.",
        "Something suggests the object may be needed, for example an unresolved report reference, "
        "a Power Query dependency without column lineage, DAX in an object that is itself unused, "
        "or a column an M step requires by name. Active use could not be proven. Decide by hand; "
        "do not remove it as part of a bulk cleanup."),
    StatusInfo(
        Status.LIKELY_UNUSED, "Likely unused", "No known use or dependency was found.",
        "No supported parser or safety check found evidence that this object is used. "
        + LIKELY_UNUSED_CAVEAT),
    StatusInfo(
        Status.INTERNAL, "Internal / auto-generated", "Created by Power BI, not a cleanup candidate.",
        "Power BI creates these objects itself (auto date/time tables). They are listed for "
        "inspection and excluded from business totals and cleanup candidates."),
)}

# Short names, also used as step labels in evidence paths.
EVIDENCE_LABELS = {
    EvidenceType.DIRECT_REPORT_USE: "Report",
    EvidenceType.RAW_REPORT_REFERENCE: "Possible report reference",
    EvidenceType.DAX_DEPENDENCY: "DAX",
    EvidenceType.DAX_UNQUALIFIED_COLUMN_REFERENCE: "Unqualified DAX column",
    EvidenceType.RELATIONSHIP_DEPENDENCY: "Relationship",
    EvidenceType.HIERARCHY_DEPENDENCY: "Hierarchy",
    EvidenceType.SORT_DEPENDENCY: "Sort by",
    EvidenceType.GROUP_BY_DEPENDENCY: "Group by",
    EvidenceType.FIELD_PARAMETER_DEPENDENCY: "Field parameter",
    EvidenceType.RLS_DEPENDENCY: "Row-level security",
    EvidenceType.CALCULATION_GROUP_DEPENDENCY: "Calculation group",
    EvidenceType.POWERQUERY_QUERY_DEPENDENCY: "Power Query (query level)",
    EvidenceType.POWERQUERY_COLUMN_DEPENDENCY: "Power Query (required column)",
    EvidenceType.POWERQUERY_COLUMN_LINEAGE: "Power Query",
    EvidenceType.FALLBACK_MATCH: "Matched report reference",
    EvidenceType.INTERNAL_OBJECT: "Internal object",
    EvidenceType.INCOMPLETE_SOURCE: "Unreadable source",
}

CATEGORY_LABELS = {
    "relationships": "Relationships",
    "metadata": "Metadata",
    "dax": "DAX",
    "power_query": "Power Query",
}

SEVERITY_LABELS = {
    HealthSeverity.WARNING: "Warning",
    HealthSeverity.INFO: "Info",
}


def rule_info(rule_id: str) -> RuleInfo:
    return RULE_INFO[rule_id]


def category_label(category: str) -> str:
    """Known categories get their label; an unknown one is shown as written."""
    return CATEGORY_LABELS.get(category, category)
