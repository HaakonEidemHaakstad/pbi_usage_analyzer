from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def visual_column(table: str, field: str) -> dict:
    return {
        "query": {
            "Commands": [
                {
                    "SemanticQueryDataShapeCommand": {
                        "Query": {
                            "Version": 2,
                            "From": [{"Name": "s", "Entity": table, "Type": 0}],
                            "Select": [
                                {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "s"}},
                                        "Property": field,
                                    },
                                    "Name": f"{table}.{field}",
                                }
                            ],
                        }
                    }
                }
            ]
        }
    }


def visual_measure(table: str, measure: str) -> dict:
    return {
        "query": {
            "Commands": [
                {
                    "SemanticQueryDataShapeCommand": {
                        "Query": {
                            "Version": 2,
                            "From": [{"Name": "s", "Entity": table, "Type": 0}],
                            "Select": [
                                {
                                    "Measure": {
                                        "Expression": {"SourceRef": {"Source": "s"}},
                                        "Property": measure,
                                    },
                                    "Name": f"{table}.{measure}",
                                }
                            ],
                        }
                    }
                }
            ]
        }
    }


def visual_hierarchy(table: str, hierarchy: str) -> dict:
    return {
        "query": {
            "Commands": [
                {
                    "SemanticQueryDataShapeCommand": {
                        "Query": {
                            "Version": 2,
                            "From": [{"Name": "s", "Entity": table, "Type": 0}],
                            "Select": [
                                {
                                    "Hierarchy": {
                                        "Expression": {"SourceRef": {"Source": "s"}},
                                        "Property": hierarchy,
                                    },
                                    "Name": f"{table}.{hierarchy}",
                                }
                            ],
                        }
                    }
                }
            ]
        }
    }


def project(root: Path, name: str) -> tuple[Path, Path, Path]:
    p = root / name
    report = p / f"{name}.Report"
    model = p / f"{name}.SemanticModel"
    (report / "definition" / "pages").mkdir(parents=True, exist_ok=True)
    (model / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    write_json(p / f"{name}.pbip", {})
    write_json(report / "definition" / "report.json", {"version": "synthetic"})
    return p, report, model


def add_visual(report: Path, page: str, visual: str, data: dict) -> None:
    write_json(report / "definition" / "pages" / page / "page.json",
               {"name": page, "displayName": page})
    write_json(report / "definition" / "pages" / page / "visuals" / visual / "visual.json", data)


def save_expected(p: Path, expected: dict, notes: str) -> None:
    write_json(p / "expected.json", {
        "expected_status": expected,
        "notes": notes,
    })


def build_direct_visual(root: Path):
    name = "01_direct_visual"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        dataType: double
        sourceColumn: Amount

    column Unused
        dataType: string
        sourceColumn: Unused
""")
    add_visual(report, "Page1", "Visual1", visual_column("Sales", "Amount"))
    save_expected(p, {
        "Column|Sales|Amount": "Used",
        "Column|Sales|Unused": "Likely unused",
    }, "Direct PBIR column use must protect Amount only.")


def build_dax_transitive(root: Path):
    name = "02_dax_transitive"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        dataType: double
        sourceColumn: Amount

    column Unused
        dataType: string
        sourceColumn: Unused

    measure 'Measure A' = [Measure B]

    measure 'Measure B' = SUM('Sales'[Amount])
""")
    add_visual(report, "Page1", "Visual1", visual_measure("Sales", "Measure A"))
    save_expected(p, {
        "Measure|Sales|Measure A": "Used",
        "Measure|Sales|Measure B": "Used",
        "Column|Sales|Amount": "Used",
        "Column|Sales|Unused": "Likely unused",
    }, "Usage must propagate Visual -> Measure A -> Measure B -> Amount.")


def build_relationship(root: Path):
    name = "03_relationship_only"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Dim.tmdl", """
table Dim
    column Key
        dataType: int64
        sourceColumn: Key

    column Label
        dataType: string
        sourceColumn: Label
""")
    write(model / "definition" / "tables" / "Fact.tmdl", """
table Fact
    column Key
        dataType: int64
        sourceColumn: Key

    column Value
        dataType: double
        sourceColumn: Value
