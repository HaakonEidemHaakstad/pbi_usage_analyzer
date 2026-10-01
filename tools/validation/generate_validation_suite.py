from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Fixed newlines so regeneration is byte-identical on every OS.
    path.write_text(text.strip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")


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


def build_relationship_health(root: Path):
    name = "18_relationship_health"
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
    crossFilteringBehavior: bothDirections
relationship Inactive
    fromColumn: Fact.Value
    toColumn: Dim.Label
    crossFilteringBehavior: bothDirections
    isActive: false
""")
    save_expected(p, {
        "Column|Dim|Key": "Used",
        "Column|Fact|Key": "Used",
        "Column|Dim|Label": "Used",
        "Column|Fact|Value": "Used",
    }, "Relationship endpoints are used even without report references.")


    expected_path = p / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["expected_health"] = [{"rule_id": "RELATIONSHIP_BIDIRECTIONAL", "scope": "Rel1"}]
    write_json(expected_path, expected)


def build_many_to_many_health(root: Path):
    name = "19_many_to_many_health"
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
    fromCardinality: many
    toCardinality: many
relationship Inactive
    fromColumn: Fact.Value
    toColumn: Dim.Label
    fromCardinality: many
    toCardinality: many
    isActive: false
""")
    save_expected(p, {
        "Column|Dim|Key": "Used",
        "Column|Fact|Key": "Used",
        "Column|Dim|Label": "Used",
        "Column|Fact|Value": "Used",
    }, "Relationship endpoints are used even without report references.")


    expected_path = p / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["expected_health"] = [{"rule_id": "RELATIONSHIP_MANY_TO_MANY", "scope": "Rel1"}]
    write_json(expected_path, expected)


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


def build_m_rename_types(root: Path):
    name = "12_m_rename_types"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Archive.tmdl", """
table Archive
    column 'Amount display'
        sourceColumn: RawAmount
        dataType: double
    column ConversionOnly
        sourceColumn: ConversionOnly
        dataType: int64
    column Unrelated
        sourceColumn: Unrelated
        dataType: string
""")
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Amount
        sourceColumn: Amount
        dataType: double
    partition Output = m
        source =
            let
                Renamed = Table.RenameColumns(Archive, {{"RawAmount", "Amount"}}),
                Typed = Table.TransformColumnTypes(Renamed, {{"Amount", type number}, {"ConversionOnly", Int64.Type}}, "en-US"),
                Selected = Table.SelectColumns(Typed, {"Amount"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Output", "Amount"))
    save_expected(p, {"Column|Archive|Amount display": "Needs manual review",
                      "Column|Archive|ConversionOnly": "Needs manual review",
                      "Column|Archive|Unrelated": "Likely unused",
                      "Column|Output|Amount": "Used"},
                  "Rename maps output to original sourceColumn; type conversion retains operational inputs even after projection.")


def build_m_rows_and_computed(root: Path):
    name = "13_m_rows_and_computed"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Archive.tmdl", """
table Archive
    column Price
        sourceColumn: Price
    column Quantity
        sourceColumn: Quantity
    column Active
        sourceColumn: Active
    column Unrelated
        sourceColumn: Unrelated
