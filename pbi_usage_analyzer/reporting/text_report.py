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
    lines += [sep, "POWER BI MODELLANALYSE V2", sep, "", f"Prosjekt: {project_name}", "", "KORT OPPSUMMERING", sub]
    lines.append(f"Den semantiske modellen inneholder {len(columns)} kolonner og {len(measures)} measures.")
    lines.append(f"{len(unused_cols)} av {len(columns)} kolonner ({pct:.1f} %) ser ikke ut til å være i bruk.")
    lines.append(f"I tillegg ser {len(unused_measures)} av {len(measures)} measures ut til å være ubrukt.")
    lines.append(f"{len(manual_cols)} kolonner og {len(manual_measures)} measures er holdt tilbake for manuell kontroll.")
    lines.append("")
    lines.append("Analysen bruker en dependency graph på tvers av PBIR, TMDL/DAX, relasjoner, hierarkier, sortering og Power Query/M.")
    lines.append("'Likely unused' betyr at ingen kjent bruk eller relevant avhengighet ble funnet. Det er fortsatt en kandidatliste, ikke en automatisk sletteliste.")

    by_table = Counter(f.ref.table for f in unused_cols)
    if by_table:
        lines += ["", "OPPRYDDINGSKANDIDATER PER TABELL", sub]
        totals = Counter(f.ref.table for f in columns if f.status != Status.INTERNAL)
        lines.append(f"{'Tabell':25} {'Ser ubrukt ut':>14} {'Totalt':>8} {'Andel':>10}")
        lines.append("-" * 62)
        for table, count in by_table.most_common():
            total = totals[table]
            share = count / total * 100 if total else 0
            lines.append(f"{table:25} {count:14d} {total:8d} {share:9.1f}%")

    if ctx.powerquery and ctx.powerquery.dependencies:
        lines += ["", "POWER QUERY / M-AVHENGIGHETER", sub]
        lines.append("Disse avhengighetene er hentet fra faktiske M-uttrykk i TMDL-partisjoner:")
        lines.append("")
        for row in ctx.powerquery.dependencies:
            lines.append(f"  - {row['Query']} <- {row['Depends on query']}")
        lines.append("")
        lines.append("Query-level M-avhengighet fra vanlige modelltabeller beskytter upstream-tabellen konservativt, men betyr ikke at alle kolonner nødvendigvis er nødvendige. Slike kolonner settes derfor til manuell kontroll, ikke 'Used'. Interne auto-date-tabeller beskytter bare konkret identifiserte kolonner; uavklarte referanser rapporteres som advarsler.")

    if unused_cols:
        lines += ["", "KOLONNER SOM IKKE SER UT TIL Å VÆRE I BRUK", sub]
        grouped = defaultdict(list)
        source_refs = {f.ref for f in source_cols}
        for f in unused_cols:
            grouped[f.ref.table].append(f)
        for table in sorted(grouped, key=str.casefold):
            table_findings = sorted(grouped[table], key=lambda f: f.ref.name.casefold())
            lines.append(f"{table} ({len(table_findings)} kolonner)")
            for finding in table_findings:
                marker = " [KILDE]" if finding.ref in source_refs else ""
                lines.append(f"  - {finding.ref.name}{marker}")
            lines.append("")

    if unused_measures:
        lines += ["MEASURES SOM IKKE SER UT TIL Å VÆRE I BRUK", sub]
        grouped = defaultdict(list)
        for f in unused_measures:
            grouped[f.ref.table].append(f.ref.name)
        for table in sorted(grouped, key=str.casefold):
            lines.append(table)
            for name in sorted(grouped[table], key=str.casefold):
                lines.append(f"  - {name}")
            lines.append("")

    if manual_cols or manual_measures:
        lines += ["FORHOLD SOM BØR KONTROLLERES", sub]
        lines.append(f"- {len(manual_cols)} kolonner bør kontrolleres manuelt.")
        lines.append(f"- {len(manual_measures)} measures bør kontrolleres manuelt.")
        lines.append("")
        for f in manual_cols:
            reason = " | ".join(f.reasons) if f.reasons else "Uavklart avhengighet"
            lines.append(f"  - {f.ref.label}: {reason}")

    if ctx.report:
        if ctx.report.stale:
            lines += ["", "MULIGE GAMLE RAPPORTREFERANSER", sub]
            for row in ctx.report.stale:
                lines.append(f"  - {row['Table']}[{row['Field']}] ({row['Type']})")
        if ctx.report.fallback:
            lines += ["", "REFERANSER SOM BLE KOBLET AUTOMATISK", sub]
            for row in ctx.report.fallback:
                lines.append(f"  - {row['Report table']}[{row['Report field']}] -> {row['Matched model table']}[{row['Matched model field']}]")

    if ctx.warnings:
        lines += ["", "ADVARSLER", sub, *ctx.warnings]

    lines += ["", "ANBEFALT NESTE STEG", sub,
              "1. Start med 'Likely unused'-objekter og fjern et mindre antall om gangen.",
              "2. Oppdater rapporten og valider visualer, filtre og beregninger etter hver runde.",
              "3. Behandle 'Needs manual review' separat; disse er med vilje holdt utenfor automatisk opprydding.",
              "4. For Power Query-kilder: vurder å fjerne bekreftet unødvendige kildekolonner tidlig dersom query folding og øvrige avhengigheter tillater det.",
              "", "FORBEHOLD", sub,
              "Dette er statisk analyse. Dynamiske eller nye Power BI-konstruksjoner kan kreve manuell kontroll.",
              "Dersom den semantiske modellen brukes av andre rapporter, kan de bruke objekter som denne rapporten ikke gjør."]
    return "\n".join(lines) + "\n"
