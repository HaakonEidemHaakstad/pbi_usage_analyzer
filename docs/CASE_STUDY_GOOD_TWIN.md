# Case study: AdventureWorks, the good twin

The counterpart of [the inherited mess](CASE_STUDY_ADVENTUREWORKS.md): the same
AdventureWorks business data, the same four source types (MariaDB, Excel, CSV
folder, JSON) and nearly the same report, built with good practice. It measures
the analyzer's *specificity*: on a sound model the health rules should stay
silent and nothing the report needs may be `Likely unused`.

Because data and report mirror the bad case, every difference between the two
analyses should trace to one deliberate practice. The [look-alikes](#look-alikes)
are good practices that resemble bad ones; they are where false positives hide.

Click-by-click instructions for both models: [build guide](CASE_STUDY_BUILD_GUIDE.md).

## Source package

```powershell
.\.venv\Scripts\python.exe tools\casestudy\adventureworks_good.py "<...>\AdventureWorks Raw Data" --out C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood
```

| Folder | Contents | Good practice shown |
| --- | --- | --- |
| `mariadb/` | `01_schema.sql`, `02_data.sql`: database `aw_dw` with `fact_sales` (2020–2022 in one table), `dim_customer`, `dim_territory` | One fact table instead of yearly tables; integer keys; declared primary keys; consistent PascalCase names; junk rows cleaned at the source |
| `excel/Products.xlsx` | Excel tables `Products` (sheet `ProductData`) and `Subcategories` (sheet `SubcategoryData`) | Header in row 1; real Excel tables; numeric prices |
| `csv/returns/` | `returns_2020.csv` … `returns_2022.csv`, plus `README.txt` | Same-shaped yearly files combined by one filtered folder query; a non-data file the filter must exclude |
| `csv/calendar.csv` | One `Date` column | Source for a proper date table |
| `json/categories.json` | `CategoryKey`, `CategoryName` | Single source of truth for categories |

## Model specification

**Settings.** Auto date/time **off** for the file. Paths and server come from three
text parameters: `SourceFolder` (`C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood`), `DbServer` (`localhost`), `DbName`
(`aw_dw`).

**Queries** (load enabled unless stated):

| Query | Source | Shape |
| --- | --- | --- |
| `Sales` | MariaDB `fact_sales` via the parameters | Keep `OrderDate`, `OrderNumber`, `ProductKey`, `CustomerKey`, `TerritoryKey`, `OrderQuantity` |
| `Customers` | MariaDB `dim_customer` | Keep `CustomerKey`, `FirstName`, `LastName`, `Occupation` |
| `Territories` | MariaDB `dim_territory` | Keep `TerritoryKey`, `Country`, `Continent` |
| `Subcategories` | Excel table `Subcategories` | Helper, **load disabled** |
| `Categories` | `categories.json` | Helper, **load disabled** |
| `Products` | Excel table `Products`, merged with `Subcategories` and `Categories` | Keep `ProductKey`, `ProductName`, `Colour`, `Cost`, `Price`, `Subcategory`, `Category` (star schema: no snowflake tables) |
| `Returns` | Folder `csv\returns`, filtered to `returns_*.csv`, then combined | `ReturnDate`, `TerritoryKey`, `ProductKey`, `ReturnQuantity`; the generated helper queries stay load-disabled |
| `Date` | `calendar.csv` | Add `Year`, `Month Number`, `Month Name`; mark as date table |

**Relationships**, all many-to-one, single direction, integer or date keys:
`Sales` → `Date`, `Products`, `Customers`, `Territories`; `Returns` → `Date`,
`Products`, `Territories`.

**Model details.** Sort `Date[Month Name]` by `Date[Month Number]`; hierarchy
`Calendar` (`Year`, `Month Name`) on `Date`; hide key columns and `Month Number`.

**Measures** in a measures-only table `Measures`, each with a description and a
display folder:

| Measure | DAX | Folder |
| --- | --- | --- |
| Total Revenue | `SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Price]))` | Sales |
| Total Cost | `SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Cost]))` | Sales |
| Total Profit | `[Total Revenue] - [Total Cost]` | Sales |
| Total Orders | `DISTINCTCOUNT(Sales[OrderNumber])` | Sales |
| Quantity Sold | `SUM(Sales[OrderQuantity])` | Sales |
| Total Returns | `SUM(Returns[ReturnQuantity])` | Returns |
| Return Rate | `DIVIDE([Total Returns], [Quantity Sold])` | Returns |

**Calculation group** `Time Intelligence`, column `Time Calculation`, items
`Current = SELECTEDMEASURE()`, `YTD = CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))`,
`PY = CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date]))`.

**Field parameter** `Metric` with `Total Revenue`, `Total Orders`, `Total Profit`.

**Role** `Europe`: on `Territories`, `[Continent] = "Europe"`.

## Report

The bad case's pages without the hidden "Old analysis" page and without implicit
measures:

| Page | Visuals |
| --- | --- |
| Overview | Cards `Total Revenue`, `Total Orders`, `Total Profit`; line chart `Total Revenue` by the `Calendar` hierarchy; slicer `Territories[Country]`; page filter `Products[Category]` is not `Components` |
| Products | Matrix rows `Products[Category]` → `Products[Subcategory]` → `Products[ProductName]`, value `Total Revenue`, background colour by `Return Rate`; visual filter `Products[Colour]`; tooltip page `Return tooltip` |
| Customers | Table `Customers[FirstName]`, `Customers[LastName]`, `Customers[Occupation]`; drillthrough on `Customers[Occupation]` |
| Return tooltip | Tooltip page: card `Return Rate` |
| Metrics | Slicer `Metric`; column chart `Metric` by `Date[Month Name]`; slicer `Time Intelligence[Time Calculation]` |

Report-level filter `Territories[Continent]` (all selected).

## Look-alikes

Good practices that resemble a bad practice. Each must **not** trigger the rule
named.

| ID | Practice | Resembles | Must not fire |
| --- | --- | --- | --- |
| GP-01 | Yearly returns files combined by one folder query with a name/extension filter | Annual append; unfiltered folder (BP-01, BP-02) | `POWERQUERY_ANNUAL_APPEND`, `POWERQUERY_FOLDER_UNFILTERED` |
| GP-02 | Power BI's generated folder helpers (`Sample File`, `Transform File`, …) and the merge helpers `Subcategories`/`Categories`, all load-disabled | Loaded staging queries (BP-04) | `POWERQUERY_APPEND_INPUT_LOADED`; their columns are not model objects at all |
| GP-03 | Paths and server in parameters, including the generated `Sample File` | Hard-coded paths/server (BP-11) | `POWERQUERY_HARDCODED_PATH`, `POWERQUERY_LOCAL_SERVER` (the `localhost` value lives in a parameter) |
| GP-04 | `Total Profit` references other measures; `Return Rate` reuses `Quantity Sold` | Duplicate logic (BP-17) | `MEASURE_DUPLICATE_EXPRESSION` |
| GP-05 | Hidden key columns used only by relationships | Unused columns | Keys must be **Used** (relationship endpoints), not Likely unused |
| GP-06 | `Month Number` hidden, used only for sorting | Unused column | **Used** via sort-by |
| GP-07 | `Continent` used only by the RLS role and a report filter | Unused column | **Used** |
| GP-08 | Measures-only table (no columns left) | — | No cleanup candidates or diagnostics from the empty table |
| GP-09 | Auto date/time off; marked date table | — | No `LocalDateTable_*` objects at all |

## Scored result (2026-10-01)

Built by the user as `USBL\AWProjects\Good\AW Good.pbip` (deviations in its
`NOTES.txt`: the measures table is `_Measures` because `Measures` is a reserved
name; the parameters had to be load-disabled; Norwegian helper and ordinal names).
An independent ground truth was derived from the raw files without analyzer code
or output. Expectations: `tests/integration/aw_good_expected.json` (run with
`PBI_AW_GOOD_PROJECT`).

- **Cleanup:** all 40 objects Used in both the analyzer and the ground truth; no
  manual reviews, no internal objects.
- **Health:** no findings, matching the ground truth's metadata facts. All nine
  look-alikes are genuinely implemented and stay silent, including the generated
  `Eksempelfil` helper (filtered, `Source{0}`), `localhost` inside a parameter, and
  measures that reference other measures.
- **Analyzer issue found and fixed:** the raw report safety net matched `Date[Date]`
  because a visual's `"Entity": "Date"` satisfied both the table and the field
  condition. Harmless here (the column is Used), but in another model a column named
  like its table would have been held for manual review by any visual using the
  table. One whole value no longer counts as both.
- The AW Mess fixes generalize: the field parameter's hidden `Metric Felt` column is
  Used through `groupByColumn`, and the calculation group's ordinal column through
  sort-by.

## Answer key (prediction)

To be confirmed against the saved PBIP, as for the bad case.

- **Cleanup:** every column and measure listed above is **Used**; none is
  `Likely unused`. `Total Cost`, `Quantity Sold` and `Total Returns` are Used
  through the measures that reference them.
- **Health:** no findings. In particular no description, relationship, duplicate
  or Power Query findings.
- **Uncertain until the files exist:** columns Power BI adds to the calculation
  group and field parameter tables (ordinal/sort columns) and how the
  measures-only table is stored. Record what the files contain before judging.

Any `Likely unused` on an object the report uses is a false positive and the
most important kind of result this case can produce; reduce it to a synthetic
fixture first, as AGENTS.md describes.

## Comparison with the bad case

| Bad practice | Good twin | Expected difference in results |
| --- | --- | --- |
| BP-01/02 yearly appends, unfiltered folder | GP-01 | Append and folder findings disappear |
| BP-03 wide view | Only needed columns imported | No Likely unused columns |
| BP-04/05/14/15 staging, duplicates, unrelated tables | Not loaded / not present | Their Likely unused columns disappear |
| BP-06 text key | Integer keys | `RELATIONSHIP_TEXT_KEY` disappears |
| BP-07/08 bidirectional, many-to-many | Single direction, many-to-one | Relationship warnings disappear |
| BP-09 auto date/time | Date table | No internal auto-date objects |
| BP-10 undocumented measures | Descriptions, folders, measure table | `MEASURE_DESCRIPTION_MISSING` disappears |
| BP-11 hard-coded paths/server | Parameters | Path and local-server findings disappear |
| BP-12 calculated column | Not present | — |
| BP-17 duplicate measures | Measures reference each other | Duplicate finding disappears |
