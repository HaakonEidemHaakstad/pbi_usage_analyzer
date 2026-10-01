"""Build the well-designed "good twin" source package from the AdventureWorks course CSVs.

Same business data and source types as the bad-practice package
(adventureworks_mess.py), arranged the way a careful team would: one clean
MariaDB warehouse with keys, an Excel workbook with real Excel tables, a folder
of same-shaped yearly CSV files, and a single JSON source of truth for
categories. The Power BI build is described in docs/CASE_STUDY_GOOD_TWIN.md and
docs/CASE_STUDY_BUILD_GUIDE.md.

Usage:
    python tools/casestudy/adventureworks_good.py RAW_DIR [--out OUT_DIR] [--force]

RAW_DIR is the "AdventureWorks Raw Data" folder. Output defaults to C:\\AWGood
on Windows and ~/Desktop/AW_good_sources elsewhere.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import sys

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from adventureworks_mess import RAW_FILES, load_raw, sql_literal

DATABASE = "aw_dw"
BATCH = 500

# (table, columns as (name, mariadb type, numeric?), primary key columns)
TABLES = {
    "fact_sales": ([
        ("OrderDate", "DATE", False), ("StockDate", "DATE", False), ("OrderNumber", "VARCHAR(20)", False),
        ("OrderLineItem", "INT", True), ("ProductKey", "INT", True), ("CustomerKey", "INT", True),
        ("TerritoryKey", "INT", True), ("OrderQuantity", "INT", True),
    ], ("OrderNumber", "OrderLineItem")),
    "dim_customer": ([
        ("CustomerKey", "INT", True), ("Prefix", "VARCHAR(10)", False), ("FirstName", "VARCHAR(50)", False),
        ("LastName", "VARCHAR(50)", False), ("BirthDate", "DATE", False), ("Gender", "CHAR(1)", False),
        ("EmailAddress", "VARCHAR(100)", False), ("AnnualIncome", "INT", True),
        ("Occupation", "VARCHAR(40)", False),
    ], ("CustomerKey",)),
    "dim_territory": ([
        ("TerritoryKey", "INT", True), ("Region", "VARCHAR(40)", False),
        ("Country", "VARCHAR(40)", False), ("Continent", "VARCHAR(40)", False),
    ], ("TerritoryKey",)),
}


def table_rows(raw: dict[str, list[dict[str, str]]]) -> dict[str, list[list[str | None]]]:
    sales = [[r["OrderDate"], r["StockDate"], r["OrderNumber"], r["OrderLineItem"], r["ProductKey"],
              r["CustomerKey"], r["TerritoryKey"], r["OrderQuantity"]]
             for year in ("sales_2020", "sales_2021", "sales_2022") for r in raw[year]]
    keys = [(row[2], row[3]) for row in sales]
    if len(set(keys)) != len(keys):
        raise ValueError("OrderNumber + OrderLineItem is not unique in the sales files")
    # The customer export ends with junk/footer rows; a warehouse keeps valid keys only.
    customers = [[r["CustomerKey"], r["Prefix"].title(), r["FirstName"].title(), r["LastName"].title(),
                  r["BirthDate"] or None, r["Gender"], r["EmailAddress"].lower(), r["AnnualIncome"] or None,
                  r["Occupation"]]
                 for r in raw["customers"] if r["CustomerKey"].isdigit()]
    territories = [[r["SalesTerritoryKey"], r["Region"], r["Country"], r["Continent"]] for r in raw["territories"]]
    return {"fact_sales": sales, "dim_customer": customers, "dim_territory": territories}


def schema_sql(dialect: str = "mariadb") -> str:
    lines = ["-- AdventureWorks good twin: reporting warehouse.", ""]
    if dialect == "mariadb":
        lines += [f"CREATE DATABASE IF NOT EXISTS {DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                  f"USE {DATABASE};", ""]
    for table, (columns, key) in TABLES.items():
        body = [f"    {name} {kind if dialect == 'mariadb' else 'NUMERIC' if numeric else 'TEXT'}"
                f"{' NOT NULL' if name in key else ''}" for name, kind, numeric in columns]
        body.append(f"    PRIMARY KEY ({', '.join(key)})")
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if dialect == "mariadb" else ""
        lines += [f"DROP TABLE IF EXISTS {table};",
                  f"CREATE TABLE {table} (\n" + ",\n".join(body) + f"\n){suffix};", ""]
    return "\n".join(lines)


def data_sql(raw: dict[str, list[dict[str, str]]], dialect: str = "mariadb") -> str:
    lines = ["-- Data. Generated from the AdventureWorks course CSVs.", ""]
    if dialect == "mariadb":
        lines += [f"USE {DATABASE};", "SET NAMES utf8mb4;", ""]
    for table, rows in table_rows(raw).items():
        columns = TABLES[table][0]
        names = ", ".join(name for name, _, _ in columns)
        for start in range(0, len(rows), BATCH):
            values = ",\n".join(
                "(" + ", ".join(sql_literal(v, numeric=numeric, dialect=dialect)
                                for v, (_, _, numeric) in zip(row, columns)) + ")"
                for row in rows[start:start + BATCH])
            lines.append(f"INSERT INTO {table} ({names}) VALUES\n{values};")
        lines.append("")
    return "\n".join(lines)


def _excel_table(sheet, name: str) -> None:
    table = Table(displayName=name, ref=sheet.dimensions)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)


def product_workbook(raw: dict[str, list[dict[str, str]]], path: Path) -> None:
    wb = Workbook()
    products = wb.active
    products.title = "ProductData"
    products.append(["ProductKey", "SubcategoryKey", "SKU", "ProductName", "ModelName", "Colour", "Size",
                     "Cost", "Price"])
    for r in raw["products"]:
        products.append([int(r["ProductKey"]), int(r["ProductSubcategoryKey"]), r["ProductSKU"], r["ProductName"],
                         r["ModelName"], r["ProductColor"], r["ProductSize"], round(float(r["ProductCost"]), 4),
                         round(float(r["ProductPrice"]), 4)])
    _excel_table(products, "Products")
    subcategories = wb.create_sheet("SubcategoryData")
    subcategories.append(["SubcategoryKey", "SubcategoryName", "CategoryKey"])
    for r in raw["subcategories"]:
        subcategories.append([int(r["ProductSubcategoryKey"]), r["SubcategoryName"], int(r["ProductCategoryKey"])])
    _excel_table(subcategories, "Subcategories")
    wb.save(path)


def write_returns(raw: dict[str, list[dict[str, str]]], folder: Path) -> list[str]:
    folder.mkdir(parents=True)
    years = sorted({r["ReturnDate"][:4] for r in raw["returns"]})
    for year in years:
        with (folder / f"returns_{year}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["ReturnDate", "TerritoryKey", "ProductKey", "ReturnQuantity"])
            writer.writerows([r["ReturnDate"], r["TerritoryKey"], r["ProductKey"], r["ReturnQuantity"]]
                             for r in raw["returns"] if r["ReturnDate"].startswith(year))
    # Not data: the folder query must select the returns files only.
    (folder / "README.txt").write_text(
        "One file per year, same columns. Add a new returns_YYYY.csv each year; nothing else changes.\n",
        encoding="utf-8")
    return [f"returns/returns_{year}.csv" for year in years] + ["returns/README.txt"]


def categories_json(raw: dict[str, list[dict[str, str]]]) -> list[dict]:
    return [{"CategoryKey": int(r["ProductCategoryKey"]), "CategoryName": r["CategoryName"]}
            for r in raw["categories"]]


WINDOWS_README = """AdventureWorks good-twin case study - source package
====================================================

