# Build guide: the two AdventureWorks case studies in Power BI Desktop

Step-by-step instructions for building both case-study models on this Windows PC:

- **AW Mess**: deliberately bad practice. Specification and answer key:
  [CASE_STUDY_ADVENTUREWORKS.md](CASE_STUDY_ADVENTUREWORKS.md).
- **AW Good**: the same data and report built well. Specification and answer
  key: [CASE_STUDY_GOOD_TWIN.md](CASE_STUDY_GOOD_TWIN.md).

Plan for roughly 2–3 hours per model. Do Part A once, then Part B (Mess) and
Part C (Good) in either order, and finish with Part D. Tick the boxes as you go.

**Build the mistakes faithfully.** In the Mess model, Power BI will sometimes
offer to fix things (detect relationships, promote headers, fix types). Follow
this guide rather than the suggestions. If you deviate anywhere, note it in a
`NOTES.txt` next to the `.pbip` file (in `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Mess` or
`C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Good`); deviations are fine as long as they are written down.

**Menu names** below are the English ones. Your Power BI Desktop appears to run
in Norwegian (your existing M steps are named `Kilde`, `Fjernede kolonner`).
Either switch Desktop to English for this exercise (*File → Options and settings
→ Options → Global → Regional settings → Application language*, then restart),
or use these likely Norwegian equivalents: Get data = *Hent data*, Transform
data = *Transformer data*, Close & Apply = *Lukk og bruk*, Mark as date table =
*Merk som datotabell*, Table tools = *Tabellverktøy*, Column tools =
*Kolonneverktøy*. The analyzer does not care which language the step names use.

---

## Part A. One-time setup

### A1. Folder layout

Each case has two folders: generated **sources** (replaceable at any time) and
your hand-built **project** (the thing being tested). Keep them apart.

All of them live in your `USBL` folder,
`C:\Users\hehaa\OneDrive\Desktop\USBL`, next to `AW` and the analyzer repository:

```
USBL\AWCase\              sources for the Mess model (generated)
USBL\AWGood\              sources for the Good model (generated)
USBL\AWProjects\Mess\     AW Mess.pbip + NOTES.txt   (your work)
USBL\AWProjects\Good\     AW Good.pbip + NOTES.txt   (your work)
```

All four folders already exist; both source packages are generated (`mariadb`,
`excel`, `csv`, `json` subfolders; the Good package also has `csv\returns`).
Below, paths are written out in full so you can paste them into dialogs.

- [ ] Open the folders in Explorer and check them.
- [ ] Never save a project inside `USBL\AWCase` or `USBL\AWGood`.
- [ ] `USBL` is synced by OneDrive. Right-click `USBL\AWProjects` → **Always keep
      on this device**, so Power BI never meets an online-only file (see A5).

If you ever need to regenerate the sources (this replaces the source folder; the
generators refuse to run if a `.pbip` project is found inside it), from the
repository folder in PowerShell:

```powershell
$raw = "C:\Users\hehaa\OneDrive\Desktop\USBL\AW\AdventureWorks+Raw+Data\AdventureWorks Raw Data"
.\.venv\Scripts\python.exe tools\casestudy\adventureworks_mess.py $raw --out C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase --force
.\.venv\Scripts\python.exe tools\casestudy\adventureworks_good.py $raw --out C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood --force
```

### A2. Install MariaDB Server

1. Download the current **LTS** MSI for Windows x86_64 from
   <https://mariadb.org/download/> (12.3 LTS at the time of writing).
2. Run the installer. On the pages that matter:
   - **Custom setup**: keep the defaults (HeidiSQL, a graphical client, is included).
   - **Database authentication**: choose a root password and store it in your
     password manager. Leave *Enable access from remote machines for root*
     **unticked**.
   - **Other database properties**: keep *Install as service* (service name
     `MariaDB`), port `3306`, and tick *Use UTF8 as default server's character
     set* if offered.
3. Finish the installation.

- [ ] Start menu shows a **MariaDB 12.3 (x64)** folder with *Command Prompt
      (MariaDB …)* and *MySQL Client*.

### A3. Load both databases

