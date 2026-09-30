from __future__ import annotations

import argparse
from pathlib import Path

from .analysis.build_graph import build_graph
from .analysis.classify import classify
from .discovery import discover_project
from .model import ObjectType, Status
from .reporting.excel_report import write_excel
from .reporting.text_report import generate_text


def run(project_folder: Path) -> tuple[Path, Path]:
    project = discover_project(project_folder)
    print("=" * 70)
    print("POWER BI USAGE ANALYZER V2")
    print("=" * 70)
    print(f"Prosjekt:       {project.project_name}")
    print(f"Report:         {project.report_folder.name}")
    print(f"Semantic model: {project.model_folder.name}")
    print()

    ctx = build_graph(project.report_folder, project.model_folder)
    findings = classify(ctx.graph)

    text_report = generate_text(project.project_name, findings, ctx)
    project.text_output.write_text(text_report, encoding="utf-8")
    write_excel(project.excel_output, project.project_name, findings, ctx)

    cols = [f for f in findings if f.ref.object_type == ObjectType.COLUMN]
    measures = [f for f in findings if f.ref.object_type == ObjectType.MEASURE]
    print(f"Kolonner: {len(cols)}")
    print(f"  Used: {sum(f.status == Status.USED for f in cols)}")
    print(f"  Needs manual review: {sum(f.status == Status.MANUAL_REVIEW for f in cols)}")
    print(f"  Likely unused: {sum(f.status == Status.LIKELY_UNUSED for f in cols)}")
    print(f"Measures: {len(measures)}")
    print(f"  Likely unused: {sum(f.status == Status.LIKELY_UNUSED for f in measures)}")
    if ctx.powerquery:
        print(f"Power Query-avhengigheter: {len(ctx.powerquery.dependencies)}")
        for row in ctx.powerquery.dependencies:
            print(f"  {row['Query']} <- {row['Depends on query']}")
    print()
    print(f"Brukerrapport: {project.text_output}")
    print(f"Teknisk rapport: {project.excel_output}")
    return project.text_output, project.excel_output


def cli() -> None:
    parser = argparse.ArgumentParser(description="Conservative Power BI PBIP/PBIR usage analyzer")
    parser.add_argument("project", nargs="?", default=str(Path.cwd()), help="PBIP project folder. Defaults to current directory.")
    args = parser.parse_args()
    run(Path(args.project))


if __name__ == "__main__":
    cli()