""")
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Total
        sourceColumn: Total
    partition Output = m
        source =
            let
                Filtered = Table.SelectRows(Archive, each [Active] = true),
                Calculated = Table.AddColumn(Filtered, "Total", each [Price] * [Quantity], type number),
                Selected = Table.SelectColumns(Calculated, {"Total"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Output", "Total"))
    save_expected(p, {"Column|Archive|Price": "Needs manual review",
                      "Column|Archive|Quantity": "Needs manual review",
                      "Column|Archive|Active": "Needs manual review",
                      "Column|Archive|Unrelated": "Likely unused",
                      "Column|Output|Total": "Used"},
                  "Filter inputs and computed-column inputs survive projection; unrelated columns are not protected.")


def build_m_join_expansion(root: Path):
    name = "14_m_join_expansion"
    p, report, model = project(root, name)
    for table, columns in (("Orders", ("CustomerKey", "Amount", "UnusedOrder")),
                           ("Customers", ("Key", "Name", "UnusedCustomer"))):
        text = f"table {table}\n"
        for column in columns:
            text += f"    column {column}\n        sourceColumn: {column}\n"
        write(model / "definition" / "tables" / f"{table}.tmdl", text)
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Amount
        sourceColumn: Amount
    column CustomerName
        sourceColumn: CustomerName
    partition Output = m
        source =
            let
                Joined = Table.NestedJoin(Orders, {"CustomerKey"}, Customers, {"Key"}, "Details", JoinKind.LeftOuter),
                Expanded = Table.ExpandTableColumn(Joined, "Details", {"Name"}, {"CustomerName"}),
                Selected = Table.SelectColumns(Expanded, {"Amount", "CustomerName"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Output", "Amount"))
    add_visual(report, "Page1", "Visual2", visual_column("Output", "CustomerName"))
    save_expected(p, {"Column|Orders|CustomerKey": "Needs manual review",
                      "Column|Orders|Amount": "Needs manual review",
                      "Column|Orders|UnusedOrder": "Likely unused",
                      "Column|Customers|Key": "Needs manual review",
                      "Column|Customers|Name": "Needs manual review",
                      "Column|Customers|UnusedCustomer": "Likely unused",
                      "Column|Output|Amount": "Used",
                      "Column|Output|CustomerName": "Used"},
                  "Nested join keys survive projection and expanded aliases resolve to the right source only.")


def build_m_scalar_filtered_join(root: Path):
    name = "15_m_scalar_filtered_join"
    p, report, model = project(root, name)
    for table, columns in (("Orders", ("CustomerKey", "Region", "Amount", "UnusedOrder")),
                           ("Customers", ("Key", "Name", "UnusedCustomer"))):
        text = f"table {table}\n"
        for column in columns:
            text += f"    column {column}\n        sourceColumn: {column}\n"
        write(model / "definition" / "tables" / f"{table}.tmdl", text)
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Rounded
        sourceColumn: Rounded
    column CustomerName
        sourceColumn: CustomerName
    partition Output = m
        source =
            let
                Joined = Table.NestedJoin(Orders, {"CustomerKey"}, Customers, {"Key"}, "Details"),
                Filtered = Table.SelectRows(Joined, each Text.StartsWith(Text.Upper(Text.Trim([Region])), "N")),
                Expanded = Table.ExpandTableColumn(Filtered, "Details", {"Name"}, {"CustomerName"}),
                Calculated = Table.AddColumn(Expanded, "Rounded", each Number.Round(Number.Abs([Amount]), 2)),
                Selected = Table.SelectColumns(Calculated, {"Rounded", "CustomerName"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Output", "Rounded"))
    add_visual(report, "Page1", "Visual2", visual_column("Output", "CustomerName"))
    save_expected(p, {"Column|Orders|CustomerKey": "Needs manual review",
                      "Column|Orders|Region": "Needs manual review",
                      "Column|Orders|Amount": "Needs manual review",
                      "Column|Orders|UnusedOrder": "Likely unused",
                      "Column|Customers|Key": "Needs manual review",
                      "Column|Customers|Name": "Needs manual review",
                      "Column|Customers|UnusedCustomer": "Likely unused",
                      "Column|Output|Rounded": "Used",
                      "Column|Output|CustomerName": "Used"},
                  "Scalar function arguments and pre-expansion filter reads remain protected alongside both join keys.")


def build_m_nested_schema(root: Path):
    name = "16_m_nested_schema"
    p, report, model = project(root, name)
    for table, columns in (("Orders", ("CustomerKey", "Region", "Amount", "Discarded", "UnusedOrder")),
                           ("Customers", ("Key", "Name", "UnusedCustomer"))):
        text = f"table {table}\n"
        for column in columns:
            text += f"    column {column}\n        sourceColumn: {column}\n"
        write(model / "definition" / "tables" / f"{table}.tmdl", text)
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Rounded
        sourceColumn: Rounded
    column CustomerName
        sourceColumn: CustomerName
    partition Output = m
        source =
            let
                Joined = Table.NestedJoin(Orders, {"CustomerKey"}, Customers, {"Key"}, "Details"),
                Renamed = Table.RenameColumns(Joined, {{"Details", "Rows"}, {"Region", "Area"}}),
                Removed = Table.RemoveColumns(Renamed, {"Discarded"}),
                Projected = Table.SelectColumns(Removed, {"Rows", "Area", "Amount"}),
                Filtered = Table.SelectRows(Projected, each Text.StartsWith(Text.Upper(Text.Trim([Area])), "N")),
                Expanded = Table.ExpandTableColumn(Filtered, "Rows", {"Name"}, {"CustomerName"}),
                Calculated = Table.AddColumn(Expanded, "Rounded", each Number.Round(Number.Abs([Amount]), 2)),
                Selected = Table.SelectColumns(Calculated, {"Rounded", "CustomerName"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Output", "Rounded"))
    add_visual(report, "Page1", "Visual2", visual_column("Output", "CustomerName"))
    save_expected(p, {"Column|Orders|CustomerKey": "Needs manual review",
                      "Column|Orders|Region": "Needs manual review",
                      "Column|Orders|Amount": "Needs manual review",
                      "Column|Orders|Discarded": "Needs manual review",
                      "Column|Orders|UnusedOrder": "Likely unused",
                      "Column|Customers|Key": "Needs manual review",
                      "Column|Customers|Name": "Needs manual review",
                      "Column|Customers|UnusedCustomer": "Likely unused",
                      "Column|Output|Rounded": "Used",
                      "Column|Output|CustomerName": "Used"},
                  "Nested column identity survives schema transformations; schema requirements, predicate reads and join keys remain protected.")


def build_m_nested_types(root: Path):
    name = "17_m_nested_types"
    p, report, model = project(root, name)
    for table, columns in (("Orders", ("CustomerKey", "Region", "Amount", "Discarded", "Converted", "UnusedOrder")),
                           ("Customers", ("Key", "Name", "UnusedCustomer"))):
        text = f"table {table}\n"
        for column in columns:
            text += f"    column {column}\n        sourceColumn: {column}\n"
        write(model / "definition" / "tables" / f"{table}.tmdl", text)
    write(model / "definition" / "tables" / "Output.tmdl", """