1. Start menu → **MariaDB 12.3 (x64) → Command Prompt (MariaDB 12.3 (x64))**.
   This is a classic command prompt with the MariaDB tools on the path. (Do not
   use PowerShell for the next commands: it does not support `<`.)
2. Load the Mess database (enter the root password after each command; the
   second file is large and takes up to a minute):

   ```bat
   cd /d C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\mariadb
   mysql -u root -p < 01_schema.sql
   mysql -u root -p < 02_data.sql
   mysql -u root -p < 03_views.sql
   ```

3. Load the Good database:

   ```bat
   cd /d C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood\mariadb
   mysql -u root -p < 01_schema.sql
   mysql -u root -p < 02_data.sql
   ```

4. Create one read-only login for Power BI. Run `mysql -u root -p`, then at the
   `MariaDB [(none)]>` prompt (choose your own password instead of `...`):

   ```sql
   CREATE USER 'pbi_reader'@'localhost' IDENTIFIED BY '...';
   GRANT SELECT ON aw_ops.* TO 'pbi_reader'@'localhost';
   GRANT SELECT ON aw_dw.* TO 'pbi_reader'@'localhost';
   SELECT COUNT(*) FROM aw_ops.sales_2021;
   SELECT COUNT(*) FROM aw_dw.fact_sales;
   exit
   ```

- [ ] The two counts are **23935** and **56046**.

### A4. Install the ODBC driver Power BI's MariaDB connector needs

1. Download **MariaDB Connector/ODBC 3.1.x, 64-bit MSI** (3.1.10 or later) from
   <https://mariadb.com/downloads/connectors/> (choose *ODBC connector*, version
   3.1, Windows 64-bit). Power BI's connector looks for the driver named
   *MariaDB ODBC 3.1 Driver*, so a newer major version may not be found.
2. Install with defaults. You do not need to create a DSN.

### A5. Power BI Desktop