""")
    write(model / "definition" / "relationships.tmdl", """
relationship Rel1
    fromColumn: Fact.Key
    toColumn: Dim.Key
""")
    save_expected(p, {
        "Column|Dim|Key": "Used",
        "Column|Fact|Key": "Used",
        "Column|Dim|Label": "Likely unused",
        "Column|Fact|Value": "Likely unused",
    }, "Relationship endpoints are used even without report references.")


def build_sort_by(root: Path):
    name = "04_sort_by"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Dim.tmdl", """
table Dim
    column Label
        dataType: string
        sourceColumn: Label
        sortByColumn: SortOrder

    column SortOrder
        dataType: int64
        sourceColumn: SortOrder

    column Unused
        dataType: string
        sourceColumn: Unused
""")
    add_visual(report, "Page1", "Visual1", visual_column("Dim", "Label"))
    save_expected(p, {
        "Column|Dim|Label": "Used",
        "Column|Dim|SortOrder": "Used",
        "Column|Dim|Unused": "Likely unused",
    }, "A used display column must propagate use to its sort-by column.")


def build_hierarchy(root: Path):
    name = "05_hierarchy"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Dates.tmdl", """
table Dates
    column Year
        dataType: int64
        sourceColumn: Year

    column Month
        dataType: string
        sourceColumn: Month

    column Unused
        dataType: string
        sourceColumn: Unused

    hierarchy Calendar
        level Year
            column: Year
        level Month
            column: Month
""")
    add_visual(report, "Page1", "Visual1", visual_hierarchy("Dates", "Calendar"))
    save_expected(p, {
        "Column|Dates|Year": "Used",
        "Column|Dates|Month": "Used",
        "Column|Dates|Unused": "Likely unused",
    }, "Using a hierarchy must protect all member columns.")


def build_powerquery_append(root: Path):
    name = "06_powerquery_append"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Current.tmdl", """