table Output
    column Rounded
        sourceColumn: Rounded
    column CustomerName
        sourceColumn: CustomerName
    partition Output = m
        source =
            let
                Joined = Table.NestedJoin(Orders, {"CustomerKey"}, Customers, {"Key"}, "Details"),
                Renamed = Table.RenameColumns(Joined, {{"Details", "Rows"}, {"Region", "Area"}}),
                Typed = Table.TransformColumnTypes(Renamed, {{"Converted", type number}}, "en-US"),
                Removed = Table.RemoveColumns(Typed, {"Discarded"}),
                Projected = Table.SelectColumns(Removed, {"Rows", "Area", "Amount"}),
                Filtered = Table.SelectRows(Projected, each Text.StartsWith(Text.Upper(Text.Trim([Area])), "N")),
                Expanded = Table.ExpandTableColumn(Filtered, "Rows", {"Name"}, {"CustomerName"}),
                Calculated = Table.AddColumn(Expanded, "Rounded", each Number.Round(Number.Abs([Amount]), 2)),
                Selected = Table.SelectColumns(Calculated, {"Rounded", "CustomerName"})
            in
                Selected
""")
    add_visual(report, "Page1", "Visual1", visual_column("Output", "Rounded"))
    add_visual(report, "Page1", "Visual2", visual_column("Output", "CustomerName"))
    save_expected(p, {"Column|Orders|CustomerKey": "Needs manual review",
                      "Column|Orders|Region": "Needs manual review",
                      "Column|Orders|Amount": "Needs manual review",
                      "Column|Orders|Discarded": "Needs manual review",
                      "Column|Orders|Converted": "Needs manual review",
                      "Column|Orders|UnusedOrder": "Likely unused",
                      "Column|Customers|Key": "Needs manual review",
                      "Column|Customers|Name": "Needs manual review",
                      "Column|Customers|UnusedCustomer": "Likely unused",
                      "Column|Output|Rounded": "Used",
                      "Column|Output|CustomerName": "Used"},
                  "Type conversion inputs remain dependencies after projection before nested expansion; unrelated columns remain unused.")


def build_measure_descriptions(root: Path):
    p, report, model = project(root, "20_measure_descriptions")
    write(model / "definition/tables/Sales.tmdl", """
table Sales
    /// Revenue in local currency.
    /// Excludes tax.
    measure Documented = 1
    measure Missing = 2
    ///
    measure Blank = 3
    measure Legacy = 4
        description: Existing description
""")
    write(model / "definition/tables/LocalDateTable_test.tmdl", """
table LocalDateTable_test
    measure Helper = 1
""")
    save_expected(p, {
        "Measure|Sales|Documented": "Likely unused",
        "Measure|Sales|Missing": "Likely unused",
        "Measure|Sales|Blank": "Likely unused",
        "Measure|Sales|Legacy": "Likely unused",
        "Measure|LocalDateTable_test|Helper": "Internal / auto-generated",
    }, "Missing and blank descriptions are informational; documented, uncertain and internal measures are skipped.")
    expected_path = p / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["expected_health"] = [
        {"rule_id": "MEASURE_DESCRIPTION_MISSING", "scope": "Sales[Missing]"},
        {"rule_id": "MEASURE_DESCRIPTION_MISSING", "scope": "Sales[Blank]"},
    ]
    write_json(expected_path, expected)


def special_dax_project(root: Path, name: str):
    p, report, model = project(root, name)
    write(model / "definition/tables/Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column Region
        sourceColumn: Region
    column Unrelated
        sourceColumn: Unrelated
    /// Revenue total.
    measure Revenue = SUM('Sales'[Amount])
""")
    return p, report, model


def build_field_parameter(root: Path):
    p, report, model = special_dax_project(root, "21_field_parameter")
    write(model / "definition/tables/Selector.tmdl", """
table Selector
    column Label
        sourceColumn: [Value1]
    column Fields
        sourceColumn: [Value2]
        extendedProperty ParameterMetadata = {"version":3,"kind":2}
    column Order
        sourceColumn: [Value3]
    partition Selector = calculated
        source =
            {
                ("Revenue", NAMEOF('Sales'[Revenue]), 0),
                ("Region", NAMEOF('Sales'[Region]), 1)
            }
""")
    add_visual(report, "Page1", "Visual1", visual_column("Selector", "Label"))
    save_expected(p, {
        "Measure|Sales|Revenue": "Used",
        "Column|Sales|Amount": "Used",
        "Column|Sales|Region": "Used",
        "Column|Sales|Unrelated": "Likely unused",
        "Column|Selector|Label": "Used",
    }, "NAMEOF references protect measure/column targets; measure usage propagates to Amount. This fixture does not establish complete field-parameter metadata semantics.")


