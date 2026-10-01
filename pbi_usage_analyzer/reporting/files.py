"""Write the standard report files for an analysis; shared by the CLI and the GUI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..api import AnalysisResult
from .excel_report import write_excel
from .json_report import write_json
from .text_report import generate_text


@dataclass(frozen=True)
class ReportFiles:
    text: Path
    excel: Path
    json: Path | None


def write_reports(result: AnalysisResult, folder: str | Path | None = None, *,
                  json: bool = False) -> ReportFiles:
    """Write text and Excel (and optionally JSON) reports into `folder`.

    The default folder is the project root, as the CLI has always used. Existing
    files with the same names are replaced.
    """
    project = result.project
    folder = project.root if folder is None else Path(folder)
    # File names come from project discovery (ProjectPaths).
    text_path, excel_path = folder / project.text_output.name, folder / project.excel_output.name
    text_path.write_text(generate_text(project.project_name, result.findings, result.context,
                                       result.health_findings, result.health_filter_scope),
                         encoding="utf-8")
    write_excel(excel_path, project.project_name, result.findings, result.context,
                result.health_findings, result.health_filter_scope)
    json_path = None
    if json:
        json_path = folder / f"{project.project_name}_usage_analysis_v2.json"
        write_json(json_path, result)
    return ReportFiles(text_path, excel_path, json_path)
