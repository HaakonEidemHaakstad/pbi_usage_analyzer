"""Generate a large synthetic PBIP project for performance checks.

The model is deterministic and has no ground-truth expectations; it exercises
parser, graph and classification scaling (qualified/unqualified DAX, calculated
columns, relationships, M partitions, visuals). It is generated on demand into a
temporary folder and is not part of the committed validation corpus.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import time


def build_large_project(root: Path, *, tables: int = 40, columns: int = 50, measures: int = 25,
                        calculated: int = 5, visuals: int = 200) -> Path:
    name = "large_model"
    project = root / name
    model = project / f"{name}.SemanticModel" / "definition"
    report = project / f"{name}.Report" / "definition"
    (model / "tables").mkdir(parents=True, exist_ok=True)
    (report / "pages").mkdir(parents=True, exist_ok=True)
    (project / f"{name}.pbip").write_text("{}", encoding="utf-8")
    (report / "report.json").write_text('{"version": "synthetic"}', encoding="utf-8")

    for t in range(tables):
        lines = [f"table T{t}"]
        for c in range(columns):
            lines += [f"    column C{c}", "        dataType: double", f"        sourceColumn: C{c}"]
        for k in range(calculated):
            lines += [f"    column 'Calc {k}' = [C{k}] * [C{k + 1}]", "        dataType: double"]
        other = (t + 1) % tables
        for m in range(measures):
            if m % 4 == 0:
                expression = f"SUM('T{t}'[C{m % columns}])"
            elif m % 4 == 1:
                expression = f"SUMX(T{other}, [C{(m + 3) % columns}])"
            elif m % 4 == 2:
                expression = f"VAR x = [M{t}_{m - 1}] // prior\n            RETURN x + [M{t}_{m - 2}]"
            else:
                expression = f"CALCULATE([M{other}_{m - 3}], T{t}[C{m % columns}] > 0)"
            if "\n" in expression:
                lines += [f"    measure M{t}_{m} =", f"            {expression}"]
            else:
                lines.append(f"    measure M{t}_{m} = {expression}")
            lines.append("        formatString: 0")
        previous = f'#"T{t - 1}"' if t else "Source"
        lines += [f"    partition T{t} = m", "        mode: import", "        source =", "            let",
                  '                Source = Csv.Document(File.Contents("data.csv")),',
                  f"                Combined = Table.Combine({{{previous}}})" if t else "                Combined = Source",
                  "            in", "                Combined"]
        (model / "tables" / f"T{t}.tmdl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    relationships = []
    for t in range(1, tables):
        relationships += [f"relationship r{t}", f"    fromColumn: T{t}.C0", f"    toColumn: T{t - 1}.C1", ""]
    (model / "relationships.tmdl").write_text("\n".join(relationships), encoding="utf-8")

    page = report / "pages" / "Page1"
    page.mkdir(parents=True, exist_ok=True)
    (page / "page.json").write_text('{"name": "Page1"}', encoding="utf-8")
    for v in range(visuals):
        t = v % tables
        field = ({"Measure": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": f"M{t}_{v % measures}"}}
                 if v % 2 else
                 {"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": f"C{v % columns}"}})
        data = {"query": {"Commands": [{"SemanticQueryDataShapeCommand": {"Query": {
            "From": [{"Name": "s", "Entity": f"T{t}", "Type": 0}], "Select": [field]}}}]}}
        folder = page / "visuals" / f"V{v}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "visual.json").write_text(json.dumps(data), encoding="utf-8")
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and time analysis of a large synthetic model.")
    parser.add_argument("output", nargs="?", help="Folder to generate into (default: temporary)")
    parser.add_argument("--tables", type=int, default=40)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pbi_usage_analyzer import analyze_project

    with tempfile.TemporaryDirectory() as folder:
        project = build_large_project(Path(args.output or folder), tables=args.tables)
        timings = []
        for _ in range(args.repeat):
            start = time.perf_counter()
            result = analyze_project(project)
            timings.append(time.perf_counter() - start)
    statuses = Counter(f.status.value for f in result.findings)
    print(f"Objects: {len(result.graph.objects)}  Evidence: {len(result.graph.evidence)}")
    print("Statuses: " + ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())))
    print("Analysis seconds (best of %d): %.2f" % (args.repeat, min(timings)))


if __name__ == "__main__":
    main()