def build_rls(root: Path):
    p, report, model = special_dax_project(root, "22_rls")
    write(model / "definition/roles/North.tmdl", """
role North
    modelPermission: read
    tablePermission Sales = 'Sales'[Region] = "North"
""")
    save_expected(p, {
        "Column|Sales|Region": "Used",
        "Column|Sales|Unrelated": "Likely unused",
        "Measure|Sales|Revenue": "Likely unused",
        "Column|Sales|Amount": "Needs manual review",
    }, "Role-only Region is protected without report usage. Unused Revenue retains its DAX dependency as manual review.")


def build_calculation_item(root: Path):
    p, report, model = special_dax_project(root, "23_calculation_item")
    write(model / "definition/tables/Calculations.tmdl", """
table Calculations
    calculationGroup
        precedence: 10
        calculationItem North = CALCULATE('Sales'[Revenue], 'Sales'[Region] = "North")
    column Name
        dataType: string
        sourceColumn: Name
""")
    save_expected(p, {
        "Measure|Sales|Revenue": "Needs manual review",
        "Column|Sales|Amount": "Needs manual review",
        "Column|Sales|Region": "Needs manual review",
        "Column|Sales|Unrelated": "Likely unused",
    }, "Calculation-item references are credible dependencies, but item activation is not proven; keep manual review rather than claiming use.")


def build_special_dax_scope(root: Path):
    p, report, model = special_dax_project(root, "24_special_dax_scope")
    write(model / "definition/roles/North.tmdl", """
role North
    modelPermission: read
    annotation Note = "'Sales'[Unrelated]"
    tablePermission Sales = 'Sales'[Region] = "North" // 'Sales'[Unrelated]
""")
    write(model / "definition/tables/Calculations.tmdl", """
/*
role Fake
    tablePermission Sales = 'Sales'[Unrelated] = 1
*/
table Calculations
    annotation Note = "NAMEOF('Sales'[Unrelated])"
    calculationGroup
        annotation Nested =
            calculationItem Fake = 'Sales'[Unrelated]
        calculationItem Actual = 'Sales'[Revenue] + IF("'Sales'[Unrelated]" = "", 0, 1)
    column Name
        sourceColumn: Name
""")
    write(model / "definition/tables/Selector.tmdl", """
table Selector
    column Label
        sourceColumn: [Value1]
    partition Selector = calculated
        source = { ("NAMEOF('Sales'[Unrelated])", NAMEOF ('Sales'[Region]), 'Sales'[Amount]) }
""")
    save_expected(p, {
        "Column|Sales|Region": "Used",
        "Column|Sales|Amount": "Needs manual review",
        "Column|Sales|Unrelated": "Likely unused",
        "Measure|Sales|Revenue": "Needs manual review",
    }, "Only actual special expressions and NAMEOF arguments create special evidence; unrelated references, comments, strings and annotations do not promote usage.")


def build_dax_lexical_scope(root: Path):
    name = "25_dax_lexical_scope"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column Cost
        sourceColumn: Cost
    column Discount
        sourceColumn: Discount
    column Legacy
        sourceColumn: Legacy
    column 'Old Margin'
        sourceColumn: Old Margin
    column 'Commented Only'
        sourceColumn: Commented Only
    column 'Draft Source'
        sourceColumn: Draft Source

    measure Margin = ```
            // Previously SUM('Sales'[Old Margin])
            [Net] - SUM(Sales[Cost]) /* was 'Sales'[Legacy]
               before the 2024 change */
            & IF(FALSE(), "'Sales'[Legacy] ""[Old Margin]"" retired")
            ```

    measure Net =
            SUM('Sales'[Amount]) -- excludes 'Sales'[Commented Only]
            - SUM('Sales'[Discount])

    measure Draft = "unterminated 'Sales'[Draft Source]
