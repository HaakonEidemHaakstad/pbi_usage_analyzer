"""Build a deliberately messy multi-source package from the AdventureWorks course CSVs.

The package feeds a Power BI case study full of known bad practices (see
docs/CASE_STUDY_ADVENTUREWORKS.md). It spreads the same business data across
MariaDB, Excel, CSV and JSON with inconsistent naming, duplicated lookups,
per-year splits and staging tables. The raw data is course material and is not
stored in the repository; this script regenerates the package from a local copy.

Usage:
    python tools/casestudy/adventureworks_mess.py RAW_DIR [--out OUT_DIR]

RAW_DIR is the "AdventureWorks Raw Data" folder. Output defaults to
~/Desktop/AW_case_sources. Existing output is replaced only with --force.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys

from openpyxl import Workbook
from openpyxl.styles import Font

RAW_FILES = {
    "calendar": "AdventureWorks Calendar Lookup.csv",
    "customers": "AdventureWorks Customer Lookup.csv",
    "categories": "AdventureWorks Product Categories Lookup.csv",
    "products": "AdventureWorks Product Lookup.csv",
    "subcategories": "AdventureWorks Product Subcategories Lookup.csv",
    "returns": "AdventureWorks Returns Data.csv",
    "sales_2020": "AdventureWorks Sales Data 2020.csv",
    "sales_2021": "AdventureWorks Sales Data 2021.csv",
    "sales_2022": "AdventureWorks Sales Data 2022.csv",
    "territories": "AdventureWorks Territory Lookup.csv",
    "unpivot_demo": "Product Category Sales (Unpivot Demo).csv",
}
# The customer file is ISO-8859-1 in the course material; everything else is ASCII.
RAW_ENCODING = {"customers": "latin-1"}
UNRELATED = Path("..") / "Largest companies" / "Largest companies.csv"
BATCH = 500


def read_csv(path: Path, encoding: str = "utf-8") -> list[dict[str, str]]:
    with path.open(encoding=encoding, newline="") as handle:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def load_raw(raw_dir: Path) -> dict[str, list[dict[str, str]]]:
    missing = [name for name in RAW_FILES.values() if not (raw_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing raw files in {raw_dir}: {', '.join(missing)}")
    return {key: read_csv(raw_dir / name, RAW_ENCODING.get(key, "utf-8")) for key, name in RAW_FILES.items()}


# --- MariaDB ------------------------------------------------------------------

def sql_literal(value: str | None, *, numeric: bool = False, dialect: str = "mariadb") -> str:
    if value is None or value == "":
        return "NULL"
    if numeric:
        float(value)  # reject non-numeric input early
        return value
    text = value.replace("'", "''")
    if dialect == "mariadb":
        text = text.replace("\\", "\\\\")
    return f"'{text}'"


# (table, columns as (name, mariadb type, numeric?)), deliberately inconsistent with the CSVs.
SALES_COLUMNS = [
    ("order_date", "DATE", False), ("stock_date", "DATE", False), ("order_number", "VARCHAR(20)", False),
    ("product_key", "INT", True), ("customer_key", "INT", True), ("territory_key", "INT", True),
    ("order_line_item", "INT", True), ("order_quantity", "INT", True),
]
TABLES = {
    "sales_2021": SALES_COLUMNS,
    "sales_2022": SALES_COLUMNS,
    # Only rows with integer keys; no primary key declared (nobody added one).
    "customers": [
        ("customer_key", "INT", True), ("prefix", "VARCHAR(10)", False), ("first_name", "VARCHAR(50)", False),
        ("last_name", "VARCHAR(50)", False), ("birth_date", "DATE", False), ("marital_status", "CHAR(1)", False),
        ("gender", "CHAR(1)", False), ("email_address", "VARCHAR(100)", False), ("annual_income", "INT", True),
        ("total_children", "INT", True), ("education_level", "VARCHAR(40)", False),
        ("occupation", "VARCHAR(40)", False), ("home_owner", "CHAR(1)", False),
    ],
    # Staging copy: every column is text, dates in US format, as landed by an "ETL".
    "stg_customers_raw": [
        ("CUSTOMERKEY", "VARCHAR(20)", False), ("FULL_NAME_RAW", "VARCHAR(120)", False),
        ("BIRTHDATE_TXT", "VARCHAR(20)", False), ("INCOME_TXT", "VARCHAR(20)", False),
        ("EMAIL", "VARCHAR(100)", False), ("LOADED_BY", "VARCHAR(40)", False),
    ],
    # Thin duplicate of the Excel product master.
    "dim_product": [
        ("product_key", "INT", True), ("product_subcategory_key", "INT", True), ("product_name", "VARCHAR(100)", False),
        ("product_cost", "DECIMAL(10,4)", True), ("product_price", "DECIMAL(10,4)", True),
    ],
    # Territory key stored as text, unlike every sales table.
    "territories": [
        ("territory_key", "VARCHAR(10)", False), ("region", "VARCHAR(40)", False),
        ("country", "VARCHAR(40)", False), ("continent", "VARCHAR(40)", False),
    ],
    "etl_log": [
        ("run_id", "INT", True), ("started_at", "DATETIME", False), ("job_name", "VARCHAR(60)", False),
        ("rows_loaded", "INT", True), ("status", "VARCHAR(20)", False),
    ],
}
PRIMARY_KEYS = {"dim_product": "product_key", "etl_log": "run_id"}

VIEWS = {
    # Wide denormalized "reporting" view: most columns will never be used.
    "v_sales_report": """
