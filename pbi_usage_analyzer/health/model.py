from dataclasses import dataclass
from enum import Enum


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
