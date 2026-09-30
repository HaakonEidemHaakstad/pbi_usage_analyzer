from __future__ import annotations

from pathlib import Path

from .model import ProjectPaths


def discover_project(project_folder: Path) -> ProjectPaths:
    project_folder = project_folder.expanduser().resolve()
    if not project_folder.is_dir():
        raise NotADirectoryError(f"Prosjektmappen finnes ikke eller er ikke en mappe: {project_folder}")

    report_folders = sorted(p for p in project_folder.glob("*.Report") if p.is_dir())
    model_folders = sorted(p for p in project_folder.glob("*.SemanticModel") if p.is_dir())
    pbip_files = sorted(project_folder.glob("*.pbip"))

    report_names = {p.name[:-len('.Report')]: p for p in report_folders}
    model_names = {p.name[:-len('.SemanticModel')]: p for p in model_folders}
    common = sorted(set(report_names) & set(model_names))

    if len(common) == 1:
        project_name = common[0]
        report_folder = report_names[project_name]
        model_folder = model_names[project_name]
    elif len(report_folders) == 1 and len(model_folders) == 1:
        report_folder = report_folders[0]
        model_folder = model_folders[0]
        project_name = report_folder.name[:-len('.Report')]
    else:
        raise RuntimeError(
            "Kunne ikke identifisere ett entydig .Report/.SemanticModel-par i prosjektmappen."
        )

    expected_pbip = project_folder / f"{project_name}.pbip"
    pbip_file = expected_pbip if expected_pbip.exists() else (pbip_files[0] if len(pbip_files) == 1 else None)

    return ProjectPaths(
        project_name=project_name,
        root=project_folder,
        report_folder=report_folder,
        model_folder=model_folder,
        pbip_file=pbip_file,
        excel_output=project_folder / f"{project_name}_usage_analysis_v2.xlsx",
        text_output=project_folder / f"{project_name}_usage_summary_v2.txt",
    )