""")
    add_visual(report, "Page1", "Visual1", visual_measure("Sales", "Margin"))
    save_expected(p, {
        "Measure|Sales|Margin": "Used",
        "Measure|Sales|Net": "Used",
        "Column|Sales|Amount": "Used",
        "Column|Sales|Cost": "Used",
        "Column|Sales|Discount": "Used",
        "Column|Sales|Legacy": "Likely unused",
        "Column|Sales|Old Margin": "Likely unused",
        "Column|Sales|Commented Only": "Likely unused",
        "Measure|Sales|Draft": "Likely unused",
        "Column|Sales|Draft Source": "Needs manual review",
    }, "DAX strings and comments do not create dependencies; genuine references around them remain transitive. An unterminated string keeps its trailing reference as evidence.")


def build_tmdl_expression_boundaries(root: Path):
    name = "26_tmdl_expression_boundaries"
    p, report, model = project(root, name)
    # Power BI Desktop writes tab-indented TMDL.
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column Cost
        sourceColumn: Cost
    column Quantity
        sourceColumn: Quantity
    column 'Folder Text'
        sourceColumn: Folder Text
    column 'Line Total' =
            // note: quantity times cost
            Sales[Quantity] * Sales[Cost]
        dataType: double
        summarizeBy: sum
    measure Margin =
            VAR label = "Margin: "
            -- status: reviewed
            RETURN SUM(Sales[Amount]) - SUMX(Sales, Sales[Line Total])
        formatString: #,0
        displayFolder: Sales[Folder Text]
        lineageTag: 0b1c
""".replace("    ", "\t"))
    add_visual(report, "Page1", "Visual1", visual_measure("Sales", "Margin"))
    save_expected(p, {
        "Measure|Sales|Margin": "Used",
        "Column|Sales|Amount": "Used",
        "Column|Sales|Line Total": "Used",
        "Column|Sales|Quantity": "Used",
        "Column|Sales|Cost": "Used",
        "Column|Sales|Folder Text": "Likely unused",
    }, "Multiline expressions continue past DAX lines containing ': ' in strings or comments; TMDL properties still end the expression.")


def build_incomplete_sources(root: Path):
    name = "27_incomplete_sources"
    p, report, model = project(root, name)
    tables = model / "definition" / "tables"
    write(tables / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column Region
        sourceColumn: Region
    column Unused
        sourceColumn: Unused
    measure Revenue = SUM(Sales[Amount])
""")
    # A leading byte-order mark must not hide the table or a visual.
    write(tables / "Dim.tmdl", "table Dim\n    column Code\n        sourceColumn: Code")
    (tables / "Dim.tmdl").write_bytes(b"\xef\xbb\xbf" + (tables / "Dim.tmdl").read_bytes())
    # Latin-1 bytes are invalid UTF-8; the damaged name cannot be matched elsewhere.
    (tables / "Other.tmdl").write_bytes(
        b"table Other\n    column Bel\xf8p\n        sourceColumn: Bel\xf8p\n"
        b"    column Plain\n        sourceColumn: Plain\n")
    add_visual(report, "Page1", "Visual1", visual_column("Sales", "Amount"))
    add_visual(report, "Page1", "Visual3", visual_column("Dim", "Code"))
    bom_visual = report / "definition/pages/Page1/visuals/Visual3/visual.json"
    bom_visual.write_bytes(b"\xef\xbb\xbf" + bom_visual.read_bytes())
    # Truncated JSON: structured parsing fails, raw text remains reviewable.
    broken = json.dumps([visual_column("Sales", "Region"), visual_measure("Sales", "Revenue")], indent=2)
    write(report / "definition/pages/Page1/visuals/Visual2/visual.json", broken[:-2])
    save_expected(p, {
        "Column|Sales|Amount": "Used",
        "Column|Sales|Region": "Needs manual review",
        "Measure|Sales|Revenue": "Needs manual review",
        "Column|Sales|Unused": "Likely unused",
        "Column|Dim|Code": "Used",
        "Column|Other|Bel\ufffdp": "Needs manual review",
        "Column|Other|Plain": "Likely unused",
    }, "Unreadable report JSON is raw-scanned for manual-review evidence; BOMs are tolerated; invalid UTF-8 TMDL is decoded with replacement and only objects with damaged names are downgraded.")


def build_dax_unqualified_columns(root: Path):
    name = "28_dax_unqualified_columns"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Quantity
        sourceColumn: Quantity
    column Price
        sourceColumn: Price
    column Amount
        sourceColumn: Amount
    column Cost
        sourceColumn: Cost
    column Region
        sourceColumn: Region
    column Unused
        sourceColumn: Unused
    column 'Line Total' = [Quantity] * [Price]
    measure Revenue = SUMX(Sales, [Amount])
    measure 'Cost Total' = SUM(Sales[Cost])
    measure Summary =
            VAR threshold = 0
            RETURN
                [Cost Total]
""")
    write(model / "definition" / "tables" / "Budget.tmdl", """
table Budget
    column Amount
        sourceColumn: Amount
""")
    write(model / "definition" / "roles" / "North.tmdl", """
role North
    modelPermission: read
    tablePermission Sales = [Region] = "North"
""")
    add_visual(report, "Page1", "Visual1", visual_column("Sales", "Line Total"))
    add_visual(report, "Page1", "Visual2", visual_measure("Sales", "Revenue"))
    add_visual(report, "Page1", "Visual3", visual_measure("Sales", "Summary"))
    save_expected(p, {
        "Column|Sales|Line Total": "Used",
        "Column|Sales|Quantity": "Used",
        "Column|Sales|Price": "Used",
        "Column|Sales|Region": "Used",
        "Measure|Sales|Summary": "Used",
        "Measure|Sales|Cost Total": "Used",
        "Column|Sales|Cost": "Used",
        "Measure|Sales|Revenue": "Used",
        "Column|Sales|Amount": "Needs manual review",
        "Column|Budget|Amount": "Likely unused",
        "Column|Sales|Unused": "Likely unused",
    }, "Unqualified columns bind to a certain row context (calculated column, RLS table); iterator row context is manual review, narrowed by the table argument. RETURN before [Measure] is not a table name.")


