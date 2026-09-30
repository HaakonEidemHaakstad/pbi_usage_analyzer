"""Structured diagnostics shared by parsers, graph construction and front ends."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import ObjectRef


class DiagnosticSeverity(str, Enum):
    WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    source_file: str = ""
    line: int | None = None
    column: int | None = None
    object_ref: ObjectRef | None = None


class DiagnosticCollection:
    @property
    def warnings(self) -> list[str]:
        """Compatibility view for report writers; diagnostics are the source of truth."""
        return [diagnostic.message for diagnostic in self.diagnostics
                if diagnostic.severity == DiagnosticSeverity.WARNING]
