"""The analyzer's MCP tools and prompts, built on `pbi_usage_analyzer.assistant`.

Every call analyzes the project afresh (well under a second on real projects), so
answers always reflect the files as saved in Power BI Desktop. State: the
per-project baseline written by `save_baseline`, stored with the user's other
analyzer state, and working copies. The change tools (`pbi_usage_analyzer.editing`)
write only to a working copy the analyzer created next to the project, never to the
original.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from pbi_usage_analyzer import AnalysisResult, analyze_project
from pbi_usage_analyzer.assistant import SYSTEM_PROMPT, Briefing, Task, build_briefing, build_prompt
from pbi_usage_analyzer.editing import (MAX_OPERATIONS, ChangeOutcome, OperationKind, WorkspaceError, apply_changes,
                                        create_working_copy, preview_changes, review_working_copy, undo_last_change)
from pbi_usage_analyzer.model import ObjectRef, ObjectType, Status
from pbi_usage_analyzer.util import norm
from pbi_usage_analyzer.views import (EFFECT_LABELS, EVIDENCE_LABELS, STATUS_INFO, Explainer, ProjectState,
                                      format_path, health_rows, review_reason, snapshot)
from pbi_usage_analyzer.views.history import state_file

from .protocol import PromptArgument, PromptTemplate, Tool, ToolError

# Same location as the desktop app's per-user data (QStandardPaths.AppDataLocation
# for organization "pbi-usage-analyzer" and the app name), so acknowledgements made
# in the app reach the assistant.
ORGANIZATION = "pbi-usage-analyzer"
APPLICATION = "Power BI Model Health Analyzer"

SECTION_KEYS = ("project", "cleanup", "health", "likely_unused", "manual_review", "diagnostics", "structure",
                "expressions", "acknowledged")

INSTRUCTIONS = SYSTEM_PROMPT + """