def build_report_measure_safety_net(root: Path):
    name = "29_report_measure_safety_net"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    measure Revenue = SUM(Sales[Amount])
    measure 'Gross Margin' = 1
    measure Total = 2
    measure Growth = 3
    measure 'Bob''s Helper' = 4
    measure Orphan = 5
    measure Structured = 6
    measure Never = 7
""")
    write(model / "definition" / "tables" / "Budget.tmdl", """
table Budget
    column Total
        sourceColumn: Total
""")
    # None of these are structured PBIR field nodes.
    add_visual(report, "Page1", "Visual1", {"customBinding": {"fieldRef": "Sales.Revenue"}})
    add_visual(report, "Page1", "Visual2", {"custom": {"entity": "Sales", "nativeName": "Gross Margin"}})
    add_visual(report, "Page1", "Visual3", {"title": "Total", "subtitle": "Revenue Growth rate"})
    add_visual(report, "Page1", "Visual4", {"expr": "CALCULATE('Sales'[Bob's Helper])"})
    add_visual(report, "Page1", "Visual5", visual_measure("Sales", "Structured"))
    add_visual(report, "Page1", "Visual6", {"label": "Orphan"})
    save_expected(p, {
        "Measure|Sales|Revenue": "Needs manual review",
        "Measure|Sales|Gross Margin": "Needs manual review",
        "Measure|Sales|Bob's Helper": "Needs manual review",
        "Measure|Sales|Structured": "Used",
        "Measure|Sales|Total": "Likely unused",
        "Measure|Sales|Growth": "Likely unused",
        "Measure|Sales|Orphan": "Likely unused",
        "Measure|Sales|Never": "Likely unused",
        "Column|Sales|Amount": "Needs manual review",
        "Column|Budget|Total": "Likely unused",
    }, "Unparsed measure references need a qualified form, or the exact name alongside its table name; titles and substrings do not protect measures.")


def build_report_column_safety_net(root: Path):
    name = "30_report_column_safety_net"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column 'Net Amount'
        sourceColumn: Net Amount
    column Region
        sourceColumn: Region
    column Code
        sourceColumn: Code
    column Year
        sourceColumn: Year
    column Notes
        sourceColumn: Notes
    column C1
        sourceColumn: C1
    column C10
        sourceColumn: C10
""")
    for table in ("Products", "Customers"):
        write(model / "definition" / "tables" / f"{table}.tmdl", f"""
table {table}
    column Name
        sourceColumn: Name
""")
    # None of these are structured PBIR field nodes.
    add_visual(report, "Page1", "Visual1", {"custom": {"queryRef": "Sum(Sales.Net Amount)"}})
    add_visual(report, "Page1", "Visual2", {"expr": "SUMX(Sales, Sales[Region])"})
    add_visual(report, "Page1", "Visual3", {"binding": {"entity": "Products", "property": "Name"}})
    add_visual(report, "Page1", "Visual4", {"visualCalc": "[Code] * 2", "source": {"entity": "Sales"}})
    add_visual(report, "Page1", "Visual5", {"title": "Year", "entity": "Sales"})
    add_visual(report, "Page1", "Visual6", {"title": "Notes about C10"})
    save_expected(p, {
        "Column|Sales|Net Amount": "Needs manual review",
        "Column|Sales|Region": "Needs manual review",
        "Column|Products|Name": "Needs manual review",
        "Column|Sales|Code": "Needs manual review",
        "Column|Sales|Year": "Needs manual review",
        "Column|Sales|Amount": "Likely unused",
        "Column|Customers|Name": "Likely unused",
        "Column|Sales|Notes": "Likely unused",
        "Column|Sales|C1": "Likely unused",
        "Column|Sales|C10": "Likely unused",
    }, "Readable report text protects a column only in a qualified form (Table.Column, Table[Column]) or as the exact name or [Name] alongside its table name; substrings, JSON keys and names without their table do not. A title equal to a column name next to its table name still counts.")


def entity_field(kind: str, table: str, name: str) -> dict:
    """Current PBIR visualContainer field: SourceRef names the entity directly."""
    key = "Hierarchy" if kind == "Hierarchy" else "Property"
    return {kind: {"Expression": {"SourceRef": {"Entity": table}}, key: name}}


