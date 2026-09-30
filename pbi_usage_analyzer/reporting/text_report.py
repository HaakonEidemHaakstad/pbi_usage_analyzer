from __future__ import annotations

from collections import Counter, defaultdict

from ..analysis.build_graph import AnalysisContext
from ..model import Finding, ObjectType, Status


def generate_text(project_name: str, findings: list[Finding], ctx: AnalysisContext) -> str:
    columns = [f for f in findings if f.ref.object_type == ObjectType.COLUMN and f.status != Status.INTERNAL]
    measures = [f for f in findings if f.ref.object_type == ObjectType.MEASURE and f.status != Status.INTERNAL]
    unused_cols = [f for f in columns if f.status == Status.LIKELY_UNUSED]
    unused_measures = [f for f in measures if f.status == Status.LIKELY_UNUSED]
    manual_cols = [f for f in columns if f.status == Status.MANUAL_REVIEW]
    manual_measures = [f for f in measures if f.status == Status.MANUAL_REVIEW]
    source_cols = []
    for f in unused_cols:
        obj = ctx.graph.object(f.ref)
        if obj and not obj.calculated and obj.source_column:
            source_cols.append(f)

    pct = (len(unused_cols) / len(columns) * 100) if columns else 0
    lines: list[str] = []
    sep = "=" * 70
    sub = "-" * 70
    lines += [sep, "POWER BI MODEL ANALYSIS V2", sep, "", f"Project: {project_name}", "", "SUMMARY", sub]
    lines.append(f"The semantic model contains {len(columns)} columns and {len(measures)} measures.")
    lines.append(f"{len(unused_cols)} of {len(columns)} columns ({pct:.1f} %) appear to be unused.")
    lines.append(f"In addition, {len(unused_measures)} of {len(measures)} measures appear to be unused.")
    lines.append(f"{len(manual_cols)} columns and {len(manual_measures)} measures are held for manual review.")
    lines.append("")
    lines.append("The analysis uses a dependency graph across PBIR, TMDL/DAX, relationships, hierarchies, sorting, and Power Query/M.")
    lines.append("'Likely unused' means no known usage or relevant dependency was found. These are cleanup candidates, not objects that are automatically safe to delete.")

    by_table = Counter(f.ref.table for f in unused_cols)
    if by_table:
        lines += ["", "CLEANUP CANDIDATES BY TABLE", sub]
        totals = Counter(f.ref.table for f in columns if f.status != Status.INTERNAL)
        lines.append(f"{'Table':25} {'Likely unused':>14} {'Total':>8} {'Share':>10}")
        lines.append("-" * 62)
        for table, count in by_table.most_common():
            total = totals[table]
            share = count / total * 100 if total else 0
            lines.append(f"{table:25} {count:14d} {total:8d} {share:9.1f}%")

    if ctx.powerquery and ctx.powerquery.dependencies:
        lines += ["", "POWER QUERY / M DEPENDENCIES", sub]
        lines.append("These dependencies were extracted from actual M expressions in TMDL partitions:")
        lines.append("")
        for row in ctx.powerquery.dependencies:
            lines.append(f"  - {row['Query']} <- {row['Depends on query']}")
        lines.append("")
        lines.append("Query-level M dependencies from ordinary model tables conservatively protect upstream columns, but do not prove that every column is required. These columns receive manual-review status rather than 'Used'. Internal auto-date tables protect only specifically identified columns; unresolved references produce warnings.")

    if unused_cols:
        lines += ["", "LIKELY UNUSED COLUMNS", sub]
        grouped = defaultdict(list)
        source_refs = {f.ref for f in source_cols}
        for f in unused_cols:
            grouped[f.ref.table].append(f)
        for table in sorted(grouped, key=str.casefold):
            table_findings = sorted(grouped[table], key=lambda f: f.ref.name.casefold())
            lines.append(f"{table} ({len(table_findings)} columns)")
            for finding in table_findings:
                marker = " [SOURCE]" if finding.ref in source_refs else ""
                lines.append(f"  - {finding.ref.name}{marker}")
            lines.append("")

    if unused_measures:
        lines += ["LIKELY UNUSED MEASURES", sub]
        grouped = defaultdict(list)
        for f in unused_measures:
            grouped[f.ref.table].append(f.ref.name)
        for table in sorted(grouped, key=str.casefold):
            lines.append(table)
            for name in sorted(grouped[table], key=str.casefold):
                lines.append(f"  - {name}")
            lines.append("")

    if manual_cols or manual_measures:
        lines += ["ITEMS REQUIRING REVIEW", sub]
        lines.append(f"- {len(manual_cols)} columns require manual review.")
        lines.append(f"- {len(manual_measures)} measures require manual review.")
        lines.append("")
        for f in manual_cols:
            reason = " | ".join(f.reasons) if f.reasons else "Unresolved dependency"
            lines.append(f"  - {f.ref.label}: {reason}")

    if ctx.report:
        if ctx.report.stale:
            lines += ["", "POSSIBLY STALE REPORT REFERENCES", sub]
            for row in ctx.report.stale:
                lines.append(f"  - {row['Table']}[{row['Field']}] ({row['Type']})")
        if ctx.report.fallback:
            lines += ["", "AUTOMATICALLY MATCHED REFERENCES", sub]
            for row in ctx.report.fallback:
                lines.append(f"  - {row['Report table']}[{row['Report field']}] -> {row['Matched model table']}[{row['Matched model field']}]")

    if ctx.warnings:
        lines += ["", "WARNINGS", sub, *ctx.warnings]

    lines += ["", "RECOMMENDED NEXT STEPS", sub,
              "1. Start with 'Likely unused' objects and remove a small number at a time.",
              "2. Refresh the report and validate visuals, filters, and calculations after each round.",
              "3. Handle 'Needs manual review' objects separately; they are intentionally excluded from automatic cleanup.",
              "4. For Power Query sources, consider removing confirmed unnecessary source columns early when query folding and other dependencies allow it.",
              "", "LIMITATIONS", sub,
              "This is static analysis. Dynamic or new Power BI constructs may require manual review.",
              "Other reports using this semantic model may depend on objects that this report does not use."]
    return "\n".join(lines) + "\n"
