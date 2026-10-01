from dataclasses import dataclass
from enum import Enum

from ..model import ObjectRef


class HealthSeverity(str, Enum):
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class HealthFinding:
    rule_id: str
    category: str
    severity: HealthSeverity
    confidence: str
    scope: str
    title: str
    explanation: str
    evidence: tuple[str, ...]
    recommendation: str
    source_file: str
    line: int
    # The model object the finding is about (measure, column, loaded query), when
    # there is one. Relationship findings have none. Not in JSON schema v1.
    object_ref: ObjectRef | None = None