table Current
    column A
        dataType: string
        sourceColumn: A

    partition Current = m
        mode: import
        source =
            let
                Source = #table({"A"}, {{"current"}}),
                Combined = Table.Combine({Source, #"Archive"})
            in
                Combined
""")
    write(model / "definition" / "tables" / "Archive.tmdl", """
table Archive
    column A
        dataType: string
        sourceColumn: A

    column B
        dataType: string
        sourceColumn: B

    partition Archive = m
        mode: import
        source =
            #table({"A", "B"}, {{"old", "x"}})
""")
    add_visual(report, "Page1", "Visual1", visual_column("Current", "A"))
    save_expected(p, {
        "Column|Current|A": "Used",
        "Column|Archive|A": "Needs manual review",
        "Column|Archive|B": "Needs manual review",
    }, "Query-level append dependency should conservatively protect Archive until column-level M lineage exists.")


def build_false_m_refs(root: Path):
    name = "07_m_false_positive_guards"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "QueryA.tmdl", """
table QueryA
    column A
        dataType: string
        sourceColumn: A

    partition QueryA = m
        mode: import
        source =
            let
                Note = "QueryB",
                // QueryB must not count as a dependency
                QueryB = 123,
                Source = #table({"A"}, {{"x"}})
            in
                Source
""")
    write(model / "definition" / "tables" / "QueryB.tmdl", """
table QueryB
    column B
        dataType: string
        sourceColumn: B
""")
    add_visual(report, "Page1", "Visual1", visual_column("QueryA", "A"))
    save_expected(p, {
        "Column|QueryA|A": "Used",
        "Column|QueryB|B": "Likely unused",
    }, "Strings, comments and local let bindings named QueryB must not create QueryA -> QueryB.")


def build_autodate_guard(root: Path):
    name = "08_autodate_scope_guard"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Date
        dataType: dateTime
        sourceColumn: Date

    column Amount
        dataType: double
        sourceColumn: Amount

    column Customer
        dataType: string
        sourceColumn: Customer
""")
    write(model / "definition" / "tables" / "LocalDateTable_test.tmdl", """
table LocalDateTable_test
    isHidden

    column Date
        dataType: dateTime
        sourceColumn: Date

    column Year
        dataType: int64
        sourceColumn: Year

    partition LocalDateTable_test = m
        mode: import
        source =
            let
                Source = Sales,
                SelectedDate = Table.SelectColumns(Source, {"Date"})
            in
                SelectedDate
""")
    save_expected(p, {
        "Column|Sales|Date": "Needs manual review",
        "Column|Sales|Amount": "Likely unused",
        "Column|Sales|Customer": "Likely unused",
        "Column|LocalDateTable_test|Date": "Internal / auto-generated",
        "Column|LocalDateTable_test|Year": "Internal / auto-generated",
    }, "Deliberate regression test: an internal LocalDateTable must not cause every Sales column to be protected. Current analyzer may fail this until auto-date/column-level M lineage is fixed.")


def build_raw_safety_net(root: Path):
    name = "09_raw_report_safety_net"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column MysteryField
        dataType: string
        sourceColumn: MysteryField

    column TrulyUnused
        dataType: string
        sourceColumn: TrulyUnused
""")
    # Deliberately not a known structured PBIR field node.
    add_visual(report, "Page1", "Visual1", {
        "customMetadata": {
            "opaqueBinding": "Sales[MysteryField]"
        }
    })
    save_expected(p, {
        "Column|Sales|MysteryField": "Needs manual review",
        "Column|Sales|TrulyUnused": "Likely unused",
    }, "Credible raw report occurrence should trigger manual review, not Used or Likely unused.")



def build_m_column_lineage(root: Path):
    name = "10_m_column_lineage"
    p, report, model = project(root, name)
    for table in ("Archive", "Current"):
        write(model / "definition" / "tables" / f"{table}.tmdl", f"""
table {table}
    column Amount
        sourceColumn: Amount
        dataType: double
    column Legacy
        sourceColumn: Legacy
        dataType: string
    column Unrelated
        sourceColumn: Unrelated
        dataType: string
""")
    write(model / "definition" / "tables" / "Combined.tmdl", """
table Combined
    column Amount
        sourceColumn: Amount
        dataType: double
    partition Combined = m
        source =
            let
                Appended = Table.Combine({Archive, Current}),
                Removed = Table.RemoveColumns(Appended, {"Legacy"}, MissingField.Ignore),
                Selected = Table.SelectColumns(Removed, {"Amount"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Combined", "Amount"))
    expected = {"Column|Combined|Amount": "Used"}
    for table in ("Archive", "Current"):
        expected.update({f"Column|{table}|Amount": "Needs manual review",
                         f"Column|{table}|Legacy": "Likely unused",
                         f"Column|{table}|Unrelated": "Likely unused"})
    save_expected(p, expected, "Supported append/remove/select lineage narrows upstream columns without claiming active use. MissingField.Ignore allows the removed column to be absent.")


def build_m_lineage_fallback(root: Path):
    name = "11_m_lineage_fallback"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Archive.tmdl", """
table Archive
    column Amount
        sourceColumn: Amount
    column HiddenInput
        sourceColumn: HiddenInput
""")
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Amount
        sourceColumn: Amount
    partition Output = m
        source =
            let
                Selected = Table.SelectColumns(Archive, {"Amount"}),
                Transformed = CustomFunction(Selected)
            in
                Transformed
""")
    save_expected(p, {"Column|Archive|Amount": "Needs manual review",
                      "Column|Archive|HiddenInput": "Needs manual review",
                      "Column|Output|Amount": "Likely unused"},
                  "Unsupported expressions must not turn a partial projection into complete lineage.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="validation_suite")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    root = Path(args.output).resolve()
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    builders = [
        build_direct_visual,
        build_dax_transitive,
        build_relationship,
        build_sort_by,
        build_hierarchy,
        build_powerquery_append,
        build_false_m_refs,
        build_autodate_guard,
        build_raw_safety_net,
        build_m_column_lineage,
        build_m_lineage_fallback,
    ]
    for builder in builders:
        builder(root)

    write_json(root / "suite_manifest.json", {
        "scenarios": [p.name for p in sorted(root.iterdir()) if p.is_dir()],
        "purpose": "Synthetic PBIP/PBIR/TMDL fixtures with explicit ground truth for static analyzer validation.",
    })
    print(f"Generated {len(builders)} validation scenarios in: {root}")


if __name__ == "__main__":
    main()
