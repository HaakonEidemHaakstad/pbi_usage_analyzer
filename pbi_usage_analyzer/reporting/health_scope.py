"""Common display labels for recorded health-filter scope."""
from ..health.filtering import HealthFilterScope


def health_scope_rows(scope: HealthFilterScope | None) -> list[tuple[str, str | int]]:
    if scope is None:
        return [("Health filter scope", "Not recorded")]

    def label(values):
        if values is None:
            return "All"
        return ", ".join(values) if values else "None (empty selection)"

    return [("Health rule filter", label(scope.rule_ids)),
            ("Health severity filter", label(scope.severities)),
            ("Health findings before filtering", scope.total_findings),
            ("Health findings included", scope.selected_findings)]
