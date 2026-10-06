"""Model changes the analyzer can make, and their validation against an analysis.

Only metadata operations are offered (tier 1): they cannot change what the model
computes or which objects exist. Removing objects, renaming, relationships and
Power Query stay with the user in Power BI Desktop.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..api import AnalysisResult
from ..model import EvidenceType, ObjectRef, ObjectType, Status
from ..util import is_internal_table, norm
from .tmdl_edit import EditError, TmdlDocument, normalize_description, read_properties

MAX_OPERATIONS = 50
MAX_DESCRIPTION = 2000


class OperationKind(str, Enum):
    SET_DESCRIPTION = "set_description"
    SET_DISPLAY_FOLDER = "set_display_folder"
    SET_FORMAT_STRING = "set_format_string"
    SET_HIDDEN = "set_hidden"


@dataclass(frozen=True)
class OperationInfo:
    label: str
    object_types: tuple[ObjectType, ...]
    value_type: type


OPERATION_INFO = {
    OperationKind.SET_DESCRIPTION: OperationInfo(
        "Set description", (ObjectType.TABLE, ObjectType.COLUMN, ObjectType.MEASURE), str),
    OperationKind.SET_DISPLAY_FOLDER: OperationInfo(
        "Set display folder", (ObjectType.COLUMN, ObjectType.MEASURE), str),
    OperationKind.SET_FORMAT_STRING: OperationInfo(
        "Set format string", (ObjectType.COLUMN, ObjectType.MEASURE), str),
    OperationKind.SET_HIDDEN: OperationInfo(
        "Hide or show", (ObjectType.COLUMN, ObjectType.MEASURE), bool),
}


class IssueSeverity(str, Enum):
    ERROR = "error"      # the batch is refused
    WARNING = "warning"  # shown; the operation still runs
    SKIPPED = "skipped"  # nothing to do (value already set)


@dataclass(frozen=True)
class PlanIssue:
    code: str
    severity: IssueSeverity
    message: str
    index: int | None = None  # operation number (0-based), None for the whole batch


@dataclass(frozen=True)
class Operation:
    kind: OperationKind
    target: str  # Table[Name], or Table for a table description
    value: str | bool
    object_type: ObjectType | None = None

    def describe(self) -> str:
        value = self.value
        if self.kind == OperationKind.SET_HIDDEN:
            return f"{'Hide' if value else 'Show'} {self.target}"
        if self.kind == OperationKind.SET_DISPLAY_FOLDER and not value:
            return f"Remove the display folder of {self.target}"
        shown = str(value) if len(str(value)) <= 60 else str(value)[:57] + "..."
        return f"{OPERATION_INFO[self.kind].label} of {self.target} to {shown!r}"

    def to_dict(self) -> dict:
        data = {"op": self.kind.value, "object": self.target, "value": self.value}
        if self.object_type is not None:
            data["object_type"] = self.object_type.value.lower()
        return data


@dataclass(frozen=True)
class ResolvedOperation:
    operation: Operation
    ref: ObjectRef
    file: Path
    value: str | bool | None  # normalized value to write (None removes the property)


_TYPES = {"table": ObjectType.TABLE, "column": ObjectType.COLUMN, "measure": ObjectType.MEASURE}


def parse_operations(raw) -> tuple[tuple[Operation, ...], tuple[PlanIssue, ...]]:
    """Operations from plain data (`{"op", "object", "value", "object_type"?}`)."""
    if not isinstance(raw, list) or not raw:
        return (), (PlanIssue("NO_OPERATIONS", IssueSeverity.ERROR, "Give at least one operation."),)
    if len(raw) > MAX_OPERATIONS:
        return (), (PlanIssue("TOO_MANY_OPERATIONS", IssueSeverity.ERROR,
                              f"{len(raw)} operations; at most {MAX_OPERATIONS} per batch. Split the change "
                              "into smaller batches by theme."),)
    operations, issues = [], []
    kinds = ", ".join(kind.value for kind in OperationKind)
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            issues.append(PlanIssue("OPERATION_MALFORMED", IssueSeverity.ERROR, "Each operation must be an object.",
                                    index))
            continue
        unknown = set(item) - {"op", "object", "value", "object_type"}
        if unknown:
            issues.append(PlanIssue("OPERATION_MALFORMED", IssueSeverity.ERROR,
                                    f"Unknown field(s): {', '.join(sorted(unknown))}.", index))
            continue
        try:
            kind = OperationKind(item.get("op"))
        except ValueError:
            issues.append(PlanIssue("OPERATION_UNKNOWN", IssueSeverity.ERROR,
                                    f"Unknown op {item.get('op')!r}; supported: {kinds}.", index))
            continue
        target, value = item.get("object"), item.get("value")
        object_type = item.get("object_type")
        if not isinstance(target, str) or not target.strip():
            issues.append(PlanIssue("OPERATION_MALFORMED", IssueSeverity.ERROR,
                                    "'object' must name a Table[Name] (or a table).", index))
            continue
        expected = OPERATION_INFO[kind].value_type
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            issues.append(PlanIssue("VALUE_INVALID", IssueSeverity.ERROR,
                                    f"{kind.value} needs a {'true/false' if expected is bool else 'text'} value.",
                                    index))
            continue
        if object_type is not None and object_type not in _TYPES:
            issues.append(PlanIssue("OPERATION_MALFORMED", IssueSeverity.ERROR,
                                    "'object_type' must be table, column or measure.", index))
            continue
        operations.append(Operation(kind, target.strip(), value, _TYPES.get(object_type)))
    return tuple(operations), tuple(issues)


def _split_target(text: str) -> tuple[str, str]:
    text = text.strip()
    if text.endswith("]") and "[" in text:
        cut = text.rindex("[")
        return text[:cut].strip().strip("'").replace("''", "'"), text[cut + 1:-1].replace("]]", "]")
    return text.strip("'").replace("''", "'"), ""


def _value_issue(kind: OperationKind, value) -> tuple[str | bool | None, str | None]:
    """Normalized value, or a reason why it is not acceptable."""
    if kind == OperationKind.SET_HIDDEN:
        return value, None
    if any(ord(c) < 32 and c not in "\n\t" for c in value) or "\t" in value:
        return None, "the value contains control characters"
    if kind == OperationKind.SET_DESCRIPTION:
        text = normalize_description(value)
        if not text:
            return None, "the description is empty"
        if len(text) > MAX_DESCRIPTION:
            return None, f"the description is longer than {MAX_DESCRIPTION} characters"
        return text, None
    if "\n" in value:
        return None, "the value must be a single line"
    text = value.strip()
    if kind == OperationKind.SET_FORMAT_STRING and not text:
        return None, "the format string is empty"
    if kind == OperationKind.SET_DISPLAY_FOLDER:
        return (text or None), None
    return text, None


def resolve_operations(result: AnalysisResult, operations) -> tuple[tuple[ResolvedOperation, ...],
                                                                     tuple[PlanIssue, ...]]:
    """Check every operation against the analysis and the current files.

    Errors refuse the batch. Operations whose value is already set are reported as
    skipped and left out of the returned list.
    """
    objects = result.graph.objects
    status = {finding.ref: finding.status for finding in result.findings}
    labels = sorted({ref.label for ref in objects if ref.object_type in _TYPES.values()})
    resolved, issues, seen = [], [], set()
    for index, op in enumerate(operations):
        info = OPERATION_INFO[op.kind]
        table, name = _split_target(op.target)
        wanted = (op.object_type,) if op.object_type else (
            (ObjectType.TABLE,) if not name else (ObjectType.COLUMN, ObjectType.MEASURE))
        matches = [ref for ref in objects if ref.object_type in wanted and norm(ref.table) == norm(table)
                   and norm(ref.name) == norm(name)]
        if not matches:
            close = difflib.get_close_matches(op.target, labels, n=5, cutoff=0.5)
            hint = f" Similar names: {', '.join(close)}." if close else ""
            issues.append(PlanIssue("OBJECT_NOT_FOUND", IssueSeverity.ERROR,
                                    f"No {'table' if not name else 'column or measure'} named {op.target!r}.{hint}",
                                    index))
            continue
        if len(matches) > 1:
            issues.append(PlanIssue("OBJECT_AMBIGUOUS", IssueSeverity.ERROR,
                                    f"{op.target} is both a column and a measure; give object_type.", index))
            continue
        ref = matches[0]
        if ref.object_type not in info.object_types:
            allowed = ", ".join(t.value.lower() for t in info.object_types)
            issues.append(PlanIssue("OBJECT_TYPE_NOT_ALLOWED", IssueSeverity.ERROR,
                                    f"{op.kind.value} applies to {allowed} objects, not to the "
                                    f"{ref.object_type.value.lower()} {ref.label}.", index))
            continue
        if is_internal_table(ref.table) or status.get(ref) == Status.INTERNAL:
            issues.append(PlanIssue("OBJECT_INTERNAL", IssueSeverity.ERROR,
                                    f"{ref.label} is generated by Power BI (auto date/time) and is not edited.",
                                    index))
            continue
        key = (op.kind, ref)
        if key in seen:
            issues.append(PlanIssue("OPERATION_DUPLICATE", IssueSeverity.ERROR,
                                    f"{op.kind.value} for {ref.label} appears twice in this batch.", index))
            continue
        seen.add(key)
        value, problem = _value_issue(op.kind, op.value)
        if problem:
            issues.append(PlanIssue("VALUE_INVALID", IssueSeverity.ERROR, f"{op.describe()}: {problem}.", index))
            continue
        obj = objects[ref]
        file = Path(obj.source_file)
        try:
            current = read_properties(TmdlDocument.decode(file.read_bytes()), ref)
        except (OSError, EditError) as exc:
            issues.append(PlanIssue(getattr(exc, "code", "FILE_UNREADABLE"), IssueSeverity.ERROR,
                                    f"{ref.label} in {file.name}: {exc}", index))
            continue
        if op.kind == OperationKind.SET_FORMAT_STRING and current.dynamic_format:
            issues.append(PlanIssue("TMDL_LAYOUT_UNSUPPORTED", IssueSeverity.ERROR,
                                    f"{ref.label} has a dynamic format string; change it in Power BI Desktop.",
                                    index))
            continue
        before = {OperationKind.SET_DESCRIPTION: current.description,
                  OperationKind.SET_DISPLAY_FOLDER: current.display_folder,
                  OperationKind.SET_FORMAT_STRING: current.format_string,
                  OperationKind.SET_HIDDEN: current.hidden}[op.kind]
        if before == value:
            issues.append(PlanIssue("ALREADY_SET", IssueSeverity.SKIPPED, f"{op.describe()}: already set.", index))
            continue
        if op.kind == OperationKind.SET_FORMAT_STRING and ref.object_type == ObjectType.COLUMN \
                and obj.data_type == "string":
            issues.append(PlanIssue("FORMAT_ON_TEXT", IssueSeverity.WARNING,
                                    f"{ref.label} is a text column; a format string has no visible effect.", index))
        if op.kind == OperationKind.SET_HIDDEN and op.value and any(
                ev.evidence_type == EvidenceType.DIRECT_REPORT_USE for ev in result.graph.incoming(ref)):
            issues.append(PlanIssue("HIDING_REPORT_FIELD", IssueSeverity.WARNING,
                                    f"{ref.label} is used in report visuals. They keep working, but report "
                                    "authors no longer see it in the field list.", index))
        resolved.append(ResolvedOperation(op, ref, file, value))
    return tuple(resolved), tuple(issues)
