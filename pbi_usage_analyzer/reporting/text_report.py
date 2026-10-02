from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from ..analysis.build_graph import AnalysisContext
from ..analysis.classify import MANUAL_REVIEW, OWNER_DEPENDENCY
from ..health.engine import RULE_INFO
from ..health.model import HealthFinding, HealthSeverity
from ..health.filtering import HealthFilterScope
from .health_scope import health_scope_rows
from ..model import Finding, ObjectType, Status
from ..views.catalog import STATUS_INFO
from ..views.explain import Explainer, format_path
from ..views.rows import relationship_labels

WIDTH = 70
# Health rules whose first evidence line adds nothing to the scope shown.
_NO_DETAIL = {"MEASURE_DESCRIPTION_MISSING"}
_REVIEW_CAUSES = MANUAL_REVIEW | OWNER_DEPENDENCY


def _shorten(text: str, limit: int = 110) -> str:
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _review_reason(explainer: Explainer, finding: Finding) -> str:
    """Why an object is held for review: a lineage path, or its own evidence."""
    explanation = explainer.explain(finding.ref)
    if explanation.review_path:
        return "via " + format_path(explanation.review_path)
    reasons = []
    for ev in explanation.evidence:
        if ev.evidence_type not in _REVIEW_CAUSES:
            continue
        reason = ev.reason
        owner = explainer.status_of(ev.source) if ev.source is not None else None
        if owner is not None and owner != Status.USED:
            reason += f" ({ev.source.label} is {STATUS_INFO[owner].label})"
        if reason not in reasons:
            reasons.append(reason)
    return "; ".join(reasons) or " | ".join(finding.reasons) or "Unresolved dependency"


def _health_lines(health_findings: tuple[HealthFinding, ...], ctx: AnalysisContext) -> list[str]:
    """One compact block per rule; full explanations stay in the Excel report."""
    # Plain ASCII: text reports are opened in many tools and code pages.
    labels = {name: label.replace("→", "->") for name, label in relationship_labels(ctx.relationships).items()}
    by_rule: dict[str, list[HealthFinding]] = defaultdict(list)
    for finding in health_findings:
        by_rule[finding.rule_id].append(finding)
    order = list(RULE_INFO)
    rules = sorted(by_rule, key=lambda rule: (by_rule[rule][0].severity != HealthSeverity.WARNING,
                                              order.index(rule) if rule in order else len(order)))
    lines = []
    for rule in rules:
        findings = by_rule[rule]
        info = RULE_INFO.get(rule)
        severity = "Warning" if findings[0].severity == HealthSeverity.WARNING else "Info"
        name = info.name if info else findings[0].title
        count = f"{len(findings)} finding" + ("s" if len(findings) != 1 else "")
        lines += ["", f"[{severity}] {name} [{rule}] - {count}"]
        lines.append(f"  {info.summary if info else findings[0].explanation}")
        for finding in findings:
            scope = labels.get(finding.scope, finding.scope) if finding.category == "relationships" else finding.scope
            where = f"{Path(finding.source_file).name}:{finding.line}" if finding.source_file else ""
            lines.append(f"  - {scope}" + (f"  ({where})" if where else ""))
            if rule not in _NO_DETAIL and finding.category != "relationships" and finding.evidence:
                # The location is already shown; drop repeated "line N: " prefixes.
                # A duplicate-measure finding's DAX expression is too long for one line.
                items = [re.sub(r"^line \d+: ", "", item) for item in finding.evidence
                         if not item.startswith("Expression:")]
                lines.append(f"      {_shorten('; '.join(items), 140)}")
    lines += ["", "Explanations, evidence and recommendations for each finding are in the Excel report "
                  "(sheet 'Model health')."]
    return lines


