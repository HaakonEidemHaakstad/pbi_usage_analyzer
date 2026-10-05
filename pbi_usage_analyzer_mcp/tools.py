"""The analyzer's MCP tools and prompts, built on `pbi_usage_analyzer.assistant`.

Every call analyzes the project afresh (well under a second on real projects), so
answers always reflect the files as saved in Power BI Desktop. The only state is
the per-project baseline written by `save_baseline`, stored with the user's other
analyzer state; tools never write to the project.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from pbi_usage_analyzer import AnalysisResult, analyze_project
from pbi_usage_analyzer.assistant import SYSTEM_PROMPT, Briefing, Task, build_briefing, build_prompt
from pbi_usage_analyzer.model import ObjectRef, ObjectType, Status
from pbi_usage_analyzer.util import norm
from pbi_usage_analyzer.views import (EVIDENCE_LABELS, STATUS_INFO, Explainer, ProjectState, format_path,
                                      health_rows, review_reason, snapshot)
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
- The tools only read the project. The user makes all changes in Power BI Desktop."""

_PATH = {"type": "string",
         "description": "Full path of the Power BI project folder (containing the .pbip file) or of the .pbip file."}
_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}


def default_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / ORGANIZATION / APPLICATION


def _wrap(text: str) -> str:
    return f"<analysis>\n{text.rstrip()}\n</analysis>"


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
        )
