# GUI design — Power BI Model Health Analyzer

Status: accepted 2026-10-01. All phases are implemented: G0 (core preparation), G1
(read-only viewer), G2 (workflow aids) and G3 (Windows build); sections 13–16. This document fixes the architecture and scope (AGENTS.md, "Future GUI
requirement"; ROADMAP Phase 4).

Owner decisions (2026-10-01): toolkit chosen by the developer (PySide6, section 7);
a standalone Windows app is wanted (G3); the interface language is English; G0
started immediately.

## 1. Goal

A thin desktop front end that lets a Power BI developer run the analyzer on a PBIP
project and work through its results: what can probably be cleaned up, what needs a
human decision, what the model-health rules found, and *why*, without reading the
text report or the Excel workbook.

The GUI adds no analysis. Everything it shows comes from `analyze_project()` and
small, tested, UI-agnostic helpers in the core package.

## 2. Users and tasks

Primary user: the person who maintains the model (Power BI developer or analyst),
on Windows, with the PBIP project on disk (often in OneDrive). Secondary user: a
reviewer who needs to understand a finding before approving a change.

| Task | What the user needs |
| --- | --- |
| Run an analysis | Pick a project folder (or a `.pbip` file), see results in about a second. |
| Get the overview | Counts per status for columns and measures, health findings by severity, diagnostics. |
| Clean up safely | Filter to Likely unused, grouped by table; see that this is a candidate list, not permission to delete. |
| Understand a status | For any object: status, short explanation, the evidence path (for example `Visual -> Sales[Revenue] -> Sales[Amount]`), source file and line. |
| Decide manual reviews | See why an object is held: which evidence is credible but unproven. |
| Act on health findings | Rule, scope, explanation, evidence, recommendation, source location. |
| Iterate | Edit the model in Power BI Desktop, re-run, see what changed. |
| Share | Export the existing text, Excel and JSON reports to a chosen folder. |

## 3. Principles

1. **Read-only.** The GUI never edits or deletes PBIP files. Removing objects stays
   in Power BI Desktop, where the user can refresh and validate.
2. **Conservatism stays visible.** "Likely unused" is always shown with its caveat
   (static analysis; other reports on the same semantic model are not seen). The UI
   offers no "delete" or "select all unused" action.
3. **Evidence first.** Every status and finding links to its evidence. A status
   without an explanation is a bug in the core, not something the GUI papers over.
4. **No domain logic in the GUI.** Filtering, labels, evidence paths and grouping
   rules live in the core and are unit-tested without a GUI toolkit.
5. **Offline and credential-free.** No network access and no telemetry.
6. **Stable identifiers.** Internal state uses enums and IDs (`Status`, `rule_id`,
   `ObjectRef`), never display text.

## 4. Architecture

```
pbi_usage_analyzer/            core, no GUI dependency (unchanged rule)
  api.py                       analyze_project() -> AnalysisResult
  views/                       NEW: UI-agnostic presentation model
    catalog.py                 status/rule labels and explanations
    explain.py                 evidence paths for one object
    rows.py                    immutable rows for tables, filter/group helpers
  reporting/                   text / Excel / JSON writers (+ write_reports helper)
pbi_usage_analyzer_gui/        NEW: thin Qt front end (optional dependency)
  app.py                       QApplication, main window
  worker.py                    runs analyze_project() off the UI thread
  models.py                    Qt item models wrapping views/ rows
  widgets/                     summary, tables, detail panel, dialogs
```

- `pbi_usage_analyzer.views` turns an `AnalysisResult` into frozen rows and text
  that any front end can show. The text report and the Excel writer can later use
  the same helpers, so the GUI and the reports cannot drift apart.
- `pbi_usage_analyzer_gui` contains only widgets, Qt item models over those rows,
  and wiring. If a widget needs a decision ("is this object a cleanup candidate?"),
  the decision belongs in `views/`.
- Dependency rule, enforced by a test: nothing under `pbi_usage_analyzer/` imports
  Qt or `pbi_usage_analyzer_gui`. The GUI toolkit is an optional extra
  (`pip install .[gui]`); the CLI and library keep working without it.
- Threading: one analysis at a time in a worker thread (`QThread`), result handed
  back by signal. Measured on 2026-10-01: AdventureWorks 0.04 s, AW Mess 0.09 s,
  AW Good 0.04 s, the generated 3,280-object model 0.32 s. A progress bar and
  cancellation are therefore not needed in the first version. The worker still
  matters, because OneDrive placeholder files can stall reads. Progress callbacks
  and cancellation stay on the core roadmap for larger models.
- The result is treated as immutable. `AnalysisResult` exposes mutable graph
  objects, so the GUI reads only `views/` rows and never holds onto graph internals.
- Settings (recent projects, window layout, later acknowledgements) are stored per
  user with `QSettings`, never inside the PBIP folder.

## 5. Screens

### 5.1 Start

Choose a project folder or `.pbip` file, or a recent project. Errors from discovery
(no unambiguous `.Report`/`.SemanticModel` pair) appear as a plain message with the
folder path, not a stack trace.

### 5.2 Main window

```
+--------------------------------------------------------------------------------+
| AW Mess   C:\...\AWProjects\Mess          [Re-run F5] [Export v]  analyzed 14:32|
+--------------------------------------------------------------------------------+
| Overview | Cleanup | Health | Diagnostics | Queries                            |
+------------------------------------------------+-------------------------------+
| Status [Likely unused v] Type [All v]          | Sales 2020[StockDate]         |
| Table [All v]  Search [stock          ]        | Likely unused                 |
|                                                | No known use or dependency.   |
| Table        Object        Type    Status      | A cleanup candidate, not      |
| Sales        StockDate     Column  Likely unu. | proof that deletion is safe.  |
| Sales 2020   StockDate     Column  Likely unu. |                               |
| sales_2021   StockDate     Column  Likely unu. | Evidence                      |
| ...                                            |  Sales[StockDate] (unused)    |
|                                                |   -> loaded from this column  |
|                                                |      (query Sales, M lineage) |
|                                                |                               |
|                                                | Source                        |
|                                                |  Sales 2020.tmdl:28  [Open]   |
+------------------------------------------------+-------------------------------+
| 178 business objects: 65 Used, 2 Needs manual review, 111 Likely unused        |
+--------------------------------------------------------------------------------+
```

- **Overview:** status counts for columns and measures (business objects; internal
  auto-date objects counted separately), Likely unused by table, health findings by
  severity and category, diagnostics count. Every number is clickable and opens the
  matching filtered tab. A short "How to read these results" panel restates the
  status semantics.
- **Cleanup:** one table of columns and measures with filters for status, type and
  table, text search, and sorting. Internal objects are hidden by default behind a
  "Show internal objects" toggle. Default filter: Likely unused.
- **Health:** findings with rule, severity, confidence, category and scope; filters
  by rule, severity and category (the same semantics as `health/filtering.py`).
- **Diagnostics:** code, message, file and line. A banner on every tab says
  "Results may be incomplete" when diagnostics exist, because damaged or
  unsupported sources only add scoped manual-review evidence.
- **Queries:** Power Query dependencies (query, depends on, path through
  load-disabled queries) and M lineage diagnostics.
- **Detail panel** (shared by all tabs): short status label, long explanation, the
  evidence path or paths, every evidence row with type and confidence, and the
  source location. The **Open** button opens the file in the system editor. Opening
  at a line (for example VS Code `code -g file:line`) is a setting, not a default.

### 5.3 Export

Writes the existing text, Excel and JSON reports to a folder the user chooses
(default: the project folder, as the CLI does). Uses the same writer functions as
the CLI. JSON exports contain local paths and expressions; the dialog says so.

### 5.4 Not in the first version

Interactive dependency graph drawing, run comparison, acknowledgements, opening a
saved JSON export, translations. See the phases below.

## 6. Core changes required first (phase G0)

These are core improvements in their own right: the reports benefit too. Each is a
small, tested change.

| # | Change | Why the GUI needs it |
| --- | --- | --- |
| C1 | `views.explain.evidence_paths(result, ref)`: shortest paths from proven roots (report use, relationship, RLS, field parameter) to `ref` over the propagating edge types, plus the direct manual-review evidence. Built only from graph evidence. | The detail panel's main content. Today findings carry flat reason strings. AGENTS.md asks for "dependency paths over booleans". |
| C2 | `views.catalog`: per `Status` a short label and a long explanation; per rule a `RuleInfo` (rule ID, category, severity, title, one-line summary) attached to the `RULES` registry. | Filter lists and help text before any finding exists; one wording shared by reports and GUI. |
| C3 | Structured health scope: `HealthFinding.object_ref: ObjectRef | None` next to the existing `scope` text (relationships keep a text scope). JSON schema version decided under the export rules. | Clicking a health finding selects the object; filtering by table. |
| C4 | Stable finding keys: `ObjectRef` key text for cleanup, and `rule_id + scope + source file` for health findings. | Selection that survives a re-run; later acknowledgements and run comparison. |
| C5 | `reporting.write_reports(result, folder, *, json=False)` used by both the CLI and the GUI. | No duplicated file-writing logic. |
| C6 | `views.rows`: frozen row types for objects, health findings, diagnostics and query dependencies, with the filter and grouping helpers. | The GUI renders rows; it does not walk the graph. |

Not required yet: progress callbacks and cancellation (measured analysis time is
well under a second), and JSON import.

## 7. Framework

| Option | For | Against |
| --- | --- | --- |
| **PySide6 (Qt for Python)**, recommended | Official Qt binding. Mature tables with sorting/filtering models, splitters and docks, HiDPI, native Windows look. LGPL-3.0 (also GPL/commercial). 6.11.2 (PyPI, 2026-08-18) supports Python 3.10–3.14 with Windows x64 wheels, so it runs on this machine's 3.14 and CI's 3.12. | Large dependency (roughly 100+ MB installed). Qt concepts to learn. Frozen executables are big. LGPL obligations if redistributed (dynamic linking, which PySide6 wheels do, satisfies them). |
| Tkinter (standard library) | No dependency (Tk 9.0 is present in this Python 3.14). Simple. | Weak table widget (no built-in sort/filter models), dated look, limited HiDPI and accessibility. Filter/search tables would need hand-written plumbing, which tends to pull logic into the GUI. |
| Local web UI (HTTP server plus browser, or pywebview 6.2.1, BSD) | Modern look; skills transfer to a possible hosted version. | Second language and toolchain (HTML/JS); a local server to secure; pywebview relies on the system web view (WebView2 on Windows). More moving parts for a single-user desktop tool. |
| Textual (terminal UI) | Pure Python, small. | Not the "intuitive GUI" the roadmap asks for; poor fit for nontechnical users. |

Decision: PySide6, as an optional extra, using only Qt Widgets (no QML) to keep one
language and a small surface. A redistributable Windows build is wanted, so G3
must ship the LGPL notices and keep Qt as separately replaceable libraries (the
one-folder build does this).

## 8. Testing

- `views/` is pure Python and gets ordinary `unittest` tests over the synthetic
  scenarios and the optional real-project tests: evidence paths for known chains
  (for example scenario 02's transitive DAX, scenario 41's lineage), catalog
  completeness (every `Status` and registered rule has labels), row/filter parity
  with `health/filtering.py`.
- Import guard test: importing `pbi_usage_analyzer` must not load Qt.
- GUI smoke test, skipped when PySide6 is absent: start the main window offscreen
  (`QT_QPA_PLATFORM=offscreen`), load a synthetic scenario through the worker, and
  check row counts against the API. An optional CI job installs the `gui` extra.
- Manual checklist per release: the three case-study projects open and their
  counts match the integration expectations.

## 9. Packaging and launch

- First: `python -m pbi_usage_analyzer_gui [project]` from the project `.venv`, plus a
  `scripts/gui.ps1` convenience launcher on Windows.
- G3: a one-folder PyInstaller build for Windows (decided 2026-10-01), with the Qt
  LGPL notices included. No installer, auto-update or code signing in this design.

## 10. Phases

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| G0 Core preparation | C1–C6 with tests; text/Excel reports use `views.catalog` wording and evidence paths where it helps. | Full validation suite green; no status changes (presentation only). |
| G1 Read-only viewer | Start screen, Overview, Cleanup, Health, Diagnostics, Queries, detail panel, re-run, export. | The three case studies open; on-screen counts equal the integration expectations; smoke test in CI. |
| G2 Workflow aids | Run comparison (previous vs current analysis of the same project, keyed by C4), acknowledgements stored per user, evidence-graph view for one object. | Acknowledged findings stay acknowledged across re-runs; comparison explains every change. |
| G3 Distribution | Windows build, user guide with screenshots. | Runs on a machine without Python. |

The AI advisory layer (ROADMAP Phase 5) is out of scope here. If it comes, it would
read the same `views/` rows and appear as a separate, clearly labelled panel.

## 11. Non-goals

- Editing or deleting anything in the PBIP project.
- Analysing several reports that share one semantic model (the core does not do it
  yet; the UI states the limitation).
- Hosting as a web service or multi-user tool.
- Replacing the text report and Excel workbook; they remain the shareable artifacts.

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| Logic creeps into widgets | `views/` layer; import guard; review rule "decisions belong in the core". |
| Users read Likely unused as "safe to delete" | Caveat in the detail panel and Overview; no bulk-delete or bulk-select-for-deletion features. |
| Large Qt dependency burdens core users | Optional extra; core and CI core jobs never install it. |
| Display text used as identity | Rows carry `ObjectRef`, `Status`, `rule_id`; text comes from the catalog only. |
| Results shown after the project changed on disk | Header shows analysis time; Re-run is one key; file watching only if users ask for it. |

## 13. Decisions and G0 result

Decided 2026-10-01: PySide6; Windows app (G3); English; G0 now.

G0 as implemented (all core, no Qt; no status or evidence changed anywhere):

| # | Where | Notes |
| --- | --- | --- |
| C1 | `views/explain.py`: `Explainer(graph, findings).explain(ref)` returns an `Explanation` (`use_path`, `review_path`, `evidence`); `format_path` | Shortest path by breadth-first search over propagating edges whose source is used; report evidence preferred over field parameter, RLS and relationship as the start. `review_path` covers manual review received through Power Query lineage. All 3,200 objects of the large model explain in 0.01 s. |
| C2 | `views/catalog.py` (`STATUS_INFO`, `EVIDENCE_LABELS`, `CATEGORY_LABELS`, `SEVERITY_LABELS`, `LIKELY_UNUSED_CAVEAT`); `health/engine.py` `RULE_INFO` | Tests require text for every status, evidence type and registered rule, and that emitted findings match their rule's category and severity. |
| C3 | `HealthFinding.object_ref` | Measures/columns for DAX and metadata rules, loaded queries for Power Query rules, none for relationships and load-disabled queries. Excluded from JSON schema v1. |
| C4 | `views.rows.object_key`, `health_key` | `Column`, table and name joined by `|`; rule ID, scope and the source path relative to the project root. |
| C5 | `reporting/files.py` `write_reports(result, folder=None, *, json=False)` | The CLI uses it. |
| C6 | `views/rows.py` row types, `filter_objects`, `filter_health`, `unused_by_table`, `query_dependency_rows` | Filters follow the health-filter semantics; parity with `filter_health_findings` is tested. |

Report changes: the Excel column/measure sheets gained an "Evidence path" column,
and Power Query dependencies show the path through load-disabled queries (Excel
column and text report). The classifier now exposes `ROOT_EVIDENCE`,
`PROPAGATING_EVIDENCE` and `OWNER_DEPENDENCY` so classification and explanations
share one definition.

## 14. G1 result

Package `pbi_usage_analyzer_gui` (Qt Widgets only; dependency `PySide6-Essentials`,
which has QtCore/QtGui/QtWidgets without the large add-ons package):

| Module | Content |
| --- | --- |
| `app.py`, `__main__.py` | `python -m pbi_usage_analyzer_gui [folder or .pbip]`; a clear message when PySide6 is missing. `pbi-model-health` gui-script in `pyproject.toml`. |
| `worker.py` | `AnalysisThread` (QThread) runs `analyze_project`; errors become a message box, the start page stays. |
| `models.py` | `RowTableModel` over frozen rows plus a sort proxy (numeric/case-insensitive sort keys). Filtering is done by `views.filter_objects`/`filter_health`, not by Qt. |
| `tabs.py` | Overview (count buttons open filtered lists; Likely unused by table; the status guide and caveat), Cleanup, Health, Diagnostics, Queries. |
| `detail.py` | HTML detail for objects (status text, evidence path, every evidence row with the status of its source when not Used), findings (relationship scopes shown as endpoints), diagnostics, query dependencies. Links resolve through an index, never through URLs built from paths. |
| `main_window.py` | Start page with recent projects (`QSettings`, per user), menus, F5 re-run keeping the selection by stable key, export via `write_reports` (JSON after a privacy prompt), diagnostics banner, About with the LGPL note. |

Core additions found necessary while building it: `HealthRow.scope_label`
(relationship endpoints instead of GUID names; the key keeps the scope) and
`Explainer.status_of`.

Verification: `tests/test_gui.py` (8 offscreen tests: worker run vs API counts,
filters and evidence path in the detail, health link to object and re-run keeping
the selection, internal toggle and diagnostics banner, query links, failed
analysis, export, `.pbip` path). Screens reviewed as offscreen screenshots of AW Mess.
Not done in G1 (as planned): opening a file at a line in an editor, run comparison,
acknowledgements, graph drawing, Windows build.

## 15. G3 result

| Item | Content |
| --- | --- |
| `packaging/pbi_model_health.spec` | PyInstaller one-folder, windowed (`console=False`) build named `PBI Model Health`; hidden import `openpyxl` (pandas loads the Excel engine by name); excludes tkinter/jsonschema/other toolkits; drops `opengl32sw.dll` (Mesa software OpenGL, 20 MB, unused by Qt Widgets, own license) and Qt translations (6 MB; English UI, no translator). |
| `packaging/write_notices.py` | `README.txt` (use, the Likely unused caveat, settings location, the Qt LGPL statement with replaceable-library note and source links), `THIRD_PARTY_NOTICES.txt` (Python plus the transitive runtime distributions of pandas, openpyxl and PySide6-Essentials with license expressions and copied license files) and `LICENSES\`. |
| `packaging/licenses/` | Official LGPL-3.0 and GPL-3.0 texts from gnu.org (SHA-256 e3a994d8… and 3972dc97…, the published values). The PySide6 wheels only carry a commercial-license reference. |
| `scripts/build_windows.ps1` | Checks the build dependencies, runs PyInstaller, writes the notices, runs `--smoke-test` on scenario 41 with `QT_QPA_PLATFORM=offscreen`, zips `PBI-Model-Health-<version>-win64.zip`. `-OutDir` for builds outside OneDrive. |
| `--smoke-test PROJECT OUT` | In `pbi_usage_analyzer_gui/app.py`: analysis, main window, `smoke-test.png`, all reports, `smoke-test.json`; exit code 1 with a traceback file on failure. |
| CI | Job "Windows application build" (after the Windows checks): same script, zip uploaded as artifact `pbi-model-health-windows` for 14 days. |

Verified 2026-10-01 on this machine (Python 3.14.7, PyInstaller 6.22.3, PySide6
6.11.2): zip 50.1 MB, folder 118.6 MB; the frozen app's smoke test on AW Mess
(opened through `AW Mess.pbip`, a OneDrive path with spaces) gives 178 cleanup and
45 health rows, the same as the library, and writes all three reports. Rendered
with the native platform, Qt follows the Windows dark mode; status colours now
have a light and a dark shade.

Not done: an application icon and a Windows version resource, code signing (Windows
SmartScreen may warn on first start of an unsigned download), an installer. The
project itself has no license file yet; decide one before distributing the app to
others.

## 16. G2 result

Core (`pbi_usage_analyzer/views/history.py`, tested in `tests/test_history.py`):

- `snapshot(result)` -> `RunSnapshot`: per object key the label, status and evidence
  path (use or lineage-review path); per health key the rule, scope label and title.
- `compare_runs(before, after)` -> `Change` rows (`ChangeKind`: status changed, object
  added/removed, finding added/resolved), ordered by kind and label; each status
  change carries the before and after evidence paths, so every change is explained.
- `ProjectState` (acknowledgements by stable key with note and date, plus the last
  run), versioned JSON (`format: 1`), atomic save, `ValueError` for unreadable or
  foreign files; `stale_acknowledgements`.
- `filter_objects`/`filter_health` accept `exclude_keys`; `Explanation.dependencies`
  (outgoing evidence); `CHANGE_LABELS` in the catalog.

GUI:

- State file per user and project: `<AppData>/projects/<sha256 of the normalized
  project path>.json` (`QStandardPaths.AppDataLocation`; with the app's names that is
  `%APPDATA%\pbi-usage-analyzer\Power BI Model Health Analyzer`). An unreadable file
  is moved aside (`*.unreadable-<time>.json`) with a warning, never overwritten
  silently. Tests and the smoke test pass their own folder (a test run once wrote
  into `%APPDATA%\Python` before this was added; those files were removed).
- Changes tab (and an Overview button): comparison with the previous analysis of
  the project, which is the last run on this computer, so it also works after a
  restart; the first run says there is nothing to compare yet. The detail shows
  before/now and both evidence paths, with a link to the object.
- Acknowledge… / Remove acknowledgement in Cleanup and Health (also Review menu,
  Ctrl+K / Ctrl+Shift+K), optional note; "Hide acknowledged" (on by default),
  an Acknowledged column with the note, the note in the detail panel, acknowledged
  counts on the Overview health buttons; Review > Remove acknowledgements of missing
  items. Selecting a hidden acknowledged item (e.g. from a link) reveals it.
- Detail panel "References" (what the object references or is loaded from) and
  links on evidence sources: walk the dependency graph one object at a time. A
  drawn graph view was not built; the links cover the navigation need.

Verification: `tests/test_history.py` (10), five new offscreen GUI tests (changes
across re-run and restart, acknowledgement persistence/hiding/removal, stale and
unreadable state, reference links); native renderings of the Changes tab and an
acknowledged object reviewed; the rebuilt Windows app passes its smoke test.

Remaining ideas (not planned phases): open a file at a line in an editor, a drawn
dependency graph, an app icon and version resource, code signing, an installer.