SELECT s.order_date, s.stock_date, s.order_number, s.order_line_item, s.order_quantity,
       s.product_key, p.product_name, p.product_subcategory_key, p.product_cost, p.product_price,
       s.order_quantity * p.product_price AS revenue,
       s.order_quantity * p.product_cost AS cost,
       s.customer_key, c.prefix, c.first_name, c.last_name, c.birth_date, c.marital_status, c.gender,
       c.email_address, c.annual_income, c.total_children, c.education_level, c.occupation, c.home_owner,
       s.territory_key, t.region, t.country, t.continent
FROM sales_2022 s
LEFT JOIN dim_product p ON p.product_key = s.product_key
LEFT JOIN customers c ON c.customer_key = s.customer_key
LEFT JOIN territories t ON t.territory_key = CAST(s.territory_key AS CHAR(10))""",
    # Pre-aggregated duplicate of the fact data, at month grain.
    "v_sales_by_month": """
SELECT {year} AS order_year, {month} AS order_month, territory_key, SUM(order_quantity) AS quantity
FROM (SELECT order_date, territory_key, order_quantity FROM sales_2021
      UNION ALL
      SELECT order_date, territory_key, order_quantity FROM sales_2022) s
GROUP BY {year}, {month}, territory_key""",
}
# The SQLite dialect exists only so tests can execute the generated data and views.
DATE_PARTS = {"mariadb": ("YEAR(order_date)", "MONTH(order_date)"),
              "sqlite": ("CAST(strftime('%Y', order_date) AS INTEGER)", "CAST(strftime('%m', order_date) AS INTEGER)")}


def schema_sql(dialect: str = "mariadb") -> str:
    lines = ["-- AdventureWorks case study: operational database (deliberately messy).", ""]
    if dialect == "mariadb":
        lines += ["CREATE DATABASE IF NOT EXISTS aw_ops CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                  "USE aw_ops;", ""]
    for table, columns in TABLES.items():
        lines.append(f"DROP TABLE IF EXISTS {table};")
        body = [f"    {name} {kind if dialect == 'mariadb' else 'TEXT' if not numeric else 'NUMERIC'}"
                for name, kind, numeric in columns]
        if table in PRIMARY_KEYS:
            body.append(f"    PRIMARY KEY ({PRIMARY_KEYS[table]})")
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if dialect == "mariadb" else ""
        lines.append(f"CREATE TABLE {table} (\n" + ",\n".join(body) + f"\n){suffix};")
        lines.append("")
    return "\n".join(lines)


def views_sql(dialect: str = "mariadb") -> str:
    year, month = DATE_PARTS[dialect]
    lines = ["-- Reporting views.", ""] + (["USE aw_ops;", ""] if dialect == "mariadb" else [])
    for name, body in VIEWS.items():
        lines += [f"DROP VIEW IF EXISTS {name};",
                  f"CREATE VIEW {name} AS{body.format(year=year, month=month)};", ""]
    return "\n".join(lines)


def insert_statements(table: str, rows: list[list[str | None]], dialect: str) -> list[str]:
    columns = TABLES[table]
    names = ", ".join(name for name, _, _ in columns)
    statements = []
    for start in range(0, len(rows), BATCH):
        values = ",\n".join(
            "(" + ", ".join(sql_literal(v, numeric=numeric, dialect=dialect)
                            for v, (_, _, numeric) in zip(row, columns)) + ")"
            for row in rows[start:start + BATCH])
        statements.append(f"INSERT INTO {table} ({names}) VALUES\n{values};")
    return statements


def _is_int(value: str) -> bool:
    return value.isdigit()


def us_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{int(month)}/{int(day)}/{year}"


def table_rows(raw: dict[str, list[dict[str, str]]]) -> dict[str, list[list[str | None]]]:
    sales = lambda rows: [[r["OrderDate"], r["StockDate"], r["OrderNumber"], r["ProductKey"], r["CustomerKey"],
                           r["TerritoryKey"], r["OrderLineItem"], r["OrderQuantity"]] for r in rows]
    customers = [[r["CustomerKey"] or None, r["Prefix"], r["FirstName"].title(), r["LastName"].title(),
                  r["BirthDate"], r["MaritalStatus"], r["Gender"], r["EmailAddress"], r["AnnualIncome"],
                  r["TotalChildren"], r["EducationLevel"], r["Occupation"], r["HomeOwner"]]
                 for r in raw["customers"] if _is_int(r["CustomerKey"])]
    # Staging keeps the export's junk and footer rows (non-numeric keys) as landed.
    staging = [[r["CustomerKey"], f"{r['Prefix']} {r['FirstName']} {r['LastName']}".strip(),
                us_date(r["BirthDate"]) if r["BirthDate"][:4].isdigit() else r["BirthDate"], f"${r['AnnualIncome']}" if r["AnnualIncome"] else "",
                r["EmailAddress"].upper(), "nightly_import.py"] for r in raw["customers"]]
    products = [[r["ProductKey"], r["ProductSubcategoryKey"], r["ProductName"], r["ProductCost"], r["ProductPrice"]]
                for r in raw["products"]]
    territories = [[r["SalesTerritoryKey"], r["Region"], r["Country"], r["Continent"]] for r in raw["territories"]]
    etl_log = [[str(i + 1), f"2022-12-{i + 1:02d} 02:00:00", job, str(n), status] for i, (job, n, status) in enumerate([
        ("load_sales_2021", len(raw["sales_2021"]), "OK"), ("load_sales_2022", len(raw["sales_2022"]), "OK"),
        ("load_customers", len(raw["customers"]), "WARN junk rows"), ("load_products", len(raw["products"]), "OK")])]
    return {"sales_2021": sales(raw["sales_2021"]), "sales_2022": sales(raw["sales_2022"]), "customers": customers,
            "stg_customers_raw": staging, "dim_product": products, "territories": territories, "etl_log": etl_log}


def data_sql(raw: dict[str, list[dict[str, str]]], dialect: str = "mariadb") -> str:
    lines = ["-- Data. Generated from the AdventureWorks course CSVs.", ""]
    if dialect == "mariadb":
        lines += ["USE aw_ops;", "SET NAMES utf8mb4;", ""]
    for table, rows in table_rows(raw).items():
        lines += insert_statements(table, rows, dialect) + [""]
    return "\n".join(lines)


# --- Excel --------------------------------------------------------------------

def _bold(cell) -> None:
    cell.font = Font(bold=True)


def product_master(raw: dict[str, list[dict[str, str]]], path: Path) -> None:
    wb = Workbook()
    notes = wb.active
    notes.title = "Read me"
    for line in ["Product master - maintained by hand by the category team.",
                 "Do NOT sort the Products sheet. Prices on the Products sheet are the 'official' ones.",
                 "Discontinued products are kept on their own sheet (some keys also appear on Products)."]:
        notes.append([line])

    sheet = wb.create_sheet("Products")
    sheet.append(["AdventureWorks product master"])
    _bold(sheet["A1"])
    sheet.append(["Exported from the old ERP. Last manual update: see Read me."])
    sheet.append([])
    header = ["ProductKey", "Subcategory", "SKU", "Product Name", "Model", "Description", "Colour", "Size",
              "Style", "Cost", "Price"]
    sheet.append(header)
    for r in raw["products"]:
        # Prices as text with a currency symbol; size "0" meaning "no size".
        sheet.append([int(r["ProductKey"]), int(r["ProductSubcategoryKey"]), r["ProductSKU"], r["ProductName"],
                      r["ModelName"], r["ProductDescription"], r["ProductColor"], r["ProductSize"],
                      r["ProductStyle"], float(r["ProductCost"]), f"${float(r['ProductPrice']):,.2f}"])

    discontinued = wb.create_sheet("Discontinued")
    discontinued.append(header[:4] + ["Last Price"])
    for r in raw["products"][:: max(1, len(raw["products"]) // 12)][:12]:
        discontinued.append([int(r["ProductKey"]), int(r["ProductSubcategoryKey"]), r["ProductSKU"],
                             r["ProductName"] + " (old)", round(float(r["ProductPrice"]) * 0.8, 2)])

    subcategories = wb.create_sheet("Subcategories")
    subcategories.append(["ProductSubcategoryKey", "SubcategoryName", "ProductCategoryKey"])
    for r in raw["subcategories"]:
        subcategories.append([int(r["ProductSubcategoryKey"]), r["SubcategoryName"], int(r["ProductCategoryKey"])])

    categories = wb.create_sheet("Categories")
    categories.append(["ProductCategoryKey", "CategoryName"])
    for r in raw["categories"]:
        categories.append([int(r["ProductCategoryKey"]), r["CategoryName"]])
    wb.save(path)


def returns_workbook(raw: dict[str, list[dict[str, str]]], path: Path) -> list[str]:
    wb = Workbook()
    wb.remove(wb.active)
    years = sorted({r["ReturnDate"][:4] for r in raw["returns"]})
    for year in years:
        sheet = wb.create_sheet(year)
        sheet.append([f"Returns {year}"])
        _bold(sheet["A1"])
        sheet.append([])
        sheet.append(["Return Date", "Territory", "Product", "Qty"])
        rows = [r for r in raw["returns"] if r["ReturnDate"].startswith(year)]
        for r in rows:
            sheet.append([r["ReturnDate"], int(r["TerritoryKey"]), int(r["ProductKey"]), int(r["ReturnQuantity"])])
        # A totals row inside the data range.
        sheet.append(["TOTAL", None, None, sum(int(r["ReturnQuantity"]) for r in rows)])
    summary = wb.create_sheet("Summary")
    summary.append(["Year", "Returned units"])
    for year in years:
        summary.append([int(year), sum(int(r["ReturnQuantity"]) for r in raw["returns"] if r["ReturnDate"].startswith(year))])
    wb.save(path)
    return years


# --- JSON / CSV ---------------------------------------------------------------

def territories_json(raw: dict[str, list[dict[str, str]]]) -> dict:
    continents: dict[str, dict[str, list[dict]]] = {}
    for r in raw["territories"]:
        continents.setdefault(r["Continent"], {}).setdefault(r["Country"], []).append(
            {"key": int(r["SalesTerritoryKey"]), "region": r["Region"]})
    return {"exportedFrom": "territory-service", "schemaVersion": 2, "continents": [
        {"name": continent, "countries": [{"name": country, "regions": regions} for country, regions in countries.items()]}
        for continent, countries in continents.items()]}


def categories_json(raw: dict[str, list[dict[str, str]]]) -> list[dict]:
    # A second source of truth for categories that disagrees with Excel on one name.
    rename = {"Clothing": "Apparel"}
    return [{"id": int(r["ProductCategoryKey"]), "name": rename.get(r["CategoryName"], r["CategoryName"])}
            for r in raw["categories"]]


def write_csvs(raw_dir: Path, raw: dict[str, list[dict[str, str]]], out: Path) -> None:
    archive = out / "csv" / "sales_archive"
    archive.mkdir(parents=True)
    shutil.copyfile(raw_dir / RAW_FILES["sales_2020"], archive / "AdventureWorks Sales Data 2020.csv")
    # A byte-identical copy someone left in the folder: combining the folder double counts 2020.
    shutil.copyfile(raw_dir / RAW_FILES["sales_2020"], archive / "AdventureWorks Sales Data 2020 - Copy.csv")
    for key, name in (("calendar", "Calendar Lookup.csv"), ("unpivot_demo", "Product Category Sales (Unpivot Demo).csv")):
        shutil.copyfile(raw_dir / RAW_FILES[key], out / "csv" / name)
    # Kept in its original ISO-8859-1 encoding.
    shutil.copyfile(raw_dir / RAW_FILES["customers"], out / "csv" / "Customer Lookup (latin1).csv")
    unrelated = raw_dir / UNRELATED
    if unrelated.is_file():
        shutil.copyfile(unrelated, out / "csv" / "Largest companies.csv")


WINDOWS_README = """AdventureWorks bad-practice case study - source package
=========================================================