def build_pbir_entity_refs(root: Path):
    name = "31_pbir_entity_refs"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column Region
        sourceColumn: Region
    column Channel
        sourceColumn: Channel
    column OrderDate
        sourceColumn: OrderDate
    column Unused
        sourceColumn: Unused
    measure Revenue = SUM(Sales[Amount])
    measure 'Filter Only' = COUNTROWS(Sales)
    measure Idle = 1
""")
    write(model / "definition" / "tables" / "Dates.tmdl", """
table Dates
    column Year
        sourceColumn: Year
    column Month
        sourceColumn: Month
    column Day
        sourceColumn: Day
    column Other
        sourceColumn: Other
    hierarchy Calendar
        level Year
            column: Year
        level Month
            column: Month
        level Day
            column: Day
""")
    level = lambda lvl: {"HierarchyLevel": {"Expression": {"Hierarchy": {
        "Expression": {"SourceRef": {"Entity": "Dates"}}, "Hierarchy": "Calendar"}}, "Level": lvl}}
    add_visual(report, "Page1", "Visual1", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.12.0/schema.json",
        "name": "Visual1",
        "visual": {"visualType": "pivotTable", "query": {"queryState": {
            "Rows": {"projections": [
                {"field": level("Month"), "queryRef": "Dates.Calendar.Month", "active": True},
                {"field": level("Day"), "queryRef": "Dates.Calendar.Day", "active": False}]},
            "Values": {"projections": [
                {"field": entity_field("Measure", "Sales", "Revenue"), "queryRef": "Sales.Revenue"}]}},
            "sortDefinition": {"sort": [{"field": entity_field("Column", "Sales", "Region"), "direction": "Ascending"}]}}},
        "filterConfig": {"filters": [
            {"name": "f1", "field": entity_field("Measure", "Sales", "Filter Only"), "type": "Advanced"},
            {"name": "f2", "field": {"Aggregation": {"Expression": entity_field("Column", "Sales", "Channel"), "Function": 0}}}]},
    })
    # Auto-date variation over a business column (shape per PBIR; not yet seen in a real sample).
    add_visual(report, "Page1", "Visual2", {"visual": {"query": {"queryState": {"Category": {"projections": [{"field": {
        "HierarchyLevel": {"Expression": {"Hierarchy": {"Expression": {"PropertyVariationSource": {
            "Expression": {"SourceRef": {"Entity": "Sales"}}, "Name": "Variation", "Property": "OrderDate"}},
            "Hierarchy": "Date Hierarchy"}}, "Level": "Year"}}}]}}}}})
    save_expected(p, {
        "Measure|Sales|Revenue": "Used",
        "Column|Sales|Amount": "Used",
        "Measure|Sales|Filter Only": "Used",
        "Column|Sales|Region": "Used",
        "Column|Sales|Channel": "Used",
        "Column|Sales|OrderDate": "Used",
        "Column|Dates|Year": "Used",
        "Column|Dates|Month": "Used",
        "Column|Dates|Day": "Used",
        "Column|Dates|Other": "Likely unused",
        "Column|Sales|Unused": "Likely unused",
        "Measure|Sales|Idle": "Likely unused",
    }, "Current PBIR visualContainer fields name the entity in SourceRef; hierarchy levels nest the hierarchy; auto-date variations reference the business column.")


def build_m_case_sensitive_refs(root: Path):
    name = "32_m_case_sensitive_refs"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Date.tmdl", """
table Date
    column Date
        sourceColumn: Date
    column Weekday
        sourceColumn: Weekday
    partition Date = m
        mode: import
        source =
                let
                    Source = Csv.Document(File.Contents("dates.csv"))
                in
                    Source
""")
    # `type date`, `Date.Year` and `#date` are M keywords/library names, not the Date query.
    write(model / "definition" / "tables" / "Returns.tmdl", """
