from __future__ import annotations

import argparse
from pathlib import Path

from .api import analyze_project
from .health.engine import RULES
from .health.model import HealthSeverity
from .reporting.excel_report import write_excel
from .reporting.text_report import generate_text
from .reporting.json_report import write_json


def run(project_folder: Path, *, health_rule_ids=None, health_severities=None, json_output: bool = False) -> tuple[Path, Path]:
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
    findings = result.findings

    text_report = generate_text(project.project_name, findings, ctx, result.health_findings, result.health_filter_scope)
    project.text_output.write_text(text_report, encoding="utf-8")
    write_excel(project.excel_output, project.project_name, findings, ctx, result.health_findings, result.health_filter_scope)

    json_path = project.root / f"{project.project_name}_usage_analysis_v2.json"
    if json_output:
        write_json(json_path, result)

    cols = result.summary.columns
    measures = result.summary.measures
    print(f"Columns: {cols.business_total}")
    print(f"  Used: {cols.used}")
    print(f"  Needs manual review: {cols.manual_review}")
    print(f"  Likely unused: {cols.likely_unused}")
    print(f"Measures: {measures.business_total}")
    print(f"  Likely unused: {measures.likely_unused}")
    if ctx.powerquery:
        print(f"Power Query dependencies: {len(ctx.powerquery.dependencies)}")
        for row in ctx.powerquery.dependencies:
            print(f"  {row['Query']} <- {row['Depends on query']}")
    print()
    print(f"Text report: {project.text_output}")
    print(f"Technical report: {project.excel_output}")
    if json_output:
        print(f"JSON report: {json_path}")
    return project.text_output, project.excel_output


def cli() -> None:
    parser = argparse.ArgumentParser(description="Conservative Power BI PBIP/PBIR usage analyzer")
    parser.add_argument("project", nargs="?", default=str(Path.cwd()), help="PBIP project folder. Defaults to current directory.")
    parser.add_argument("--health-rule", action="append", choices=[rule_id for rule_id, _, _ in RULES],
                        help="Include this health rule (repeatable; default: all).")
    parser.add_argument("--health-severity", action="append", choices=[s.value for s in HealthSeverity],
                        help="Include this health severity (repeatable; default: all).")
    parser.add_argument("--json", action="store_true", help="Also write a versioned JSON analysis report in the project folder.")
    args = parser.parse_args()
    run(Path(args.project), health_rule_ids=args.health_rule, health_severities=args.health_severity, json_output=args.json)


if __name__ == "__main__":
    cli()