def generate_text(project_name: str, findings: list[Finding], ctx: AnalysisContext, health_findings: tuple[HealthFinding, ...] = (), health_filter_scope: HealthFilterScope | None = None) -> str:
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
    sep = "=" * WIDTH
    sub = "-" * WIDTH
    lines += [sep, "POWER BI MODEL ANALYSIS V2", sep, "", f"Project: {project_name}", "", "SUMMARY", sub]
    lines.append(f"The semantic model contains {len(columns)} columns and {len(measures)} measures.")
    lines.append(f"{len(unused_cols)} of {len(columns)} columns ({pct:.1f} %) appear to be unused.")
    lines.append(f"In addition, {len(unused_measures)} of {len(measures)} measures appear to be unused.")
    lines.append(f"{len(manual_cols)} columns and {len(manual_measures)} measures are held for manual review.")
    if health_findings:
        warnings = sum(f.severity == HealthSeverity.WARNING for f in health_findings)
        lines.append(f"Model health: {warnings} warnings and {len(health_findings) - warnings} informational findings.")
    lines.append("")
    lines.append("The analysis uses a dependency graph across PBIR, TMDL/DAX, relationships, hierarchies, sorting, and Power Query/M.")
    lines.append("'Likely unused' means no known usage or relevant dependency was found. These are cleanup candidates, not objects that are automatically safe to delete.")

    by_table = Counter(f.ref.table for f in unused_cols)
    if by_table:
        lines += ["", "CLEANUP CANDIDATES BY TABLE", sub]
        totals = Counter(f.ref.table for f in columns if f.status != Status.INTERNAL)
        name_width = max(len("Table"), *(len(table) for table in by_table))
        lines.append(f"{'Table':{name_width}} {'Likely unused':>14} {'Total':>8} {'Share':>10}")
        lines.append("-" * (name_width + 35))
        for table, count in by_table.most_common():
            total = totals[table]
            share = count / total * 100 if total else 0
            lines.append(f"{table:{name_width}} {count:14d} {total:8d} {share:9.1f}%")

    if ctx.powerquery and ctx.powerquery.dependencies:
        lines += ["", "POWER QUERY / M DEPENDENCIES", sub]
        lines.append("These dependencies were extracted from actual M expressions in TMDL partitions:")
        lines.append("")
        for row in ctx.powerquery.dependencies:
            via = f" (through {' -> '.join(row['Via'])})" if row["Via"] else ""
            lines.append(f"  - {row['Query']} <- {row['Depends on query']}{via}")
        lines.append("")
        lines.append("Supported M lineage protects output and required schema columns. Unresolved query-level M dependencies from ordinary model tables conservatively protect upstream columns, but do not prove that every column is required. These columns receive manual-review status rather than 'Used'. Internal auto-date tables protect only specifically identified columns; unresolved references produce warnings.")

    if unused_cols:
        lines += ["", "LIKELY UNUSED COLUMNS", sub]
        if source_cols:
            lines += ["[SOURCE] = loaded from the data source; removing it in Power Query also makes the refresh lighter.", ""]
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
        explainer = Explainer(ctx.graph, findings)
        lines += ["ITEMS REQUIRING REVIEW", sub]
        lines.append(f"- {len(manual_cols)} columns require manual review.")
        lines.append(f"- {len(manual_measures)} measures require manual review.")
        lines.append("")
        for f in manual_cols + manual_measures:
            lines.append(f"  - {f.ref.label}: {_review_reason(explainer, f)}")

    if ctx.report:
        if ctx.report.stale:
            lines += ["", "POSSIBLY STALE REPORT REFERENCES", sub]
            for row in ctx.report.stale:
                lines.append(f"  - {row['Table']}[{row['Field']}] ({row['Type']})")
        if ctx.report.fallback:
            lines += ["", "AUTOMATICALLY MATCHED REFERENCES", sub]
            for row in ctx.report.fallback:
                lines.append(f"  - {row['Report table']}[{row['Report field']}] -> {row['Matched model table']}[{row['Matched model field']}]")

    if health_findings or health_filter_scope is not None:
        lines += ["", "MODEL HEALTH", sub]
        unfiltered = (health_filter_scope is not None and health_filter_scope.rule_ids is None
                      and health_filter_scope.severities is None)
        if not unfiltered:
            lines.extend(f"{label}: {value}" for label, value in health_scope_rows(health_filter_scope))
        if not health_findings:
            lines.append("No health findings included in this report.")
        else:
            lines.extend(_health_lines(health_findings, ctx))

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
