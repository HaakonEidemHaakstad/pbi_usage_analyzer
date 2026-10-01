# Case study: AdventureWorks, the inherited mess

A Power BI project that is deliberately built badly, from the same AdventureWorks
data spread across MariaDB, Excel, CSV and JSON. Once saved as PBIP it becomes a
scored test case for the analyzer: every bad practice has an ID, and the
[answer key](#answer-key) states what the analyzer should report today.

Build it faithfully, including the mistakes. If you deviate, note it; the answer
key is re-derived from the saved files anyway, but deviations explain surprises.

## 1. Generate the source package (Ubuntu)

The raw data is course material and is not in this repository.

```bash
.venv/bin/python tools/casestudy/adventureworks_mess.py \
    "$HOME/Desktop/AW/AdventureWorks+Raw+Data/AdventureWorks Raw Data"
```

This writes `~/Desktop/AW_case_sources` (use `--out` to change it, `--force` to
replace it). `manifest.json` lists every table, sheet and file.

On the Windows PC, generate straight into the expected location (skips the copy
in section 2, step 1):

```powershell
.\.venv\Scripts\python.exe tools\casestudy\adventureworks_mess.py "<...>\AdventureWorks+Raw+Data\AdventureWorks Raw Data" --out C:\AWCase
```

| Folder | Contents | Built-in traps |
| --- | --- | --- |
| `mariadb/` | `01_schema.sql`, `02_data.sql`, `03_views.sql` for database `aw_ops` | `sales_2021`/`sales_2022` split by year with snake_case columns; `territories.territory_key` is text; `stg_customers_raw` (all text, junk rows); `dim_product` (thin duplicate of the Excel master); `etl_log`; wide view `v_sales_report` (29 columns); aggregate view `v_sales_by_month` |
| `excel/Product Master.xlsx` | Read me, Products, Discontinued, Subcategories, Categories | Header on row 4 under title rows; prices stored as text (`$34.99`); discontinued products reuse keys |
| `excel/Returns by Year.xlsx` | 2020, 2021, 2022, Summary | One sheet per year; title rows; a `TOTAL` row inside each sheet's data |
| `csv/sales_archive/` | 2020 sales | A byte-identical `- Copy` file: combining the folder double counts 2020 |
| `csv/` | Calendar, customers (ISO-8859-1), unpivot demo, largest companies | Latin-1 encoding; a pivoted layout; an unrelated dataset; customer export junk/footer rows |
| `json/` | `territories.json` (nested), `product_categories.json` | Categories disagree with Excel (`Apparel` vs `Clothing`) |

## 2. Prepare the Windows PC

1. Copy the whole package to `C:\AWCase` (the steps below hard-code that path;
   that is bad practice BP-11).
2. Install MariaDB Server and load the database:
   `mysql -u root -p < mariadb\01_schema.sql`, then `02_data.sql`, then `03_views.sql`.
3. Create a read-only login for Power BI (choose your own password):
   `CREATE USER 'pbi_reader'@'localhost' IDENTIFIED BY '...'; GRANT SELECT ON aw_ops.* TO 'pbi_reader'@'localhost';`
4. Install the 64-bit MariaDB Connector/ODBC, which Power BI's MariaDB connector
   uses (check Microsoft's current connector documentation if it asks for another
   driver).
5. In Power BI Desktop, *Options → Preview features*: make sure projects are saved
   with **TMDL** and **PBIR** (the enhanced report format), if those are still
   options in your version.
6. *Options → Current file → Data load*: leave **Auto date/time** switched on (BP-09).

## 3. Power Query (Get Data)

Keep **Enable load** on for every query unless a step says otherwise; loading
helper queries is part of the mess.

| # | Query name | Source and steps | Bad practice |
| --- | --- | --- | --- |
| Q1 | `Sales 2020` | *Folder* `C:\AWCase\csv\sales_archive` → *Combine & Transform* | BP-02, BP-11 |
| Q2 | `sales_2021` | *MariaDB* `localhost` / `aw_ops`, table `sales_2021`; rename columns to match the CSV (`order_date` → `OrderDate`, …) | BP-01, BP-04 |
| Q3 | `sales_2022` | Same for `sales_2022`, renaming again by hand | BP-01, BP-04 |
| Q4 | `Sales` | *Append Queries as New*: Q1, Q2, Q3 | BP-01 |
| Q5 | `v_sales_report` | MariaDB view, import all columns | BP-03 |
| Q6 | `v_sales_by_month` | MariaDB view | BP-08 |
| Q7 | `customers` | MariaDB table | |
| Q8 | `Customer Lookup (latin1)` | CSV, accept the default encoding (65001 UTF-8) so accented names break; keep the junk rows | BP-05, BP-16 |
| Q9 | `stg_customers_raw` | MariaDB table | BP-04 |
| Q10 | `Products` | Excel `Product Master.xlsx`, sheet *Products*: remove top 3 rows, use first row as headers, replace `$` and change `Price` to decimal | BP-11 |
| Q11 | `dim_product` | MariaDB table | BP-05 |
| Q12 | `Subcategories` | Excel sheet *Subcategories* | |
| Q13 | `Categories` | Excel sheet *Categories* | |
| Q14 | `product_categories` | JSON file, convert to table | BP-05 |
| Q15 | `territories` | MariaDB table; keep `territory_key` as **text** | BP-06 |
| Q16 | `territories json` | JSON file, expand continents → countries → regions | BP-05 |
| Q17 | `Returns 2020`, `Returns 2021`, `Returns 2022` | One query per Excel sheet: remove top 2 rows, promote headers; **do not** remove the `TOTAL` row | BP-01, BP-13 |
| Q18 | `Returns` | Append Q17's three queries | BP-01 |
| Q19 | `Calendar` | CSV `Calendar Lookup.csv`; add columns `Year`, `Month Number`, `Month Name` and `YearMonth` (`Year * 100 + Month Number`) in Power Query | |
| Q20 | `Largest companies` | CSV | BP-14 |
| Q21 | `Product Category Sales (Unpivot Demo)` | CSV, **do not** unpivot | BP-15 |
| Q22 | `etl_log` | MariaDB table | BP-14 |

In `Sales`, change `TerritoryKey` to **text** so the relationship to `territories`
can be created (BP-06).

## 4. Model

**Relationships** (single direction, many-to-one, unless stated):

| From | To | Note |
| --- | --- | --- |
| `Sales[ProductKey]` | `Products[ProductKey]` | |
| `Sales[CustomerKey]` | `customers[customer_key]` | **Both directions** (BP-07) |
| `Sales[TerritoryKey]` | `territories[territory_key]` | Text key (BP-06) |
| `Sales[OrderDate]` | `Calendar[Date]` | |
| `Returns[Product]` | `Products[ProductKey]` | |
| `Products[Subcategory]` | `Subcategories[ProductSubcategoryKey]` | **Both directions** (BP-07) |
| `Subcategories[ProductCategoryKey]` | `Categories[ProductCategoryKey]` | |
| `v_sales_by_month[YearMonth]` | `Calendar[YearMonth]` | **Many-to-many** (BP-08); add `YearMonth = [order_year] * 100 + [order_month]` to the view query first |

Sort `Calendar[Month Name]` by `Calendar[Month Number]`.

**Measures**. Put them wherever you happen to be (BP-10: no descriptions, no
display folders, scattered across tables):

```dax
-- in Sales
Total Revenue = SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Price]))
Total Orders = DISTINCTCOUNT(Sales[OrderNumber])
Avg Quantity = AVERAGEX(Sales, [OrderQuantity])
Copy of Total Revenue = SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Price]))
Old Profit = // replaced by the view: SUM(Sales[OrderLineItem])
    SUMX(Sales, Sales[OrderQuantity] * (RELATED(Products[Price]) - RELATED(Products[Cost])))
-- in v_sales_report
Revenue (view) = SUM(v_sales_report[revenue])
-- in Returns
Total Returns = SUM(Returns[Qty])
Return Rate = DIVIDE([Total Returns], SUM(Sales[OrderQuantity]))
```

**Calculated column** in `customers` (BP-12, belongs in Power Query):
`Age = DATEDIFF(customers[birth_date], TODAY(), YEAR)`

**Calculation group** `Time Calc` with column `Calculation` and items:
`Current = SELECTEDMEASURE()` and `YTD = CALCULATE(SELECTEDMEASURE(), DATESYTD(Calendar[Date]))`.

**Field parameter** `Metric Selector` (*Modeling → New parameter → Fields*) with
`Total Revenue` and `Total Orders`.

**Role** `Europe only`: on `territories`, filter `[continent] = "Europe"`
(an unqualified column in a table permission).

## 5. Report

| Page | Visuals | What it exercises |
| --- | --- | --- |
| Overview | Cards: `Total Revenue`, `Total Orders`; card with `v_sales_report[revenue]` dragged in directly (implicit sum); line chart `Total Revenue` by `Sales[OrderDate]` using the **auto date hierarchy** (Year → Month); slicer `territories[country]` | Implicit measure; auto-date variation (BP-09) |
| Products | Matrix rows `Categories[CategoryName]` → `Subcategories[SubcategoryName]` → `Products[Product Name]`, values `Total Revenue`; background conditional formatting by `Return Rate`; visual-level filter `Products[Colour]` | Field used only in formatting; field used only in a filter |
| Customers | Table `customers[first_name]`, `customers[last_name]`, `customers[occupation]`; set as **drillthrough** on `customers[occupation]` | Drillthrough field |
| Return tooltip | Page type *Tooltip*; card `Return Rate`; assign it as the tooltip of the Products matrix | Tooltip page |
| Metrics | Slicer on `Metric Selector`; column chart of `Metric Selector` by `Calendar[Month Name]`; apply `Time Calc` as a slicer | Field parameter; calculation group; sort-by |
| Old analysis | Table of `v_sales_report[product_name]` and `v_sales_report[region]`, plus `Revenue (view)`; then **hide the page** | Hidden page still counts |

Also add a **page-level filter** on Overview: `Categories[CategoryName]` is not
`Components`, and a **report-level filter** `territories[continent]` (all selected).
Create one bookmark that hides the implicit-measure card.

Finally, *File → Save as* **Power BI project (.pbip)**, e.g. `C:\AWCase\pbip\AW Mess.pbip`,
and copy the whole `pbip` folder back to Ubuntu (for example `~/Desktop/AW_case_pbip`).
The analyzer and an independent review will then produce the actual answer key.

## Answer key

What the analyzer is expected to report for each bad practice today. "Detected"
means an existing cleanup status or health rule covers it; "Not yet" marks a
candidate rule. This is a prediction: once the PBIP exists, record the actual
expected statuses (as for `tests/integration/adventureworks_expected.json`) and
investigate every difference.

| ID | Bad practice | Expected analyzer result | Status |
| --- | --- | --- | --- |
| BP-01 | Hard-coded annual appends across three different source types (`Sales`, `Returns`) | Append dependencies `Sales → Sales 2020 / sales_2021 / sales_2022`, `Returns → Returns 20xx`; per-year query columns are **Needs manual review**, not Likely unused | Detected as lineage; `POWERQUERY_ANNUAL_APPEND` (info) on `Sales` and `Returns`; `POWERQUERY_APPEND_INPUT_LOADED` (warning) for each loaded per-year query |
| BP-02 | Folder combine includes a duplicate file (2020 counted twice) | `POWERQUERY_FOLDER_UNFILTERED` (warning) on `Sales 2020`: the folder is combined with only the default hidden-files filter. The duplicate file itself is not visible statically | Detected as a risk; actual duplicates need folder access |
| BP-03 | Wide denormalized view imported in full | `v_sales_report` columns used only by the hidden page, the implicit card and `Revenue (view)` are Used; the rest **Likely unused** | Detected (cleanup) |
| BP-04 | Staging and per-year queries loaded into the model | `stg_customers_raw` columns Likely unused; per-year sales/returns queries as BP-01 | Cleanup detected; loaded per-year queries via `POWERQUERY_APPEND_INPUT_LOADED`; no rule for a loaded but unreferenced staging query (`stg_*` name heuristics not implemented) |
| BP-05 | Duplicate/conflicting sources (`dim_product`, customers CSV, categories JSON, territories JSON) | Their columns **Likely unused** (no relationships or references) | Detected (cleanup) |
| BP-06 | Relationship on a text key | Keys **Used** (relationship endpoints); `RELATIONSHIP_TEXT_KEY` (info) on `Sales[TerritoryKey]` → `territories[territory_key]` | Detected (data type only; the key has few values, so the finding is a prompt to check, not a defect) |
| BP-07 | Bidirectional relationships | `RELATIONSHIP_BIDIRECTIONAL` (warning) ×2 | Detected |
| BP-08 | Many-to-many relationship at month grain | `RELATIONSHIP_MANY_TO_MANY` (warning) | Detected |
| BP-09 | Auto date/time on | `LocalDateTable_*`/`DateTableTemplate_*` reported as **Internal**, not cleanup candidates; the auto-date hierarchy on `Sales[OrderDate]` protects `Sales[OrderDate]` | Detected; PBIR `PropertyVariationSource` handling first verified here. No "many auto-date tables" rule yet |
| BP-10 | Measures without descriptions, scattered | `MEASURE_DESCRIPTION_MISSING` (info) for every measure | Detected (descriptions); display folders not checked |
| BP-11 | Hard-coded file paths and server | `POWERQUERY_HARDCODED_PATH` (warning) for each query reading from `C:\AWCase\...`; `POWERQUERY_LOCAL_SERVER` (warning) for each MariaDB query on `localhost` | Detected, assuming Power BI writes the server as a `localhost` literal (verify in the saved PBIP) |
| BP-12 | Calculated column that belongs in Power Query (`Age`) | `customers[Age]` Likely unused (unused), `customers[birth_date]` Needs manual review | Cleanup detected; no rule for the practice itself |
| BP-13 | Totals row imported as data (`Returns`) | — | Not yet (needs data inspection) |
| BP-14 | Unrelated/technical tables loaded (`Largest companies`, `etl_log`) | All columns **Likely unused** | Detected (cleanup) |
| BP-15 | Pivoted layout left unpivoted | Columns Likely unused (unused) | No rule for the layout |
| BP-16 | Wrong text encoding for a Latin-1 file | — | Not yet (M `Encoding` vs file encoding needs data access) |
| BP-17 | Duplicate measures (`Copy of Total Revenue`; `Revenue (view)` vs `Total Revenue`) | Unused ones Likely unused; `MEASURE_DUPLICATE_EXPRESSION` (info) for `Copy of Total Revenue` with `Total Revenue` | Exact copies detected; `Revenue (view)` reads another table, so that semantic duplicate is not |

Also expected: `Sales[OrderLineItem]` stays **Likely unused**, because it appears
only in a DAX comment; `territories[continent]` is **Used** via the RLS role (an
unqualified column in a table permission); `Calendar[Month Number]` is **Used**
through sort-by; `Products[Colour]` (filter only) and the drillthrough/tooltip
fields are **Used**; `Avg Quantity`'s unqualified `[OrderQuantity]` gives
`Sales[OrderQuantity]` manual-review evidence at most (it is also used elsewhere).
