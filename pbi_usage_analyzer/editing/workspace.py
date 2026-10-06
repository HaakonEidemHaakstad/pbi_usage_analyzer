"""Working copies: the only place the analyzer writes model changes.

Procedure (docs/AI_ASSISTANT_DESIGN.md section 16):

1. `create_working_copy` copies the project (its .pbip file, semantic model and
   report folders) next to the original and records the original's analysis as the
   baseline. The original is never written.
2. `preview_changes` validates a batch of operations and tries it on a temporary
   copy: file diffs, read-back of every value and a re-analysis. Nothing is written.
3. `apply_changes` repeats the trial, writes the batch to the working copy with
   backups, re-analyzes the copy and restores the backups automatically when a check
   fails. Every operation is metadata only, so the only acceptable analysis change
   is a resolved model-health finding.
4. `undo_last_change` restores the last batch's backups.
5. `review_working_copy` compares the copy with the baseline and lists what the user
   must still check in Power BI Desktop, which the static analysis cannot.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..api import AnalysisResult, analyze_project
from ..views.assessment import AttemptAssessment, assess_attempt
from ..views.history import ChangeKind, ProjectState, RunSnapshot, snapshot
from .operations import (IssueSeverity, Operation, OperationKind, PlanIssue, ResolvedOperation, parse_operations,
                         resolve_operations)
from .tmdl_edit import EditError, TmdlDocument, read_properties, set_description, set_hidden, set_property

WORKSPACE_DIR = ".pbi-model-health"
WORKSPACE_FILE = "workspace.json"
WORKSPACE_FORMAT = 1


class WorkspaceError(Exception):
    """The request cannot be carried out (not a working copy, nothing to undo, ...)."""


@dataclass
class Batch:
    number: int
    applied_at: str
    note: str
    operations: tuple[dict, ...]
    files: dict[str, str]  # relative path -> SHA-256 after the batch
    undone: bool = False


@dataclass
class Workspace:
    root: Path
    original: str
    created_at: str
    baseline: RunSnapshot
    state_hashes: dict[str, str]  # model and report files as the analyzer last left them
    batches: list[Batch] = field(default_factory=list)

    @property
    def active_batches(self) -> list[Batch]:
        return [batch for batch in self.batches if not batch.undone]

    def to_dict(self) -> dict:
        return {
            "format": WORKSPACE_FORMAT,
            "original": self.original,
            "created_at": self.created_at,
            "baseline": ProjectState(self.original, last_run=self.baseline).to_dict()["last_run"],
            "state_hashes": dict(sorted(self.state_hashes.items())),
            "batches": [{"number": b.number, "applied_at": b.applied_at, "note": b.note,
                         "operations": list(b.operations), "files": dict(sorted(b.files.items())),
                         "undone": b.undone} for b in self.batches],
        }

    def save(self) -> None:
        path = self.root / WORKSPACE_DIR / WORKSPACE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=1).encode("utf-8"))


@dataclass(frozen=True)
class FileDiff:
    path: str  # relative to the project root, with /
    diff: str


@dataclass(frozen=True)
class ReadBack:
    operation: Operation
    expected: str | bool | None
    actual: str | bool | None

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


@dataclass(frozen=True)
class Check:
    """Deterministic verification of a batch against the analysis before it."""
    problems: tuple[str, ...]
    readback: tuple[ReadBack, ...]
    assessment: AttemptAssessment

    @property
    def passed(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class ChangeOutcome:
    issues: tuple[PlanIssue, ...]
    operations: tuple[ResolvedOperation, ...] = ()
    diffs: tuple[FileDiff, ...] = ()
    check: Check | None = None
    applied: bool = False      # written to the working copy and kept
    rolled_back: bool = False  # written, failed the check on disk, backups restored
    batch: Batch | None = None
    outside_changes: tuple[str, ...] = ()

    @property
    def refused(self) -> bool:
        return any(issue.severity == IssueSeverity.ERROR for issue in self.issues)


@dataclass(frozen=True)
class WorkspaceReview:
    workspace: Workspace
    assessment: AttemptAssessment
    outside_changes: tuple[str, ...]
    checklist: tuple[str, ...]


# -- files ------------------------------------------------------------------


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".pbimh-tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _project_files(result: AnalysisResult) -> dict[str, str]:
    """Hashes of the model and report definition files (Power BI's caches excluded)."""
    root = result.project.root
    hashes = {}
    for folder in (result.project.model_folder, result.project.report_folder):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and ".pbi" not in path.relative_to(folder).parts:
                hashes[_relative(path, root)] = _sha(path.read_bytes())
    return hashes


def _copy_project(result: AnalysisResult, target: Path, *, with_caches: bool) -> None:
    ignore = None if with_caches else shutil.ignore_patterns(".pbi")
    target.mkdir(parents=True, exist_ok=True)
    for folder in (result.project.model_folder, result.project.report_folder):
        shutil.copytree(folder, target / folder.name, ignore=ignore, copy_function=shutil.copyfile)
    if result.project.pbip_file is not None:
        shutil.copyfile(result.project.pbip_file, target / result.project.pbip_file.name)


def _analyze(path: Path) -> AnalysisResult:
    try:
        return analyze_project(path)
    except Exception as exc:  # fatal input problems are reported, not raised through the front end
        raise WorkspaceError(f"Cannot analyze {path}: {exc}") from exc


# -- working copies -----------------------------------------------------------


def workspace_marker(path: Path) -> Path:
    return path / WORKSPACE_DIR / WORKSPACE_FILE


def create_working_copy(project_path: str | Path, target: str | Path | None = None,
                        now: datetime | None = None) -> Workspace:
    """Copy the project next to the original (or to `target`, which must not exist)."""
    result = _analyze(Path(project_path))
    root = result.project.root
    moment = now or datetime.now()
    if target is None:
        stem = f"{root.name} (proposed {moment:%Y-%m-%d %H%M}"
        target = root.parent / f"{stem})"
        number = 2
        while target.exists():
            target, number = root.parent / f"{stem} {number})", number + 1
    target = Path(target).expanduser().resolve()
    if target.exists():
        raise WorkspaceError(f"{target} already exists; choose a new folder for the working copy.")
    if target == root or root in target.parents:
        raise WorkspaceError("The working copy must be outside the original project folder.")
    _copy_project(result, target, with_caches=True)
    copied = _analyze(target)
    workspace = Workspace(target, str(root), moment.isoformat(timespec="seconds"), snapshot(result, moment),
                          _project_files(copied))
    workspace.save()
    return workspace


def open_workspace(path: str | Path) -> Workspace:
    root = Path(str(path).strip().strip('"')).expanduser()
    if root.is_file() and root.suffix.casefold() == ".pbip":
        root = root.parent
    root = root.resolve()
    marker = workspace_marker(root)
    if not marker.exists():
        raise WorkspaceError(
            f"{root} is not a working copy made by the analyzer. Changes are only applied to working copies; "
            "create one with create_working_copy first.")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if data.get("format") != WORKSPACE_FORMAT:
            raise ValueError(f"unsupported format {data.get('format')!r}")
        baseline = ProjectState.from_dict({"format": 1, "project_root": data["original"], "acknowledgements": {},
                                           "last_run": data["baseline"]}).last_run
        batches = [Batch(b["number"], b["applied_at"], b["note"], tuple(b["operations"]), dict(b["files"]),
                         bool(b["undone"])) for b in data["batches"]]
        workspace = Workspace(root, data["original"], data["created_at"], baseline, dict(data["state_hashes"]),
                              batches)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(f"Cannot read the working-copy record {marker}: {exc}") from exc
    if os.path.normcase(str(Path(workspace.original).resolve())) == os.path.normcase(str(root)):
        raise WorkspaceError("The working-copy record points at this folder as its own original; refusing.")
    return workspace


def _outside_changes(workspace: Workspace, result: AnalysisResult) -> tuple[str, ...]:
    current = _project_files(result)
    keys = workspace.state_hashes.keys() | current.keys()
    return tuple(sorted(k for k in keys if workspace.state_hashes.get(k) != current.get(k)))


# -- trial and checks ----------------------------------------------------------


def _edit(document: TmdlDocument, item: ResolvedOperation) -> TmdlDocument:
    kind, ref, value = item.operation.kind, item.ref, item.value
    if kind == OperationKind.SET_DESCRIPTION:
        return set_description(document, ref, value)
    if kind == OperationKind.SET_DISPLAY_FOLDER:
        return set_property(document, ref, "displayFolder", value)
    if kind == OperationKind.SET_FORMAT_STRING:
        return set_property(document, ref, "formatString", value)
    return set_hidden(document, ref, bool(value))


NOT_FOUND = "(object not found in the file)"


def _actual(document: TmdlDocument, item: ResolvedOperation):
    try:
        props = read_properties(document, item.ref)
    except EditError:
        return NOT_FOUND
    return {OperationKind.SET_DESCRIPTION: props.description,
            OperationKind.SET_DISPLAY_FOLDER: props.display_folder,
            OperationKind.SET_FORMAT_STRING: props.format_string,
            OperationKind.SET_HIDDEN: props.hidden}[item.operation.kind]


def _render(result: AnalysisResult, resolved) -> tuple[dict[Path, tuple[bytes, bytes]], tuple[ReadBack, ...],
                                                       tuple[PlanIssue, ...]]:
    """New content per file (old bytes, new bytes) and the read-back of every operation."""
    root = result.project.root.resolve()
    documents: dict[Path, tuple[bytes, TmdlDocument]] = {}
    issues = []
    for index, item in enumerate(resolved):
        path = item.file.resolve()
        if root not in path.parents:
            issues.append(PlanIssue("FILE_OUTSIDE_PROJECT", IssueSeverity.ERROR,
                                    f"{item.ref.label} is defined outside the project folder.", index))
            continue
        try:
            if path not in documents:
                data = path.read_bytes()
                documents[path] = (data, TmdlDocument.decode(data))
            old, document = documents[path]
            documents[path] = (old, _edit(document, item))
        except (OSError, EditError) as exc:
            issues.append(PlanIssue(getattr(exc, "code", "FILE_UNREADABLE"), IssueSeverity.ERROR,
                                    f"{item.operation.describe()}: {exc}", index))
    readback = []
    if not issues:
        for item in resolved:
            readback.append(ReadBack(item.operation, item.value, _actual(documents[item.file.resolve()][1], item)))
    files = {path: (old, document.encode()) for path, (old, document) in documents.items()}
    return files, tuple(readback), tuple(issues)


def _diffs(root: Path, files: dict[Path, tuple[bytes, bytes]]) -> tuple[FileDiff, ...]:
    diffs = []
    for path, (old, new) in sorted(files.items()):
        name = _relative(path, root)
        before = TmdlDocument.decode(old).lines
        after = TmdlDocument.decode(new).lines
        text = "\n".join(difflib.unified_diff(before, after, f"a/{name}", f"b/{name}", lineterm="", n=2))
        diffs.append(FileDiff(name, text))
    return tuple(diffs)


def _diagnostic_counts(result: AnalysisResult) -> Counter:
    root = result.project.root.resolve()
    counts = Counter()
    for diagnostic in result.diagnostics:
        try:
            source = _relative(Path(diagnostic.source_file), root) if diagnostic.source_file else ""
        except ValueError:
            source = Path(diagnostic.source_file).name
        counts[(diagnostic.code, source)] += 1
    return counts


def _check(before: AnalysisResult, after: AnalysisResult, readback: tuple[ReadBack, ...]) -> Check:
    problems = []
    for item in readback:
        if not item.ok:
            problems.append(f"{item.operation.describe()}: the file reads back {item.actual!r}, "
                            f"not {item.expected!r}.")
    lost = set(before.graph.objects) - set(after.graph.objects)
    gained = set(after.graph.objects) - set(before.graph.objects)
    for ref in sorted(lost):
        problems.append(f"{ref.label} is no longer found by the analyzer.")
    for ref in sorted(gained):
        problems.append(f"{ref.label} appeared unexpectedly.")
    old, new = _diagnostic_counts(before), _diagnostic_counts(after)
    for key in sorted(new.keys()):
        if new[key] > old.get(key, 0):
            problems.append(f"New analyzer diagnostic {key[0]} in {key[1] or 'the project'}.")
    assessment = assess_attempt(snapshot(before), snapshot(after))
    for item in assessment.changes:
        if item.change.kind != ChangeKind.FINDING_RESOLVED:
            change = item.change
            problems.append(f"Unexpected analysis change ({item.effect.value}): {change.kind.value} "
                            f"{change.label} {change.before!r} -> {change.after!r}. Metadata changes should only "
                            "resolve model-health findings.")
    return Check(tuple(problems), readback, assessment)


def _trial(result: AnalysisResult, raw_operations):
    """Validate and try a batch on a temporary copy; nothing in the project is written."""
    operations, issues = parse_operations(raw_operations)
    if any(issue.severity == IssueSeverity.ERROR for issue in issues):
        return ChangeOutcome(issues), {}
    resolved, more = resolve_operations(result, operations)
    issues = tuple(sorted(issues + more, key=lambda i: (i.index is None, i.index or 0)))
    if any(issue.severity == IssueSeverity.ERROR for issue in issues):
        return ChangeOutcome(issues, resolved), {}
    if not resolved:
        return ChangeOutcome(issues), {}
    files, readback, edit_issues = _render(result, resolved)
    issues += edit_issues
    if edit_issues:
        return ChangeOutcome(issues, resolved), {}
    root = result.project.root
    with tempfile.TemporaryDirectory(prefix="pbimh-trial-") as tmp:
        trial_root = Path(tmp) / root.name
        _copy_project(result, trial_root, with_caches=False)
        for path, (_, new) in files.items():
            (trial_root / _relative(path, root)).write_bytes(new)
        check = _check(result, _analyze(trial_root), readback)
    return ChangeOutcome(issues, resolved, _diffs(root, files), check), files


def preview_changes(project_path: str | Path, raw_operations) -> ChangeOutcome:
    """Validate and try a batch of operations without writing to the project."""
    result = _analyze(Path(project_path))
    return _trial(result, raw_operations)[0]


def apply_changes(workspace_path: str | Path, raw_operations, note: str = "",
                  now: datetime | None = None) -> ChangeOutcome:
    """Apply a batch to a working copy; restore it automatically if a check fails."""
    workspace = open_workspace(workspace_path)
    before = _analyze(workspace.root)
    outside = _outside_changes(workspace, before)
    outcome, files = _trial(before, raw_operations)
    outcome = ChangeOutcome(outcome.issues, outcome.operations, outcome.diffs, outcome.check,
                            outside_changes=outside)
    if outcome.refused or not files or outcome.check is None or not outcome.check.passed:
        return outcome
    number = max((batch.number for batch in workspace.batches), default=0) + 1
    backup = workspace.root / WORKSPACE_DIR / "batches" / str(number)
    if backup.exists():
        shutil.rmtree(backup)
    for path, (old, _) in files.items():
        saved = backup / _relative(path, workspace.root)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(old)
    for path, (_, new) in files.items():
        _write_atomic(path, new)
    after = _analyze(workspace.root)
    readback = tuple(ReadBack(item.operation, item.value,
                              _actual(TmdlDocument.decode(item.file.read_bytes()), item))
                     for item in outcome.operations)
    check = _check(before, after, readback)
    if not check.passed:
        for path, (old, _) in files.items():
            _write_atomic(path, old)
        shutil.rmtree(backup)
        return ChangeOutcome(outcome.issues, outcome.operations, outcome.diffs, check, rolled_back=True,
                             outside_changes=outside)
    batch = Batch(number, (now or datetime.now()).isoformat(timespec="seconds"), note.strip(),
                  tuple(item.operation.to_dict() for item in outcome.operations),
                  {_relative(path, workspace.root): _sha(new) for path, (_, new) in files.items()})
    workspace.batches.append(batch)
    workspace.state_hashes = _project_files(after)
    workspace.save()
    return ChangeOutcome(outcome.issues, outcome.operations, outcome.diffs, check, applied=True, batch=batch,
                         outside_changes=outside)


def undo_last_change(workspace_path: str | Path) -> Batch:
    """Restore the files of the last applied batch from its backups."""
    workspace = open_workspace(workspace_path)
    if not workspace.active_batches:
        raise WorkspaceError("No applied change to undo in this working copy.")
    batch = workspace.active_batches[-1]
    backup = workspace.root / WORKSPACE_DIR / "batches" / str(batch.number)
    changed = []
    for name, sha in batch.files.items():
        path = workspace.root / name
        if not path.exists() or _sha(path.read_bytes()) != sha:
            changed.append(name)
    if changed:
        raise WorkspaceError(
            f"Cannot undo change {batch.number}: {', '.join(changed)} changed after it was applied (for example "
            "saved by Power BI Desktop). Undo it in Power BI Desktop instead, or make a new working copy.")
    for name in batch.files:
        _write_atomic(workspace.root / name, (backup / name).read_bytes())
    batch.undone = True
    workspace.state_hashes = _project_files(_analyze(workspace.root))
    workspace.save()
    return batch


def review_working_copy(workspace_path: str | Path) -> WorkspaceReview:
    workspace = open_workspace(workspace_path)
    result = _analyze(workspace.root)
    assessment = assess_attempt(workspace.baseline, snapshot(result))
    return WorkspaceReview(workspace, assessment, _outside_changes(workspace, result),
                           desktop_checklist(workspace, result))


def desktop_checklist(workspace: Workspace, result: AnalysisResult) -> tuple[str, ...]:
    """What only Power BI Desktop can confirm, for the operations applied so far."""
    kinds = {OperationKind(op["op"]) for batch in workspace.active_batches for op in batch.operations}
    pbip = result.project.pbip_file.name if result.project.pbip_file else "the .pbip file"
    steps = [f"Close Power BI Desktop if the working copy is open in it, then open {pbip} in {workspace.root}.",
             "Refresh the data (Home > Refresh) and confirm it finishes without errors."]
    if OperationKind.SET_DESCRIPTION in kinds:
        steps.append("Hover over the changed tables, columns and measures in the Data pane: the descriptions "
                     "should read correctly.")
    if OperationKind.SET_HIDDEN in kinds:
        steps.append("Check the Data pane: hidden fields are gone, shown fields are back, and visuals that use a "
                     "hidden field still show data.")
    if OperationKind.SET_DISPLAY_FOLDER in kinds:
        steps.append("Check that the display folders in the Data pane group the fields as intended.")
    if OperationKind.SET_FORMAT_STRING in kinds:
        steps.append("Check the number and date formats in visuals that show the changed fields.")
    steps += ["Open every report page and look for visuals showing errors.",
              "Save in Power BI Desktop, then review the working copy again: Power BI rewrites the files when it "
              "saves, and the review confirms nothing was lost.",
              f"When satisfied, use the working copy as the project (publish from it) and keep the original "
              f"{workspace.original} as a backup until the published model has been checked."]
    return tuple(steps)