Copy this whole folder to C:\\AWCase on the Windows PC (the case study guide
assumes that path; hard-coding it is one of the bad practices).

MariaDB (run on the Windows PC):
  1. Install MariaDB Server and MariaDB Connector/ODBC (64-bit).
  2. mysql -u root -p < mariadb\\01_schema.sql
     mysql -u root -p < mariadb\\02_data.sql
     mysql -u root -p < mariadb\\03_views.sql
  3. Create a read-only user for Power BI, e.g.
     CREATE USER 'pbi_reader'@'localhost' IDENTIFIED BY '<choose a password>';
     GRANT SELECT ON aw_ops.* TO 'pbi_reader'@'localhost';

Contents: see manifest.json. Build steps: docs/CASE_STUDY_ADVENTUREWORKS.md in
the analyzer repository.
"""


def build(raw_dir: Path, out: Path) -> dict:
    raw = load_raw(raw_dir)
    (out / "mariadb").mkdir(parents=True)
    (out / "excel").mkdir()
    (out / "json").mkdir()
    (out / "mariadb" / "01_schema.sql").write_text(schema_sql(), encoding="utf-8")
    (out / "mariadb" / "02_data.sql").write_text(data_sql(raw), encoding="utf-8")
    (out / "mariadb" / "03_views.sql").write_text(views_sql(), encoding="utf-8")
    product_master(raw, out / "excel" / "Product Master.xlsx")
    years = returns_workbook(raw, out / "excel" / "Returns by Year.xlsx")
    (out / "json" / "territories.json").write_text(json.dumps(territories_json(raw), indent=2), encoding="utf-8")
    (out / "json" / "product_categories.json").write_text(json.dumps(categories_json(raw), indent=2), encoding="utf-8")
    write_csvs(raw_dir, raw, out)
    (out / "README_WINDOWS.txt").write_text(WINDOWS_README, encoding="utf-8")
    manifest = {
        "mariadb": {table: len(rows) for table, rows in table_rows(raw).items()},
        "views": sorted(VIEWS),
        "excel": {"Product Master.xlsx": ["Read me", "Products", "Discontinued", "Subcategories", "Categories"],
                  "Returns by Year.xlsx": years + ["Summary"]},
        "csv": sorted(p.relative_to(out / "csv").as_posix() for p in (out / "csv").rglob("*.csv")),
        "json": ["product_categories.json", "territories.json"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def replace_output(out: Path, force: bool) -> bool:
    """Clear an existing output folder for regeneration; False if it must be kept.

    A hand-built Power BI project inside the folder is never deleted, even with
    --force: projects belong in their own folder (C:\\AWProjects in the guide).
    """
    if not out.exists():
        return True
    projects = sorted(out.rglob("*.pbip"))
    if projects:
        print(f"{out} contains a Power BI project ({projects[0]}); refusing to replace it. "
              "Move the project elsewhere first.", file=sys.stderr)
        return False
    if not force:
        print(f"{out} exists; pass --force to replace it.", file=sys.stderr)
        return False
    shutil.rmtree(out)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw_dir", type=Path, help='The "AdventureWorks Raw Data" folder')
    parser.add_argument("--out", type=Path, default=Path.home() / "Desktop" / "AW_case_sources")
    parser.add_argument("--force", action="store_true", help="Replace an existing output folder")
    args = parser.parse_args(argv)
    out = args.out.expanduser().resolve()
    if not replace_output(out, args.force):
        return 2
    manifest = build(args.raw_dir.expanduser(), out)
    print(f"Wrote {out}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