How to use this server's tools:
- analyze_model reads a Power BI project (a PBIP folder or .pbip file) and returns the \
analyzer's briefing between <analysis> tags. Start here. Ask for the path if you do not \
have it. For a large model, request only the sections you need.
- explain_object explains one column or measure (Table[Name]), or lists a table's \
objects: status, evidence path, properties, DAX and related findings.
- To evaluate changes: call save_baseline before the user edits the model, then \
compare_with_baseline after they have saved it in Power BI Desktop. The comparison \
contains the analyzer's deterministic assessment of every change.
- Changing the model: the tools can set descriptions, display folders and format \
strings, and hide or show columns and measures, only in a working copy. Procedure: \
create_working_copy once; for each small batch of one theme, preview_changes, then \
apply_changes with the same operations (it re-checks the batch, re-analyzes the copy and \
rolls back automatically if anything else changed); undo_last_change if the user wants a \
batch reverted; finally review_working_copy and give the user its Power BI Desktop \
checklist. Agree each batch with the user before applying it unless they have said \
otherwise. Descriptions must follow from the DAX, M or data in the analysis, not from \
guesses. Removing or renaming objects, relationships, Power Query and DAX changes are \
advice for the user to carry out in Power BI Desktop; the tools cannot make them.
- The original project is never written. Changes become real only when the user opens \
the working copy in Power BI Desktop, checks it and adopts it."""

_PATH = {"type": "string",
         "description": "Full path of the Power BI project folder (containing the .pbip file) or of the .pbip file."}
_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_WORKING_COPY = {"type": "string", "description": "Folder of a working copy made by create_working_copy."}
_OPERATIONS = {
    "type": "array", "minItems": 1, "maxItems": MAX_OPERATIONS,
    "description": "Metadata changes, applied together as one batch.",
    "items": {"type": "object", "properties": {
        "op": {"type": "string", "enum": [kind.value for kind in OperationKind],
               "description": "set_description (table, column, measure), set_display_folder and "
                              "set_format_string (column, measure; an empty folder removes it), set_hidden "
                              "(column, measure; value true or false)."},
        "object": {"type": "string", "description": "Table[Name], or a table name for a table description."},
        "object_type": {"type": "string", "enum": ["table", "column", "measure"],
                        "description": "Only when a column and a measure share the name."},
        "value": {"type": ["string", "boolean"], "description": "The new value (true/false for set_hidden)."}},
        "required": ["op", "object", "value"], "additionalProperties": False}}


def default_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / ORGANIZATION / APPLICATION


def _wrap(text: str) -> str:
    return f"<analysis>\n{text.rstrip()}\n</analysis>"


def _assessment_lines(changes) -> list[str]:
    return [f"- {EFFECT_LABELS[item.effect]}: {item.change.label}: "
            f"{item.change.before or '(none)'} -> {item.change.after or '(none)'}. {item.note}" for item in changes]


def _outcome_text(outcome: ChangeOutcome, *, preview: bool) -> str:
    check = outcome.check
    if outcome.refused:
        head = "Refused: nothing was written. Fix the errors below and try again."
    elif not outcome.operations:
        head = "Nothing to do: every value is already set. Nothing was written."
    elif outcome.rolled_back:
        head = ("Rolled back: the change was written, but the check on the working copy failed, so the files "
                "were restored. Nothing changed.")
    elif check is not None and not check.passed:
        head = "Checks failed on a trial copy, so nothing was written."
    elif preview:
        head = ("Preview only, nothing was written. All checks passed on a trial copy; apply_changes with the "
                "same operations would make exactly these changes.")
    else:
        head = (f"Applied as change {outcome.batch.number} to the working copy. All checks passed; "
                "undo_last_change reverts it.")
    lines = [head]
    if outcome.outside_changes:
        lines.append("Note: files changed outside the analyzer since its last change (for example saved by Power "
                     f"BI Desktop): {', '.join(outcome.outside_changes)}. If Power BI Desktop has the working copy "
                     "open, ask the user to close it: its next save would overwrite these changes.")
    if outcome.issues:
        lines.append("Issues:")
        lines += [f"- {issue.severity.value}{f' (operation {issue.index + 1})' if issue.index is not None else ''}: "
                  f"{issue.message}" for issue in outcome.issues]
    if outcome.operations and not outcome.refused:
        lines.append("Operations:")
        lines += [f"- {item.operation.describe()} [{item.ref.object_type.value.lower()} in "
                  f"{item.file.name}]" for item in outcome.operations]
    if check is not None:
        ok = sum(item.ok for item in check.readback)
        lines.append(f"Checks: {ok} of {len(check.readback)} values read back as intended; objects, diagnostics "
                     f"and statuses {'unchanged' if check.passed else 'checked'}.")
        if check.problems:
            lines.append("Problems:")
            lines += [f"- {problem}" for problem in check.problems]
        changes = _assessment_lines(check.assessment.changes)
        if changes:
            lines.append("Analysis changes:")
            lines += changes
    if outcome.diffs:
        lines.append("File changes:")
        lines += [f"```diff\n{diff.diff}\n```" for diff in outcome.diffs]
    return "\n".join(lines)


class AnalyzerTools:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or default_data_dir()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _analyze(project_path: str) -> AnalysisResult:
        path = Path(project_path.strip().strip('"')).expanduser()
        if not path.exists():
            raise ToolError(f"No such folder or file: {path}. Give the full path of the PBIP project folder "
                            "or its .pbip file.")
        try:
            return analyze_project(path)
        except Exception as exc:  # fatal input problems are explained to the model and the user
            raise ToolError(f"Cannot analyze {path}: {exc}") from exc

    def _acknowledgements(self, result: AnalysisResult):
        try:
            state = ProjectState.load(state_file(self.data_dir, result.project.root), str(result.project.root))
        except ValueError:
            return ()
        return tuple(state.acknowledgements.values())

    def _baseline(self, result: AnalysisResult):
        try:
            state = ProjectState.load(state_file(self.data_dir, result.project.root, "assistant"),
                                      str(result.project.root))
        except ValueError:
            return None
        return state.last_run

    # -- tools ------------------------------------------------------------

    def analyze_model(self, project_path: str, sections: list[str] | None = None,
                      include_expressions: bool = True) -> str:
        result = self._analyze(project_path)
        briefing = build_briefing(result, acknowledgements=self._acknowledgements(result),
                                  include_expressions=include_expressions)
        if sections:
            briefing = Briefing(briefing.project_name,
                                tuple(s for s in briefing.sections if s.key in set(sections)))
        return f"Project root: {result.project.root}\n\n{_wrap(briefing.text())}"

    def explain_object(self, project_path: str, object: str, object_type: str | None = None) -> str:
        result = self._analyze(project_path)
        text = object.strip()
        refs = [finding.ref for finding in result.findings]
        if object_type:
            refs = [ref for ref in refs if ref.object_type.value.casefold() == object_type]
        if not text.endswith("]") or "[" not in text:
            table = norm(text.strip("'"))
            in_table = [ref for ref in refs if norm(ref.table) == table]
            if not in_table:
                raise ToolError(self._not_found(text, result))
            return _wrap(self._table_overview(result, in_table))
        cut = text.rindex("[")
        table, name = norm(text[:cut].strip().strip("'")), norm(text[cut + 1:-1].replace("]]", "]"))
        matches = [ref for ref in refs if norm(ref.table) == table and norm(ref.name) == name]
        if not matches:
            raise ToolError(self._not_found(text, result))
        explainer = Explainer(result.graph, result.findings)
        return _wrap("\n\n".join(self._explain(result, explainer, ref) for ref in matches))

    def save_baseline(self, project_path: str) -> str:
        result = self._analyze(project_path)
        run = snapshot(result)
        state = ProjectState(str(result.project.root), last_run=run)
        state.save(state_file(self.data_dir, result.project.root, "assistant"))
        summary = result.summary
        return (f"Baseline saved for {result.project.project_name} ({run.analyzed_at}): columns "
                f"{summary.columns.used} Used / {summary.columns.manual_review} Needs manual review / "
                f"{summary.columns.likely_unused} Likely unused, measures {summary.measures.used} / "
                f"{summary.measures.manual_review} / {summary.measures.likely_unused}, "
                f"{len(result.health_findings)} model-health findings. It replaces any earlier baseline. "
                "After the user has changed the model and saved it in Power BI Desktop, call "
                "compare_with_baseline.")

    def compare_with_baseline(self, project_path: str) -> str:
        result = self._analyze(project_path)
        baseline = self._baseline(result)
        if baseline is None:
            raise ToolError("No baseline is saved for this project. Call save_baseline before the model is "
                            "changed, then compare after the changes are saved in Power BI Desktop.")
        briefing = build_briefing(result, previous=baseline, include_expressions=False)
        kept = Briefing(briefing.project_name,
                        tuple(s for s in briefing.sections if s.key in ("project", "changes")), briefing.assessment)
        return (_wrap(kept.text()) + "\n\nThe baseline is unchanged; call save_baseline to make the current "
                "state the new baseline.")

    # -- change tools (working copies only) ---------------------------------

    @staticmethod
    def _path(text: str) -> Path:
        path = Path(text.strip().strip('"')).expanduser()
        if not path.exists():
            raise ToolError(f"No such folder or file: {path}.")
        return path

    def create_working_copy(self, project_path: str, target_folder: str | None = None) -> str:
        try:
            workspace = create_working_copy(self._path(project_path), target_folder or None)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        return (f"Working copy created: {workspace.root}\nOriginal (never changed): {workspace.original}\n"
                "The original's analysis is recorded as the baseline of this copy. Use this working copy path "
                "with preview_changes, apply_changes, undo_last_change and review_working_copy.")

    def preview_changes(self, project_path: str, operations: list) -> str:
        try:
            outcome = preview_changes(self._path(project_path), operations)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        return _outcome_text(outcome, preview=True)

    def apply_changes(self, working_copy: str, operations: list, note: str = "") -> str:
        try:
            outcome = apply_changes(self._path(working_copy), operations, note)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        return _outcome_text(outcome, preview=False)

    def undo_last_change(self, working_copy: str) -> str:
        try:
            batch = undo_last_change(self._path(working_copy))
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        lines = [f"Undid change {batch.number}{' (' + batch.note + ')' if batch.note else ''}; its files are "
                 "restored from the backups:"]
        lines += [f"- {name}" for name in sorted(batch.files)]
        return "\n".join(lines)

    def review_working_copy(self, working_copy: str) -> str:
        try:
            review = review_working_copy(self._path(working_copy))
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        workspace = review.workspace
        lines = [f"Working copy: {workspace.root}", f"Original (never changed): {workspace.original}",
                 f"Created {workspace.created_at}."]
        if workspace.batches:
            lines.append("Changes applied:")
            for batch in workspace.batches:
                state = " (undone)" if batch.undone else ""
                lines.append(f"- Change {batch.number}{state}, {batch.applied_at}"
                             f"{': ' + batch.note if batch.note else ''}; {len(batch.operations)} operation(s)")
        else:
            lines.append("No changes applied yet.")
        if review.outside_changes:
            lines.append("Files changed outside the analyzer since its last change (for example saved by Power BI "
                         f"Desktop): {', '.join(review.outside_changes)}.")
        lines.append("Compared with the original's analysis:")
        lines += _assessment_lines(review.assessment.changes) or ["- No change in statuses or findings."]
        lines.append("To check in Power BI Desktop (the analyzer cannot):")
        lines += [f"{number}. {step}" for number, step in enumerate(review.checklist, 1)]
        return "\n".join(lines)

    # -- formatting -------------------------------------------------------

    @staticmethod
    def _not_found(text: str, result: AnalysisResult) -> str:
        labels = sorted({finding.ref.label for finding in result.findings}
                        | {finding.ref.table for finding in result.findings})
        close = difflib.get_close_matches(text, labels, n=8, cutoff=0.5)
        hint = f" Similar names: {', '.join(close)}." if close else ""
        return f"No column, measure or table named {text!r} in {result.project.project_name}.{hint}"

    @staticmethod
    def _table_overview(result: AnalysisResult, refs: list[ObjectRef]) -> str:
        status = {finding.ref: finding.status for finding in result.findings}
        lines = [f"Objects of table {refs[0].table}:"]
        lines += [f"- {ref.label} ({ref.object_type.value.lower()}): {STATUS_INFO[status[ref]].label}"
                  for ref in refs]
        return "\n".join(lines)

    @staticmethod
    def _explain(result: AnalysisResult, explainer: Explainer, ref: ObjectRef) -> str:
        explanation = explainer.explain(ref)
        info = STATUS_INFO[explanation.status]
        obj = result.graph.object(ref)
        lines = [f"{ref.label} ({ref.object_type.value.lower()}): {info.label}", info.explanation]
        if explanation.status == Status.USED:
            lines.append(f"Why: {format_path(explanation.use_path) or 'proven use (see evidence)'}")
        elif explanation.status == Status.MANUAL_REVIEW:
            finding = next(f for f in result.findings if f.ref == ref)
            lines.append(f"Why: {review_reason(explainer, finding)}")
        elif explanation.status == Status.LIKELY_UNUSED:
            lines.append("Why: no supported parser or safety check found evidence of use.")
        if obj is not None:
            properties = [f"hidden: {'yes' if obj.hidden else 'no'}"]
            if ref.object_type == ObjectType.COLUMN:
                properties.append(f"calculated: {'yes' if obj.calculated else 'no'}")
            if obj.data_type:
                properties.append(f"data type: {obj.data_type}")
            if obj.source_column:
                properties.append(f"source column: {obj.source_column}")
            if obj.sort_by_column:
                properties.append(f"sorted by: {obj.sort_by_column}")
            if obj.source_file:
                try:
                    location = Path(obj.source_file).resolve().relative_to(result.project.root.resolve()).as_posix()
                except ValueError:
                    location = Path(obj.source_file).name
                properties.append(f"defined in: {location}{':' + str(obj.source_line) if obj.source_line else ''}")
            lines.append("Properties: " + "; ".join(properties))
            if obj.description:
                lines.append(f"Description: {obj.description}")
            if obj.expression:
                lines.append(f"DAX:\n```dax\n{obj.expression.strip()}\n```")
        if explanation.evidence:
            lines.append("Evidence pointing at it:")
            lines += [f"- {EVIDENCE_LABELS[ev.evidence_type]}"
                      f"{' from ' + ev.source.label if ev.source is not None else ''}: {ev.reason}"
                      for ev in explanation.evidence]
        if explanation.dependencies:
            lines.append("It depends on:")
            lines += [f"- {EVIDENCE_LABELS[ev.evidence_type]}: {ev.target.label}" for ev in explanation.dependencies]
        findings = [row for row in health_rows(result) if row.object_ref == ref]
        if findings:
            lines.append("Model-health findings about it:")
            lines += [f"- {row.rule_id}: {row.title}" for row in findings]
        return "\n".join(lines)

    # -- prompts ----------------------------------------------------------

    def prompt(self, task: Task, project_path: str, question: str = "", previous_advice: str = "") -> str:
        result = self._analyze(project_path)
        previous = None
        if task == Task.EVALUATE:
            previous = self._baseline(result)
            if previous is None:
                raise ToolError("No baseline is saved for this project. Use the save_baseline tool before "
                                "changing the model, then run this prompt after saving the changes.")
        briefing = build_briefing(result, previous=previous, acknowledgements=self._acknowledgements(result))
        return (build_prompt(task, briefing, question=question, prior_advice=previous_advice).text()
                + f"\n\nProject path for this server's tools: {result.project.root}")

    # -- registration -----------------------------------------------------

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool("analyze_model", "Analyze a Power BI model",
                 "Run the deterministic Power BI model-health analyzer on a PBIP project and return its briefing: "
                 "counts, model-health findings with evidence and recommendations, cleanup candidates, objects "
                 "needing manual review, diagnostics, model structure and (optionally) all DAX and M.",
                 {"type": "object", "properties": {
                     "project_path": _PATH,
                     "sections": {"type": "array", "items": {"type": "string", "enum": list(SECTION_KEYS)},
                                  "description": "Only these briefing sections (default: all)."},
                     "include_expressions": {"type": "boolean",
                                             "description": "Include all DAX and M (default true)."}},
                  "required": ["project_path"], "additionalProperties": False},
                 self.analyze_model, _READ_ONLY),
            Tool("explain_object", "Explain a column, measure or table",
                 "Explain why a column or measure has its cleanup status: evidence path, evidence, dependencies, "
                 "properties, DAX and related findings. Give a table name alone to list its objects.",
                 {"type": "object", "properties": {
                     "project_path": _PATH,
                     "object": {"type": "string", "description": "Table[Name], or a table name."},
                     "object_type": {"type": "string", "enum": ["column", "measure"],
                                     "description": "Only when a column and a measure share the name."}},
                  "required": ["project_path", "object"], "additionalProperties": False},
                 self.explain_object, _READ_ONLY),
            Tool("save_baseline", "Save a baseline before changes",
                 "Record the project's current analysis as the baseline for compare_with_baseline. Writes only to "
                 "the analyzer's per-user data folder, never to the project; replaces an earlier baseline.",
                 {"type": "object", "properties": {"project_path": _PATH},
                  "required": ["project_path"], "additionalProperties": False},
                 self.save_baseline,
                 {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}),
            Tool("compare_with_baseline", "Compare with the baseline",
                 "Analyze the project again and compare it with the saved baseline: status counts before and "
                 "after and every change with the analyzer's assessment (risk, attention, improvement, cleanup, "
                 "neutral), most serious first.",
                 {"type": "object", "properties": {"project_path": _PATH},
                  "required": ["project_path"], "additionalProperties": False},
                 self.compare_with_baseline, _READ_ONLY),
            Tool("create_working_copy", "Create a working copy for changes",
                 "Copy the project (.pbip file, semantic model and report folders) to a new folder next to it and "
                 "record the original's analysis as the copy's baseline. Changes are only ever applied to such a "
                 "copy; the original is never written.",
                 {"type": "object", "properties": {
                     "project_path": _PATH,
                     "target_folder": {"type": "string",
                                       "description": "Optional new folder for the copy (must not exist). Default: "
                                                      "'<project folder> (proposed <date time>)' next to it."}},
                  "required": ["project_path"], "additionalProperties": False},
                 self.create_working_copy,
                 {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}),
            Tool("preview_changes", "Preview model changes",
                 "Validate a batch of metadata changes and try it on a temporary copy: problems, the exact file "
                 "changes, read-back of each value and the analysis changes. Writes nothing.",
                 {"type": "object", "properties": {"project_path": _PATH, "operations": _OPERATIONS},
                  "required": ["project_path", "operations"], "additionalProperties": False},
                 self.preview_changes, _READ_ONLY),
            Tool("apply_changes", "Apply model changes to the working copy",
                 "Apply a batch of metadata changes to a working copy made by create_working_copy (refused for any "
                 "other folder). Validates and tries the batch first, keeps backups, re-analyzes the copy and "
                 "restores it automatically if anything other than the intended values changed.",
                 {"type": "object", "properties": {
                     "working_copy": _WORKING_COPY, "operations": _OPERATIONS,
                     "note": {"type": "string", "description": "Short theme of the batch, kept in its history."}},
                  "required": ["working_copy", "operations"], "additionalProperties": False},
                 self.apply_changes,
                 {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}),
            Tool("undo_last_change", "Undo the last change",
                 "Restore the files of the last applied change in a working copy from its backups. Refused if the "
                 "files changed afterwards (for example saved by Power BI Desktop).",
                 {"type": "object", "properties": {"working_copy": _WORKING_COPY},
                  "required": ["working_copy"], "additionalProperties": False},
                 self.undo_last_change,
                 {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}),
            Tool("review_working_copy", "Review the working copy",
                 "Summarize a working copy: changes applied, every analysis change compared with the original, "
                 "files changed outside the analyzer, and what the user must still check in Power BI Desktop.",
                 {"type": "object", "properties": {"working_copy": _WORKING_COPY},
                  "required": ["working_copy"], "additionalProperties": False},
                 self.review_working_copy, _READ_ONLY),
        )

    def prompts(self) -> tuple[PromptTemplate, ...]:
        path = PromptArgument("project_path", "Full path of the PBIP project folder or .pbip file.", True)
        question = PromptArgument("question", "Optional question or focus.")
        return (
            PromptTemplate("interpret", "Interpret the analysis",
                           "Explain what the analyzer found in a Power BI model and what matters most.",
                           (path, question), lambda **a: self.prompt(Task.INTERPRET, **a)),
            PromptTemplate("next_steps", "Suggest next steps",
                           "A prioritized, verifiable plan to move the model towards best practice.",
                           (path, question), lambda **a: self.prompt(Task.NEXT_STEPS, **a)),
            PromptTemplate("evaluate", "Evaluate my changes",
                           "Assess changes made since the saved baseline (use save_baseline first).",
                           (path, question, PromptArgument("previous_advice", "Optional: the plan being followed.")),
                           lambda **a: self.prompt(Task.EVALUATE, **a)),
            PromptTemplate("improve_model", "Improve the model",
                           "Let Claude make metadata improvements (descriptions, display folders, format strings, "
                           "hidden fields) in a checked working copy; the original is not changed.",
                           (path, question), lambda **a: self.prompt(Task.IMPROVE, **a)),
        )
