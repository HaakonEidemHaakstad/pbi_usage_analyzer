from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


class ObjectType(str, Enum):
    TABLE = "Table"
    COLUMN = "Column"
    MEASURE = "Measure"
    HIERARCHY = "Hierarchy"
    QUERY = "Query"
    REPORT_FIELD = "ReportField"


class EvidenceType(str, Enum):
    DIRECT_REPORT_USE = "DIRECT_REPORT_USE"
    RAW_REPORT_REFERENCE = "RAW_REPORT_REFERENCE"
    DAX_DEPENDENCY = "DAX_DEPENDENCY"
    # Unqualified [Column] whose row-context table is not certain.
    DAX_UNQUALIFIED_COLUMN_REFERENCE = "DAX_UNQUALIFIED_COLUMN_REFERENCE"
    RELATIONSHIP_DEPENDENCY = "RELATIONSHIP_DEPENDENCY"
    HIERARCHY_DEPENDENCY = "HIERARCHY_DEPENDENCY"
    SORT_DEPENDENCY = "SORT_DEPENDENCY"
    FIELD_PARAMETER_DEPENDENCY = "FIELD_PARAMETER_DEPENDENCY"
    RLS_DEPENDENCY = "RLS_DEPENDENCY"
    CALCULATION_GROUP_DEPENDENCY = "CALCULATION_GROUP_DEPENDENCY"
    POWERQUERY_QUERY_DEPENDENCY = "POWERQUERY_QUERY_DEPENDENCY"
    POWERQUERY_COLUMN_DEPENDENCY = "POWERQUERY_COLUMN_DEPENDENCY"
    FALLBACK_MATCH = "FALLBACK_MATCH"
    INTERNAL_OBJECT = "INTERNAL_OBJECT"
    # Source that could not be parsed or decoded may hide evidence for its target.
    INCOMPLETE_SOURCE = "INCOMPLETE_SOURCE"


class Status(str, Enum):
    USED = "Used"
    MANUAL_REVIEW = "Needs manual review"
    LIKELY_UNUSED = "Likely unused"
    INTERNAL = "Internal / auto-generated"


@dataclass(frozen=True, order=True)
class ObjectRef:
    object_type: ObjectType
    table: str
    name: str = ""

    @property
    def label(self) -> str:
        if self.name:
            return f"{self.table}[{self.name}]"
        return self.table


@dataclass
class ModelObject:
    ref: ObjectRef
    source_file: str = ""
    hidden: bool = False
    calculated: bool = False
    source_column: str | None = None
    data_type: str | None = None
    expression: str = ""
    sort_by_column: str | None = None
    metadata: dict = field(default_factory=dict)
    description: str | None = None
    source_line: int | None = None


@dataclass(frozen=True)
class Evidence:
    source: ObjectRef | None
    target: ObjectRef
    evidence_type: EvidenceType
    reason: str
    source_file: str = ""
    confidence: str = "high"  # high | medium | low


@dataclass
class Finding:
    ref: ObjectRef
    status: Status
    reasons: list[str] = field(default_factory=list)
    evidence_types: list[str] = field(default_factory=list)


@dataclass
class ProjectPaths:
    project_name: str
    root: Path
    report_folder: Path
    model_folder: Path
    pbip_file: Path | None
    excel_output: Path
    text_output: Path


class DependencyGraph:
    def __init__(self) -> None:
        self.objects: dict[ObjectRef, ModelObject] = {}
        self.evidence: list[Evidence] = []
        self._incoming: dict[ObjectRef, list[Evidence]] = {}
        self._outgoing: dict[ObjectRef, list[Evidence]] = {}

    def add_object(self, obj: ModelObject) -> None:
        self.objects[obj.ref] = obj

    def add_objects(self, objects: Iterable[ModelObject]) -> None:
        for obj in objects:
            self.add_object(obj)

    def add_evidence(self, ev: Evidence) -> None:
        self.evidence.append(ev)
        self._incoming.setdefault(ev.target, []).append(ev)
        if ev.source is not None:
            self._outgoing.setdefault(ev.source, []).append(ev)

    def incoming(self, ref: ObjectRef) -> list[Evidence]:
        return list(self._incoming.get(ref, []))

    def outgoing(self, ref: ObjectRef) -> list[Evidence]:
        return list(self._outgoing.get(ref, []))

    def object(self, ref: ObjectRef) -> ModelObject | None:
        return self.objects.get(ref)