1. Update Power BI Desktop (Microsoft Store updates itself; otherwise install
   the latest from <https://powerbi.microsoft.com/desktop/>).
2. Current versions save projects (`.pbip`) with the PBIR report format by
   default; no preview feature needs to be switched on. You will check the
   saved format in Part D.
3. The projects are saved in `USBL\AWProjects`, which OneDrive syncs. Microsoft
   warns that saving a PBIP into a synced folder can fail, because OneDrive locks
   files while uploading them. With *Always keep on this device* set (A1), this
   is usually fine. If a save fails or reports a locked file: pause OneDrive
   (taskbar OneDrive icon → settings → **Pause syncing**), save again, then resume.

### A6. Settings to apply at the start of each new file

Parts B and C each start with *File → Options and settings → Options*,
**Current file** section:

| Page | Setting | Mess | Good |
| --- | --- | --- | --- |
| Data load | *Relationships → Autodetect new relationships after data is loaded* | **Off** | **Off** |
| Data load | *Time intelligence → Auto date/time* | **On** | **Off** |
| Regional settings | *Locale for import* | English (United States) | English (United States) |
| Privacy | *Ignore the Privacy Levels…* | On | On |

Why: autodetection would create relationships the guide does not ask for; the
English locale makes `34.99` a decimal number rather than a thousands value;
ignoring privacy levels avoids *Formula.Firewall* prompts when Excel, JSON and
MariaDB data are combined (fine for local synthetic data).

### Recurring how-tos

- **Open the Power Query editor**: Home → **Transform data**.
- **Rename a query**: in the Power Query editor, right-click it in the *Queries*
  pane → Rename. **Rename a column**: double-click its header.
- **Edit a step's formula**: select the step under *Applied steps*; the formula
  bar shows its M (*View → Formula bar* if hidden). For whole queries use
  Home → **Advanced editor**.
- **Delete an auto-added step**: click the **X** left of the step under
  *Applied steps*.
- **Disable load**: right-click the query → untick **Enable load** (its name turns
  italic).
- **MariaDB sign-in**: on first connection choose **Database**, user
  `pbi_reader`, your password; level `localhost`.
- **New measure**: select the target table in the *Data* pane →
  Table tools → **New measure**, paste the DAX, press Enter.

---

## Part B. AW Mess (bad practice)

Paths and server are typed as literals throughout; that is intended (BP-11).
Specification: [CASE_STUDY_ADVENTUREWORKS.md](CASE_STUDY_ADVENTUREWORKS.md).

### B1. New file and settings

- [ ] File → New (blank report).
- [ ] Apply the **Mess** column of the A6 table.

### B2. Power Query: MariaDB queries (Q2, Q3, Q5–Q7, Q9, Q11, Q15, Q22)

1. Home → Get data → **More…** → *Database* → **MariaDB** → Connect.
2. Server: `localhost`, Database: `aw_ops`, Data connectivity mode: **Import** → OK.
   Sign in as described in the how-tos.
3. In the Navigator, expand `aw_ops` if needed and tick all of: `sales_2021`,
   `sales_2022`, `v_sales_report`, `v_sales_by_month`, `customers`,
   `stg_customers_raw`, `dim_product`, `territories`, `etl_log`.
4. Click **Transform Data**. Power BI creates one query per item.
5. Rename the queries, if needed, to exactly: `sales_2021`, `sales_2022`,
   `v_sales_report`, `v_sales_by_month`, `customers`, `stg_customers_raw`,
   `dim_product`, `territories`, `etl_log`.
6. **sales_2021** (Q2): rename columns `order_date` → `OrderDate`, `stock_date` →
   `StockDate`, `order_number` → `OrderNumber`, `product_key` → `ProductKey`,
   `customer_key` → `CustomerKey`, `territory_key` → `TerritoryKey`,
   `order_line_item` → `OrderLineItem`, `order_quantity` → `OrderQuantity`.
7. **sales_2022** (Q3): the same eight renames again, by hand.
8. **v_sales_by_month** (Q6): Add Column → **Custom column**, name `YearMonth`,
   formula `[order_year] * 100 + [order_month]` → OK; then click the type icon
   in the new column's header → **Whole number**.
9. Leave `v_sales_report`, `customers`, `stg_customers_raw`, `dim_product`,
   `territories` (keep `territory_key` as text) and `etl_log` unchanged.

### B3. Power Query: folder and append (Q1, Q4)

1. **Sales 2020** (Q1): Home → New source → **Folder** → Browse to
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\csv\sales_archive` → OK. In the preview dialog click
   **Combine & Transform Data** (the duplicate `- Copy` file is meant to be
   included). In *Combine Files*: Sample file **First file**, Delimiter
   **Comma** → OK. Rename the new main query (named `sales_archive`) to
   `Sales 2020`. Leave the generated helper queries as they are.
2. **Sales** (Q4): Home → Append queries → **Append queries as new** → *Three or
   more tables* → add `Sales 2020`, `sales_2021`, `sales_2022` → OK. Rename
   `Append1` to `Sales`. Click the type icon of `TerritoryKey` → **Text**.

### B4. Power Query: files (Q8, Q10, Q12–Q14, Q16–Q21)

1. **Customer Lookup (latin1)** (Q8): New source → **Text/CSV** →
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\csv\Customer Lookup (latin1).csv`. Leave *File origin* at
   **65001: Unicode (UTF-8)** even though accented names look broken
   (BP-16) → **Transform Data**. Rename the query to `Customer Lookup (latin1)`.
   Do not remove the junk rows at the bottom.
2. **Excel product master**: New source → **Excel workbook** →
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\excel\Product Master.xlsx`. In the Navigator tick the **sheets**
   `Products`, `Subcategories`, `Categories` → **Transform Data**.
   - **Products** (Q10): if *Applied steps* show *Promoted Headers* or *Changed
     Type* after *Navigation*, delete them. Then Home → Remove rows → **Remove
     top rows** → `3` → OK; Home → **Use first row as headers**. Select the
     `Price` column → Transform → **Replace values**: `$` with nothing → OK;
     again `,` with nothing → OK. Then set `Price` to **Decimal number**.
   - **Subcategories** (Q12) and **Categories** (Q13): check that the first row
     is the header (otherwise *Use first row as headers*).
3. **product_categories** (Q14): New source → **JSON** →
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\json\product_categories.json`. It opens as a list: List tools →
   **To table** → OK. Click the expand icon on `Column1`, keep `id` and `name`,
   untick *Use original column name as prefix* → OK. Rename the query to
   `product_categories`.
4. **territories json** (Q16): New source → **JSON** →
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\json\territories.json`. In the record, click the **List** link
   next to `continents` → **To table** → OK. Expand `Column1` (keep `name`,
   `countries`, untick the prefix). Expand `countries` → **Expand to new rows**,
   then expand it again (keep `name`, `regions`). Expand `regions` → *Expand to
   new rows*, then expand (`key`, `region`). Rename duplicate `name` columns if
   asked. Rename the query to `territories json`.
5. **Returns 2020 / 2021 / 2022** (Q17): New source → **Excel workbook** →
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\excel\Returns by Year.xlsx`. Tick sheets `2020`, `2021`, `2022` →
   **Transform Data**. In each of the three queries: delete any auto *Promoted
   Headers*/*Changed Type* steps; Remove top rows → `2`; **Use first row as
   headers**. Do **not** remove the `TOTAL` row at the bottom (BP-13). Rename
   the queries `Returns 2020`, `Returns 2021`, `Returns 2022`.
6. **Returns** (Q18): Append queries **as new** → three tables → `Returns 2020`,
   `Returns 2021`, `Returns 2022`. Rename to `Returns`.
7. **Calendar** (Q19): New source → Text/CSV → `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\csv\Calendar Lookup.csv`
   → Transform Data. Rename to `Calendar`. With `Date` selected:
   Add Column → Date → Year → **Year**; Add Column → Date → Month → **Month**
   (rename the column to `Month Number`); Add Column → Date → Month → **Name of
   month** (rename to `Month Name`). Then Add Column → Custom column, name
   `YearMonth`, formula `[Year] * 100 + [Month Number]`, type **Whole number**.
8. **Largest companies** (Q20) and **Product Category Sales (Unpivot Demo)** (Q21):
   New source → Text/CSV for each file in `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase\csv`. Do not unpivot.
9. Every query keeps **Enable load** on (loading helpers is part of the mess),
   except the folder helper queries Power BI created in B3 (leave them as they are).

- [ ] Home → **Close & apply**. Wait for the load to finish.

### B5. Model

1. **Relationships**: Model view. Drag each column onto its partner, then
   double-click the line to check the settings:

   | From (many side) | To (one side) | Settings |
   | --- | --- | --- |
   | `Sales[ProductKey]` | `Products[ProductKey]` | Many-to-one, Single |
   | `Sales[CustomerKey]` | `customers[customer_key]` | Many-to-one, Cross filter direction **Both** |
   | `Sales[TerritoryKey]` | `territories[territory_key]` | Many-to-one, Single (text key) |
   | `Sales[OrderDate]` | `Calendar[Date]` | Many-to-one, Single |
   | `Returns[Product]` | `Products[ProductKey]` | Many-to-one, Single |
   | `Products[Subcategory]` | `Subcategories[ProductSubcategoryKey]` | Many-to-one, **Both** |
   | `Subcategories[ProductCategoryKey]` | `Categories[ProductCategoryKey]` | Many-to-one, Single |
   | `v_sales_by_month[YearMonth]` | `Calendar[YearMonth]` | Cardinality **Many-to-many**, Single (`Calendar` filters `v_sales_by_month`) |

   Delete any other relationship you find (right-click the line → Delete).
2. **Sort by**: Table view → select `Calendar[Month Name]` → Column tools →
   **Sort by column** → `Month Number`.
3. **Measures** (no descriptions, no folders), created in the table named in
   each comment:

   ```dax
   // in Sales
   Total Revenue = SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Price]))
   Total Orders = DISTINCTCOUNT(Sales[OrderNumber])
   Avg Quantity = AVERAGEX(Sales, [OrderQuantity])
   Copy of Total Revenue = SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Price]))
   Old Profit = // replaced by the view: SUM(Sales[OrderLineItem])
       SUMX(Sales, Sales[OrderQuantity] * (RELATED(Products[Price]) - RELATED(Products[Cost])))
   // in v_sales_report
   Revenue (view) = SUM(v_sales_report[revenue])
   // in Returns
   Total Returns = SUM(Returns[Qty])
   Return Rate = DIVIDE([Total Returns], SUM(Sales[OrderQuantity]))
   ```

   Paste one measure at a time, without the `// in …` lines. `Old Profit` keeps
   its comment and line break (Shift+Enter for a new line).
4. **Calculated column** in `customers`: select `customers` → Table tools →
   **New column** → `Age = DATEDIFF(customers[birth_date], TODAY(), YEAR)`.
5. **Field parameter**: Modeling → New parameter → **Fields**. Name
   `Metric Selector`; add `Total Revenue` and `Total Orders`; leave *Add slicer
   to this page* ticked → Create.
6. **Role**: Modeling → **Manage roles** → New → name `Europe only` → select
   table `territories` → switch to the **DAX editor** and enter exactly
   `[continent] = "Europe"` (no table name) → Save.
7. Do **not** create a calculation group in this model (it would block the
   implicit measure in B6).

### B6. Report

Create the pages (right-click a page tab → Rename) and visuals:

1. **Overview**
   - Card: `Total Revenue`. Card: `Total Orders`.
   - Card: drag the column `v_sales_report[revenue]` itself (it shows *Sum of
     revenue*; this implicit measure is intended).
   - Line chart: Y-axis `Total Revenue`, X-axis `Sales[OrderDate]`. Power BI uses
     the automatic date hierarchy; in the X-axis well remove *Quarter* and
     *Day*, keeping *Year* and *Month*.
   - Slicer: `territories[country]`.
   - Filters pane → **Filters on this page**: add `Categories[CategoryName]`,
     *Basic filtering*, *Select all*, then untick `Components`.
2. **Products**
   - Matrix: Rows `Categories[CategoryName]`, `Subcategories[SubcategoryName]`,
     `Products[Product Name]`; Values `Total Revenue`.
   - Format visual → Cell elements → **Background color** On → *fx* → Format
     style *Gradient*, based on field **Return Rate** → OK.
   - Filters on this visual: add `Products[Colour]`, Basic filtering, tick a few
     colours (e.g. Black, Red, Silver).
3. **Customers**
   - Table: `customers[first_name]`, `customers[last_name]`, `customers[occupation]`.
   - With no visual selected, in the Visualizations pane → *Drill through* well,
     add `customers[occupation]`.
4. **Return tooltip**
   - Format page → **Page information** → *Allow use as tooltip* On (canvas
     becomes tooltip-sized).
   - Card: `Return Rate`.
   - Back on **Products**, select the matrix → Format visual → General →
     **Tooltips** → Type *Report page*, Page *Return tooltip*.
5. **Metrics**
   - Slicer: `Metric Selector` (already created in B5 if it landed here; move it).
   - Clustered column chart: X-axis `Calendar[Month Name]`, Y-axis `Metric Selector`.
6. **Old analysis**
   - Table: `v_sales_report[product_name]`, `v_sales_report[region]`, `Revenue (view)`.
   - Right-click the page tab → **Hide page**.
7. **Report filter**: Filters pane → **Filters on all pages** → add
   `territories[continent]`, leave all selected.
8. **Bookmark**: on Overview, View → Bookmarks and Selection panes. In
   Selection, hide the *Sum of revenue* card; in Bookmarks click **Add**
   (rename it `Without implicit card`). Unhide the card afterwards.

### B7. Save

- [ ] File → **Save as** → Browse this device → folder `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Mess`
      → file name `AW Mess` → Save as type **Power BI project files
      (*.pbip)** → Save. The model keeps reading its data from `C:\Users\hehaa\OneDrive\Desktop\USBL\AWCase`.

---

## Part C. AW Good (good practice)

Specification: [CASE_STUDY_GOOD_TWIN.md](CASE_STUDY_GOOD_TWIN.md). Every path
and the server come from parameters; the generated queries are edited to use them.

### C1. New file and settings

- [ ] File → New. Apply the **Good** column of the A6 table (Auto date/time **off**).

### C2. Parameters

Home → Transform data, then Home → Manage parameters → **New parameter**, three times:

| Name | Required | Type | Suggested values | Current value |
| --- | --- | --- | --- | --- |
| `SourceFolder` | yes | Text | Any value | `C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood` |
| `DbServer` | yes | Text | Any value | `localhost` |
| `DbName` | yes | Text | Any value | `aw_dw` |

### C3. MariaDB queries

1. Home → New source → More… → **MariaDB**: Server `localhost`, Database
   `aw_dw`, **Import** → OK. Tick `fact_sales`, `dim_customer`, `dim_territory`
   → **Transform Data**.
2. In each of the three queries select the **Source** step and change the
   formula bar from `MariaDB.Contents("localhost", "aw_dw")` (the arguments may
   look slightly different) to:

   ```m
   = MariaDB.Contents(DbServer, DbName)
   ```

   If later steps show an error, open Home → Advanced editor and check that only
   the two literal arguments changed.
3. Rename and shape (Home → **Choose columns**, keep only these):

   | Query (rename to) | Keep columns |
   | --- | --- |
   | `fact_sales` → `Sales` | `OrderDate`, `OrderNumber`, `ProductKey`, `CustomerKey`, `TerritoryKey`, `OrderQuantity` |
   | `dim_customer` → `Customers` | `CustomerKey`, `FirstName`, `LastName`, `Occupation` |
   | `dim_territory` → `Territories` | `TerritoryKey`, `Country`, `Continent` |

### C4. Excel and JSON queries

1. New source → **Excel workbook** → `C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood\excel\Products.xlsx`. In the
   Navigator tick the **tables** `Products` and `Subcategories` (table icons,
   not the sheets `ProductData`/`SubcategoryData`) → Transform Data.
2. In both queries select **Source** and change the path in the formula bar:

   ```m
   = Excel.Workbook(File.Contents(SourceFolder & "\excel\Products.xlsx"), null, true)
   ```

   (keep whatever arguments follow the path as Power BI generated them).
3. New source → **JSON** → `C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood\json\categories.json` → List tools →
   **To table** → OK → expand `Column1` (`CategoryKey`, `CategoryName`, untick
   the prefix) → set types: `CategoryKey` Whole number, `CategoryName` Text.
   Rename the query `Categories`. Edit its **Source** step:

   ```m
   = Json.Document(File.Contents(SourceFolder & "\json\categories.json"))
   ```

### C5. Products as one star-schema dimension

1. Select `Products` → Home → **Merge queries** (not *as new*). Second table
   `Subcategories`; click `SubcategoryKey` in both; Join kind *Left outer* → OK.
2. Expand the new `Subcategories` column: tick `SubcategoryName` and
   `CategoryKey`, untick the prefix → OK.
3. Merge queries again: second table `Categories`, match `CategoryKey` ↔
   `CategoryKey`, Left outer → OK. Expand: `CategoryName` only, no prefix.
4. Choose columns: `ProductKey`, `ProductName`, `Colour`, `Cost`, `Price`,
   `SubcategoryName`, `CategoryName`. Rename `SubcategoryName` → `Subcategory`
   and `CategoryName` → `Category`. Check `Cost` and `Price` are Decimal number.
5. Right-click `Subcategories` → untick **Enable load**. Same for `Categories`.

### C6. Returns: one filtered folder query

1. New source → **Folder** → `C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood\csv\returns` → OK. In the preview
   dialog click **Transform Data** (not *Combine*): the folder also contains
   `README.txt`, which must be filtered out first.
2. Filter the file list: on `Extension`, Text filters → **Equals** `.csv`; on
   `Name`, Text filters → **Begins with** `returns_`.
3. Click the **Combine files** button (double down-arrow) in the `Content`
   column header → Sample file *First file*, Delimiter *Comma* → OK.
4. Rename the main query to `Returns`. Remove the `Source.Name` column. Check
   types: `ReturnDate` Date, `TerritoryKey`, `ProductKey`, `ReturnQuantity` Whole
   number.
5. Make the folder path a parameter in **two** places: the `Returns` query's
   **Source** step and the generated helper query **Sample File** (in the
   *Transform File from returns* / *Helper Queries* group). In both, change
   `Folder.Files("C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood\csv\returns")` to:

   ```m
   = Folder.Files(SourceFolder & "\csv\returns")
   ```

6. Check that the helper queries (`Sample File`, `Parameter1`, `Transform Sample
   File`, `Transform File`) are italic, i.e. not loaded. If one is not, untick
   **Enable load** on it.

### C7. Date table

1. New source → Text/CSV → `C:\Users\hehaa\OneDrive\Desktop\USBL\AWGood\csv\calendar.csv` → Transform Data.
   Rename to `Date`; edit **Source** to read the path from the parameter:

   ```m
   = Csv.Document(File.Contents(SourceFolder & "\csv\calendar.csv"), [Delimiter=",", Columns=1, Encoding=65001, QuoteStyle=QuoteStyle.None])
   ```

   (keep Power BI's own options if they differ; only replace the path).
2. Make sure `Date` has type **Date**. Add `Year`, `Month Number` and
   `Month Name` exactly as in B4 step 7 (no `YearMonth` column here).

- [ ] Home → **Close & apply**.

### C8. Model

1. **Relationships** (Model view), all *Many-to-one*, cross filter *Single*:

   | From | To |
   | --- | --- |
   | `Sales[OrderDate]` | `Date[Date]` |
   | `Sales[ProductKey]` | `Products[ProductKey]` |
   | `Sales[CustomerKey]` | `Customers[CustomerKey]` |
   | `Sales[TerritoryKey]` | `Territories[TerritoryKey]` |
   | `Returns[ReturnDate]` | `Date[Date]` |
   | `Returns[ProductKey]` | `Products[ProductKey]` |
   | `Returns[TerritoryKey]` | `Territories[TerritoryKey]` |

2. **Date table**: select the `Date` table → Table tools → **Mark as date table**
   → date column `Date` → OK.
3. **Sort by**: `Date[Month Name]` → Column tools → Sort by column → `Month Number`.
4. **Hierarchy**: in the Data pane right-click `Date[Year]` → **Create hierarchy**;
   rename it `Calendar`; right-click `Date[Month Name]` → Add to hierarchy →
   `Calendar`. The hierarchy holds `Year`, then `Month Name`.
5. **Hide** (right-click → Hide in report view): `Sales[ProductKey]`,
   `Sales[CustomerKey]`, `Sales[TerritoryKey]`, `Sales[OrderDate]`,
   `Returns[ProductKey]`, `Returns[TerritoryKey]`, `Returns[ReturnDate]`,
   `Products[ProductKey]`, `Customers[CustomerKey]`, `Territories[TerritoryKey]`,
   `Date[Month Number]`.

### C9. Measures table with documented measures

1. Home → **Enter data** → name the table `Measures` → **Load**.
2. Create these measures in `Measures` (New measure, one at a time). After each,
   in Model view select it and fill **Description** and **Display folder** in
   the Properties pane:

   | Measure | DAX | Display folder | Description |
   | --- | --- | --- | --- |
   | Total Revenue | `Total Revenue = SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Price]))` | Sales | Order quantity times list price, in USD. |
   | Total Cost | `Total Cost = SUMX(Sales, Sales[OrderQuantity] * RELATED(Products[Cost]))` | Sales | Order quantity times standard cost, in USD. |
   | Total Profit | `Total Profit = [Total Revenue] - [Total Cost]` | Sales | Revenue minus cost, in USD. |
   | Total Orders | `Total Orders = DISTINCTCOUNT(Sales[OrderNumber])` | Sales | Number of distinct orders. |
   | Quantity Sold | `Quantity Sold = SUM(Sales[OrderQuantity])` | Sales | Units sold. |
   | Total Returns | `Total Returns = SUM(Returns[ReturnQuantity])` | Returns | Units returned. |
   | Return Rate | `Return Rate = DIVIDE([Total Returns], [Quantity Sold])` | Returns | Returned units as a share of units sold. |

3. Delete `Column1` from `Measures` (right-click → Delete from model). The table
   becomes a measures-only table at the top of the Data pane.

### C10. Calculation group, field parameter, role

1. **Calculation group**: Model view → Home → **Calculation group**. Accept the
   prompt to turn on *Discourage implicit measures*. In the Data pane (Model
   tab) rename the table to `Time Intelligence`, the column to `Time Calculation`,
   and the first item to `Current` (its expression stays `SELECTEDMEASURE()`).
   Right-click *Calculation items* → **New calculation item** twice:

   ```dax
   YTD = CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))
   PY = CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date]))
   ```

2. **Field parameter**: Modeling → New parameter → **Fields**, name `Metric`,
   fields `Total Revenue`, `Total Orders`, `Total Profit` → Create.
3. **Role**: Modeling → Manage roles → New → `Europe` → table `Territories` →
   DAX editor: `[Continent] = "Europe"` → Save.

### C11. Report

Same pages as the Mess model, without the hidden page and without implicit measures:

1. **Overview**: cards `Total Revenue`, `Total Orders`, `Total Profit`; line
   chart Y-axis `Total Revenue`, X-axis the **`Calendar` hierarchy** (drag the
   hierarchy itself); slicer `Territories[Country]`; page filter
   `Products[Category]`, all except `Components`.
2. **Products**: matrix rows `Products[Category]`, `Products[Subcategory]`,
   `Products[ProductName]`, value `Total Revenue`; background colour gradient
   based on `Return Rate`; visual filter `Products[Colour]` (a few colours);
   tooltip page `Return tooltip` (create that page first, see 4).
3. **Customers**: table `Customers[FirstName]`, `Customers[LastName]`,
   `Customers[Occupation]`; drill-through field `Customers[Occupation]`.
4. **Return tooltip**: *Allow use as tooltip* On; card `Return Rate`.
5. **Metrics**: slicer `Metric`; clustered column chart X-axis `Date[Month Name]`,
   Y-axis `Metric`; slicer `Time Intelligence[Time Calculation]`.
6. **Report filter**: Filters on all pages → `Territories[Continent]`, all selected.

### C12. Save

- [ ] File → Save as → folder `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Good` → file name `AW Good` →
      Power BI project files (*.pbip). The model finds its data only through
      the `SourceFolder` and `DbServer`/`DbName` parameters.

---

## Part D. Check and hand back

1. For each project folder (`C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Mess`, `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Good`), check
   the format in Explorer (shown for Mess; Good is the same with `AW Good`):
   - `AW Mess.SemanticModel\definition\tables\` contains `.tmdl` files (TMDL).
     If you see a `model.bim` file instead, tell me; the analyzer needs TMDL.
   - `AW Mess.Report\definition\pages\` exists (PBIR).
2. Write any deviations into `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Mess\NOTES.txt` /
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Good\NOTES.txt`.
3. Tell me when both are saved (the paths are fixed: `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Mess` and
   `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\Good`). The projects stay on this PC: they contain synthetic
   data only, but they are not committed to the repository.

I will then derive the ground truth independently from the saved files, run the
analyzer, record the expectations as integration tests and investigate every
difference, starting with any `Likely unused` object in the Good model.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| MariaDB connector says the driver is missing | Install Connector/ODBC **3.1.x 64-bit** (A4) and restart Power BI Desktop. |
| `Access denied for user 'pbi_reader'` | Re-run the `GRANT` lines in A3 step 4; check the credentials under File → Options → Data source settings. |
| *Formula.Firewall* error | Current file → Privacy → ignore privacy levels (A6). |
| Prices or costs become huge numbers | Locale for import is not English (United States) (A6); fix it, then refresh. |
| A relationship cannot be created (type mismatch) | Check both columns' types in Power Query; in Mess, `Sales[TerritoryKey]` must be Text. |
| Folder combine picked `README.txt` as sample (Good) | Delete `Returns` and its helper queries and redo C6, filtering **before** combining. |
| Save as offers no `.pbip` type | Update Power BI Desktop (A5). |
| Save fails, or a file is "in use" | OneDrive is syncing the project folder: pause syncing, save, resume (A5). |
| A generator says the folder "contains a Power BI project" | A `.pbip` was saved inside a source folder. Move that project folder to `C:\Users\hehaa\OneDrive\Desktop\USBL\AWProjects\…` and run the generator again. |
