"""Command line: analyze one or more projects and write the text and Excel reports."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import analyze_project
from .health.engine import RULES
from .health.model import HealthSeverity
from .reporting.files import write_reports


def run(project_folder: Path, *, health_rule_ids=None, health_severities=None, json_output: bool = False,
        output_folder: Path | None = None) -> tuple[Path, Path]:
    """Analyze one project, print a summary and write its reports.

    Reports go to `output_folder`, or to the project folder when it is None.
    """
    options = {}
    if health_rule_ids is not None:
        options["health_rule_ids"] = health_rule_ids
    if health_severities is not None:
        options["health_severities"] = health_severities
    result = analyze_project(project_folder, **options)
    project = result.project
    print("=" * 70)
    print("POWER BI USAGE ANALYZER V2")
    print("=" * 70)
    print(f"Project:       {project.project_name}")
    print(f"Report:         {project.report_folder.name}")
    print(f"Semantic model: {project.model_folder.name}")
    print()

    ctx = result.context
    if output_folder is not None:
        output_folder.mkdir(parents=True, exist_ok=True)
    files = write_reports(result, output_folder, json=json_output)

    cols = result.summary.columns
    measures = result.summary.measures
    print(f"Columns: {cols.business_total}")
    print(f"  Used: {cols.used}")
    print(f"  Needs manual review: {cols.manual_review}")
    print(f"  Likely unused: {cols.likely_unused}")
    print(f"Measures: {measures.business_total}")
    print(f"  Likely unused: {measures.likely_unused}")
    print(f"Model health findings: {len(result.health_findings)}")
    if result.diagnostics:
        print(f"Diagnostics: {len(result.diagnostics)} (results may be incomplete; see the reports)")
    if ctx.powerquery:
        print(f"Power Query dependencies: {len(ctx.powerquery.dependencies)}")
        for row in ctx.powerquery.dependencies:
            print(f"  {row['Query']} <- {row['Depends on query']}")
    print()
    print(f"Text report: {files.text}")
    print(f"Technical report: {files.excel}")
    if files.json:
        print(f"JSON report: {files.json}")
    return files.text, files.excel


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Conservative Power BI PBIP/PBIR usage analyzer. Writes a plain-text summary and an "
                    "Excel report for each project.")
    result.add_argument("projects", nargs="*", metavar="project",
                        help="PBIP project folder or .pbip file (several allowed). Default: current directory.")
    result.add_argument("--out", type=Path, metavar="FOLDER",
                        help="Write the reports to this folder instead of each project's folder.")
    result.add_argument("--health-rule", action="append", choices=[rule_id for rule_id, _, _ in RULES],
                        help="Include this health rule (repeatable; default: all).")
    result.add_argument("--health-severity", action="append", choices=[s.value for s in HealthSeverity],
                        help="Include this health severity (repeatable; default: all).")
    result.add_argument("--json", action="store_true", help="Also write a versioned JSON analysis report.")
    return result


def cli(argv: list[str] | None = None) -> int:
    """Run the command line; returns 0 when every project succeeded, 1 otherwise."""
    args = parser().parse_args(argv)
    projects = [Path(p) for p in args.projects] or [Path.cwd()]
    failures = 0
    for number, project in enumerate(projects):
        if number:
            print()
        try:
            run(project, health_rule_ids=args.health_rule, health_severities=args.health_severity,
                json_output=args.json, output_folder=args.out)
        except (OSError, RuntimeError, ValueError) as exc:
            failures += 1
            print(f"Could not analyze {project}: {exc}", file=sys.stderr)
    if len(projects) > 1:
        print(f"\nAnalyzed {len(projects) - failures} of {len(projects)} projects.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(cli())
