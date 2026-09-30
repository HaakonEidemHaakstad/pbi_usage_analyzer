"""Reusable health finding selection, independent of analysis and rendering."""
from collections.abc import Iterable
from dataclasses import dataclass

from .engine import RULES
from .model import HealthFinding, HealthSeverity


@dataclass(frozen=True)
class HealthFilterScope:
    rule_ids: tuple[str, ...] | None
    severities: tuple[str, ...] | None
    total_findings: int
    selected_findings: int


def normalize_health_filters(rule_ids=None, severities=None):
    """None is unrestricted; an empty selection matches nothing."""
    def selection(values, allowed, label):
        if values is None:
            return None
        if isinstance(values, str):
            values = (values,)
        selected = frozenset(values)
        unknown = selected - allowed
        if unknown:
            raise ValueError(f"Unknown health {label}: {', '.join(sorted(map(str, unknown)))}")
        return selected

    return (selection(rule_ids, {rule_id for rule_id, _, _ in RULES}, "rule ID"),
            selection(severities, {severity.value for severity in HealthSeverity}, "severity"))


def filter_health_findings(
    findings: Iterable[HealthFinding], *, rule_ids=None, severities=None,
) -> tuple[HealthFinding, ...]:
    """Select exact IDs/severities with AND between filters, preserving order."""
    rule_ids, severities = normalize_health_filters(rule_ids, severities)
    return tuple(finding for finding in findings
                 if (rule_ids is None or finding.rule_id in rule_ids)
                 and (severities is None or finding.severity in severities))
