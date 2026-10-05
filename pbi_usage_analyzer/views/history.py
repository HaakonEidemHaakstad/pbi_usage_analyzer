"""Run comparison and acknowledgements, keyed by the stable object/finding keys.

A `RunSnapshot` keeps what is needed to explain a change later (status and
evidence path per object, title and scope per health finding). `ProjectState`
holds the last snapshot and the user's acknowledgements and round-trips through
a small versioned JSON document; where it is stored is the front end's choice.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..api import AnalysisResult
from ..model import Status
from .catalog import STATUS_INFO
from .explain import Explainer, format_path
from .rows import health_rows, object_key

STATE_FORMAT = 1


@dataclass(frozen=True)
class ObjectState:
    label: str
    status: Status
    path: str  # evidence path at the time (use or lineage-review path), may be empty


@dataclass(frozen=True)
class FindingState:
    rule_id: str
    scope_label: str
    title: str


@dataclass(frozen=True)
class RunSnapshot:
    analyzed_at: str  # ISO 8601, local time
    analyzer_version: str
    objects: dict[str, ObjectState]
    findings: dict[str, FindingState]


def state_file(data_dir: Path, project_root: Path, kind: str = "projects") -> Path:
    """Per-user state file of one project, outside the project folder: `projects`
    for the GUI's review state, `assistant` for the assistant's saved baseline."""
    identity = os.path.normcase(str(project_root.resolve()))
    return data_dir / kind / (hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24] + ".json")


def snapshot(result: AnalysisResult, analyzed_at: datetime | None = None) -> RunSnapshot:
    from .. import __version__

    explainer = Explainer(result.graph, result.findings)
    objects = {}
    for finding in result.findings:
        explanation = explainer.explain(finding.ref)
        objects[object_key(finding.ref)] = ObjectState(
            finding.ref.label, finding.status, format_path(explanation.use_path or explanation.review_path))
    findings = {row.key: FindingState(row.rule_id, row.scope_label, row.title) for row in health_rows(result)}
    stamp = (analyzed_at or datetime.now()).isoformat(timespec="seconds")
    return RunSnapshot(stamp, __version__, objects, findings)


class ChangeKind(str, Enum):
    STATUS_CHANGED = "status_changed"
    OBJECT_ADDED = "object_added"
    OBJECT_REMOVED = "object_removed"
    FINDING_ADDED = "finding_added"
    FINDING_RESOLVED = "finding_resolved"


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    key: str
    label: str
    before: str  # status label or finding title; empty when absent
    after: str
    before_path: str = ""
    after_path: str = ""


def compare_runs(before: RunSnapshot, after: RunSnapshot) -> tuple[Change, ...]:
    """Every difference between two runs: status changes, added/removed objects,
    new and resolved health findings. Ordered by kind, then label."""
    changes = []
    for key in before.objects.keys() | after.objects.keys():
        old, new = before.objects.get(key), after.objects.get(key)
        if old is None:
            changes.append(Change(ChangeKind.OBJECT_ADDED, key, new.label, "", STATUS_INFO[new.status].label,
                                  "", new.path))
        elif new is None:
            changes.append(Change(ChangeKind.OBJECT_REMOVED, key, old.label, STATUS_INFO[old.status].label, "",
                                  old.path, ""))
        elif old.status != new.status:
            changes.append(Change(ChangeKind.STATUS_CHANGED, key, new.label, STATUS_INFO[old.status].label,
                                  STATUS_INFO[new.status].label, old.path, new.path))
    for key in before.findings.keys() | after.findings.keys():
        old, new = before.findings.get(key), after.findings.get(key)
        if old is None:
            changes.append(Change(ChangeKind.FINDING_ADDED, key, new.scope_label, "", new.title))
        elif new is None:
            changes.append(Change(ChangeKind.FINDING_RESOLVED, key, old.scope_label, old.title, ""))
    order = list(ChangeKind)
    return tuple(sorted(changes, key=lambda c: (order.index(c.kind), c.label.casefold(), c.key)))


@dataclass(frozen=True)
class Acknowledgement:
    key: str
    note: str
    acknowledged_at: str  # ISO 8601 date


@dataclass
class ProjectState:
    """Per-project, per-user state: acknowledgements and the last run."""
    project_root: str
    acknowledgements: dict[str, Acknowledgement] = field(default_factory=dict)
    last_run: RunSnapshot | None = None

    def acknowledge(self, key: str, note: str = "", when: datetime | None = None) -> Acknowledgement:
        item = Acknowledgement(key, note.strip(), (when or datetime.now()).date().isoformat())
        self.acknowledgements[key] = item
        return item

    def unacknowledge(self, key: str) -> None:
        self.acknowledgements.pop(key, None)

    def stale_acknowledgements(self, current_keys) -> tuple[Acknowledgement, ...]:
        """Acknowledgements whose object or finding no longer exists."""
        keys = set(current_keys)
        return tuple(item for key, item in sorted(self.acknowledgements.items()) if key not in keys)

    def to_dict(self) -> dict:
        run = None
        if self.last_run is not None:
            run = {
                "analyzed_at": self.last_run.analyzed_at,
                "analyzer_version": self.last_run.analyzer_version,
                "objects": {k: {"label": v.label, "status": v.status.name, "path": v.path}
                            for k, v in sorted(self.last_run.objects.items())},
                "findings": {k: {"rule_id": v.rule_id, "scope_label": v.scope_label, "title": v.title}
                             for k, v in sorted(self.last_run.findings.items())},
            }
        return {
            "format": STATE_FORMAT,
            "project_root": self.project_root,
            "acknowledgements": {k: {"note": v.note, "acknowledged_at": v.acknowledged_at}
                                 for k, v in sorted(self.acknowledgements.items())},
            "last_run": run,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectState":
        """Raise ValueError for an unknown format or malformed content."""
        try:
            if data.get("format") != STATE_FORMAT:
                raise ValueError(f"unsupported state format {data.get('format')!r}")
            run = None
            if data.get("last_run"):
                raw = data["last_run"]
                run = RunSnapshot(
                    raw["analyzed_at"], raw["analyzer_version"],
                    {k: ObjectState(v["label"], Status[v["status"]], v["path"]) for k, v in raw["objects"].items()},
                    {k: FindingState(v["rule_id"], v["scope_label"], v["title"]) for k, v in raw["findings"].items()},
                )
            acknowledgements = {k: Acknowledgement(k, v["note"], v["acknowledged_at"])
                                for k, v in data["acknowledgements"].items()}
            return cls(data["project_root"], acknowledgements, run)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"malformed project state: {exc!r}") from exc

    @classmethod
    def load(cls, path: Path, project_root: str) -> "ProjectState":
        """Empty state when the file does not exist; ValueError when it is unreadable."""
        if not path.exists():
            return cls(project_root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"malformed project state in {path}")
        return cls.from_dict(data)

    def save(self, path: Path) -> None:
        """Write atomically (temporary file, then replace)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(path)