Location: anywhere. Power BI reads it through the SourceFolder parameter
(default C:\\AWGood), and MariaDB through the DbServer/DbName parameters.

MariaDB:
  mysql -u root -p < mariadb\\01_schema.sql
  mysql -u root -p < mariadb\\02_data.sql
  GRANT SELECT ON aw_dw.* TO 'pbi_reader'@'localhost';

Build steps: docs/CASE_STUDY_BUILD_GUIDE.md in the analyzer repository.
"""


def build(raw_dir: Path, out: Path) -> dict:
    raw = load_raw(raw_dir)
    for folder in ("mariadb", "excel", "csv", "json"):
        (out / folder).mkdir(parents=True)
    (out / "mariadb" / "01_schema.sql").write_text(schema_sql(), encoding="utf-8")
    (out / "mariadb" / "02_data.sql").write_text(data_sql(raw), encoding="utf-8")
    product_workbook(raw, out / "excel" / "Products.xlsx")
    returns = write_returns(raw, out / "csv" / "returns")
    shutil.copyfile(raw_dir / RAW_FILES["calendar"], out / "csv" / "calendar.csv")
    (out / "json" / "categories.json").write_text(json.dumps(categories_json(raw), indent=2), encoding="utf-8")
    (out / "README_WINDOWS.txt").write_text(WINDOWS_README, encoding="utf-8")
    manifest = {
        "mariadb": {table: len(rows) for table, rows in table_rows(raw).items()},
        "excel": {"Products.xlsx": {"ProductData": "Products", "SubcategoryData": "Subcategories"}},
        "csv": ["calendar.csv"] + returns,
        "json": ["categories.json"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def default_out() -> Path:
    return Path("C:/AWGood") if os.name == "nt" else Path.home() / "Desktop" / "AW_good_sources"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw_dir", type=Path, help='The "AdventureWorks Raw Data" folder')
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Replace an existing output folder")
    args = parser.parse_args(argv)
    out = (args.out or default_out()).expanduser().resolve()
    if out.exists():
        if not args.force:
            print(f"{out} exists; pass --force to replace it.", file=sys.stderr)
            return 2
        shutil.rmtree(out)
    manifest = build(args.raw_dir.expanduser(), out)
    print(f"Wrote {out}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
