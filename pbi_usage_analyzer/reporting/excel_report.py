from __future__ import annotations

from pathlib import Path
import pandas as pd

from ..analysis.build_graph import AnalysisContext
from ..model import Finding, ObjectType, Status


def _finding_rows(findings: list[Finding], obj_type: ObjectType) -> list[dict]:
    rows = []
    for f in findings:
        if f.ref.object_type != obj_type:
            continue
        rows.append({
            "Table": f.ref.table,
            "Object": f.ref.name,
            "Status": f.status.value,
            "Evidence types": " | ".join(f.evidence_types),
            "Reasons": " | ".join(f.reasons),
        })
    return rows


def write_excel(path: Path, project_name: str, findings: list[Finding], ctx: AnalysisContext) -> None:
    cols = [f for f in findings if f.ref.object_type == ObjectType.COLUMN and f.status != Status.INTERNAL]
    measures = [f for f in findings if f.ref.object_type == ObjectType.MEASURE and f.status != Status.INTERNAL]
    summary = pd.DataFrame([
        {"Metric": "Project", "Value": project_name},
        {"Metric": "Model columns", "Value": len(cols)},
        {"Metric": "Measures", "Value": len(measures)},
        {"Metric": "Likely unused columns", "Value": sum(f.status == Status.LIKELY_UNUSED for f in cols)},
        {"Metric": "Manual review columns", "Value": sum(f.status == Status.MANUAL_REVIEW for f in cols)},
        {"Metric": "Likely unused measures", "Value": sum(f.status == Status.LIKELY_UNUSED for f in measures)},
        {"Metric": "Manual review measures", "Value": sum(f.status == Status.MANUAL_REVIEW for f in measures)},
        {"Metric": "Graph evidence edges", "Value": len(ctx.graph.evidence)},
        {"Metric": "Power Query dependencies", "Value": len(ctx.powerquery.dependencies) if ctx.powerquery else 0},
    ])

    evidence_rows = [{
        "Source": ev.source.label if ev.source else "",
        "Target": ev.target.label,
        "Type": ev.evidence_type.value,
        "Confidence": ev.confidence,
        "Reason": ev.reason,
        "Source file": ev.source_file,
    } for ev in ctx.graph.evidence]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(_finding_rows(findings, ObjectType.COLUMN)).to_excel(writer, sheet_name="Column analysis", index=False)
        pd.DataFrame([r for r in _finding_rows(findings, ObjectType.COLUMN) if r["Status"] == Status.LIKELY_UNUSED.value]).to_excel(writer, sheet_name="Likely unused columns", index=False)
        pd.DataFrame(_finding_rows(findings, ObjectType.MEASURE)).to_excel(writer, sheet_name="Measure analysis", index=False)
        pd.DataFrame([r for r in _finding_rows(findings, ObjectType.MEASURE) if r["Status"] == Status.LIKELY_UNUSED.value]).to_excel(writer, sheet_name="Likely unused measures", index=False)
        pd.DataFrame(evidence_rows).to_excel(writer, sheet_name="Dependency evidence", index=False)
        if ctx.report:
            pd.DataFrame(ctx.report.structured_refs).to_excel(writer, sheet_name="Report usage", index=False)
            pd.DataFrame(ctx.report.raw_hits).to_excel(writer, sheet_name="Raw report safety net", index=False)
            pd.DataFrame(ctx.report.stale).to_excel(writer, sheet_name="Stale references", index=False)
            pd.DataFrame(ctx.report.fallback).to_excel(writer, sheet_name="Fallback matches", index=False)
            pd.DataFrame(ctx.report.auto_date).to_excel(writer, sheet_name="Auto date references", index=False)
        if ctx.powerquery:
            pd.DataFrame(ctx.powerquery.dependencies).to_excel(writer, sheet_name="Power Query dependencies", index=False)
        pd.DataFrame({"Warning": ctx.warnings}).to_excel(writer, sheet_name="Warnings", index=False)