table Returns
    column ReturnDate
        sourceColumn: ReturnDate
    partition Returns = m
        mode: import
        source =
                let
                    Kilde = Csv.Document(File.Contents("returns.csv")),
                    Typed = Table.TransformColumnTypes(Kilde, {{"ReturnDate", type date}}),
                    Added = Table.AddColumn(Typed, "Y", each Date.Year([ReturnDate]) + Date.From(#date(2024, 1, 1)))
                in
                    Added
""")
    add_visual(report, "Page1", "Visual1", visual_column("Returns", "ReturnDate"))
    save_expected(p, {
        "Column|Returns|ReturnDate": "Used",
        "Column|Date|Date": "Likely unused",
        "Column|Date|Weekday": "Likely unused",
    }, "M is case-sensitive: type keywords and library identifiers must not create a dependency on a query named Date (found in a real project).")


def build_dax_unresolved_references(root: Path):
    name = "33_dax_unresolved_references"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    column 'Bad Calc' = Sales[Nope] * 2
    /// Valid; case differs from the table name.
    measure Good = SUM('SALES'[amount])
    /// Column was renamed away.
    measure Stale = SUM('Sales'[Revenue]) + [Good]
    /// Table does not exist in the model.
    measure 'Missing Table' = SUM('Old Sales'[Amount])
    /// Keyword before a bracket, a comment and a string are not references.
    measure Clean = ```
            VAR x = 1
            RETURN [Good] + x // 'Sales'[Ghost]
                & "Sales[Ghost]"
            ```
    /// Unqualified names may be ADDCOLUMNS extension columns; not checked.
    measure Unqualified = SUMX(ADDCOLUMNS(Sales, "Rev", 1), [Rev])
""")
    save_expected(p, {
        "Column|Sales|Amount": "Needs manual review",
        "Column|Sales|Bad Calc": "Likely unused",
        "Measure|Sales|Good": "Needs manual review",
        "Measure|Sales|Stale": "Likely unused",
        "Measure|Sales|Missing Table": "Likely unused",
        "Measure|Sales|Clean": "Likely unused",
        "Measure|Sales|Unqualified": "Likely unused",
    }, "Qualified DAX references to a missing column/measure or a missing quoted table are reported; comments, strings, keywords and unqualified names are not.")
    expected_path = p / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["expected_health"] = [
        {"rule_id": "DAX_REFERENCE_UNRESOLVED", "scope": "Sales[Bad Calc]"},
        {"rule_id": "DAX_REFERENCE_UNRESOLVED", "scope": "Sales[Stale]"},
        {"rule_id": "DAX_REFERENCE_UNRESOLVED", "scope": "Sales[Missing Table]"},
    ]
    write_json(expected_path, expected)


def build_m_hardcoded_paths(root: Path):
    name = "34_m_hardcoded_paths"
    p, report, model = project(root, name)
    write(model / "definition" / "tables" / "Sales.tmdl", """
table Sales
    column Amount
        sourceColumn: Amount
    partition Sales = m
        mode: import
        source =
                let
                    // Old location: C:\\Archive\\sales.csv
                    Source = Csv.Document(File.Contents("C:\\Users\\ann\\OneDrive\\Data\\sales.csv")),
                    Note = "See https://example.com/docs",
                    Types = Table.TransformColumnTypes(Source, {{"Amount", type number}})
                in
                    Types
""")
    write(model / "definition" / "tables" / "Budget.tmdl", """
table Budget
    column Amount
        sourceColumn: Amount
    partition Budget = m
        mode: import
        source =
                let
                    Source = Csv.Document(File.Contents(DataFolder & "\\budget.csv"))
                in
                    Source
""")
    # CRLF line endings and tab indentation, as Power BI Desktop writes them.
    expressions = (
        'expression DataFolder = "D:\\Data" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        '\tlineageTag: 11111111-1111-1111-1111-111111111111\n'
        '\n'
        "expression 'Sales Archive' =\n"
        '\t\tlet\n'
        '\t\t    Files = Folder.Files("\\\\fileserver\\finance\\sales"),\n'
        '\t\t    #"C:\\not a path" = Files\n'
        '\t\tin\n'
        '\t\t    #"C:\\not a path"\n'
        '\tlineageTag: 22222222-2222-2222-2222-222222222222\n'
        '\n'
        '\tannotation PBI_ResultType = Table\n'
    ).replace("\n", "\r\n")
    (model / "definition" / "expressions.tmdl").write_bytes(expressions.encode("utf-8"))
    save_expected(p, {
        "Column|Sales|Amount": "Likely unused",
        "Column|Budget|Amount": "Likely unused",
    }, "Literal drive and UNC paths in M are reported per query; parameters, comments, quoted identifiers, URLs and relative fragments are not.")
    expected_path = p / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["expected_health"] = [
        {"rule_id": "POWERQUERY_HARDCODED_PATH", "scope": "Sales"},
        {"rule_id": "POWERQUERY_HARDCODED_PATH", "scope": "Sales Archive"},
    ]
    write_json(expected_path, expected)


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
        build_m_rename_types,
        build_m_rows_and_computed,
        build_m_join_expansion,
        build_m_scalar_filtered_join,
        build_m_nested_schema,
        build_m_nested_types,
        build_relationship_health,
        build_many_to_many_health,
        build_measure_descriptions,
        build_field_parameter,
        build_rls,
        build_calculation_item,
        build_special_dax_scope,
        build_dax_lexical_scope,
        build_tmdl_expression_boundaries,
        build_incomplete_sources,
        build_dax_unqualified_columns,
        build_report_measure_safety_net,
        build_report_column_safety_net,
        build_pbir_entity_refs,
        build_m_case_sensitive_refs,
        build_dax_unresolved_references,
        build_m_hardcoded_paths,
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
