# Architecture — Power BI Usage Analyzer V2

## Design goal

V2 treats cleanup analysis as a graph problem.

Parsers answer only: **what objects exist and what references what?**

The classifier answers: **what does that evidence imply?**

The reporters answer: **how should that conclusion be presented?**

This separation is intentional. It prevents parser-specific heuristics from silently becoming deletion decisions.

## Graph model

Nodes currently include:

- Table
- Query
- Column
- Measure
- Hierarchy

Edges/evidence currently include:

- DIRECT_REPORT_USE
- RAW_REPORT_REFERENCE
- DAX_DEPENDENCY
- RELATIONSHIP_DEPENDENCY
- HIERARCHY_DEPENDENCY
- SORT_DEPENDENCY
- FIELD_PARAMETER_DEPENDENCY
- RLS_DEPENDENCY
- CALCULATION_GROUP_DEPENDENCY
- POWERQUERY_QUERY_DEPENDENCY
- POWERQUERY_COLUMN_DEPENDENCY (bounded M lineage and auto-date projections)
- POWERQUERY_COLUMN_LINEAGE (downstream column -> upstream column it is loaded from)
- FALLBACK_MATCH
- INTERNAL_OBJECT

## Confidence and status

Strong report/model evidence can produce `Used`.

Ambiguous evidence produces `Needs manual review`.

`Likely unused` is only assigned after all supported evidence sources fail to protect an object.

## Usage propagation

A report reference to Measure A makes Measure A a used root.

If Measure A references Measure B, and Measure B references Column C, usage propagates:

    Report
      -> Measure A
      -> Measure B
      -> Column C

A DAX dependency whose owner is not itself proven used does not automatically make the target used. It may instead justify manual review.

## Power Query

Power Query supports bounded column-level lineage with a query-level fallback.

For example:

    Ledger
      -> Ledger 2024

If this edge is proven from the M partition source but column lineage is not, columns in `Ledger 2024` are protected as `Needs manual review` unless stronger evidence exists.

This is deliberately conservative because query-level lineage does not prove every upstream column is propagated. When column lineage is proven, usage-aware lineage (below) replaces it.

### Bounded M column lineage

A separate M tokenizer/parser traces symbolic column demands backward through complete supported expressions.

For example:

    Source = #"Ledger 2024",
    Selected = Table.SelectColumns(Source, {"Account", "Amount", "Company"})

creates column-level manual-review edges only for:

- Ledger 2024[Account]
- Ledger 2024[Amount]
- Ledger 2024[Company]

This will reduce false negatives without reintroducing risky false positives.

## PBIR safety net

Structured PBIR parsing is preferred.

The raw safety net exists only because Power BI can encode semantic references through structures not yet explicitly supported by the parser. A raw hit is never strong enough by itself to produce `Used`; it produces manual review.

Columns and measures not matched structurally share one rule for readable files
(`_readable_hit_files`, over a per-file `ReportText`): `Table.Field` with identifier
boundaries anywhere in the file's strings, DAX-style `'Table'[Field]`/`Table[Field]`
text, or the exact field name as a whole string value or unqualified `[Field]` when
the file's string values include the table name. JSON keys count only within
qualified forms. Substrings do not count: `Revenue Growth rate` does not protect
`Revenue`, `c10` does not protect `C1`, and the key `name` does not protect a `Name`
column. Unreadable files keep a looser substring rule because they have no structure.

## Extension rule

When adding support for a new Power BI construct:

1. Add a parser or extend the relevant parser.
2. Emit typed evidence.
3. Add regression fixtures.
4. Update classification semantics only if necessary.
5. Never make the parser directly write final statuses.

## Internal auto-date scope

`LocalDateTable_*` and `DateTableTemplate_*` objects remain in the graph for
inspection and receive internal evidence. Internal columns and measures are
excluded from business totals and cleanup candidates in both reports.

Internal query owners never expand a query dependency to every upstream column.
Relationships to an internal auto-date table give no evidence: Power BI creates one
for every date column while Auto date/time is on (19 in the AW Mess case study), so
the link says nothing about use. Report use of the auto-date hierarchy
(`PropertyVariationSource`) protects the backing column as `Used`.
For a single M partition with the complete shape
`let Source = Query, Selected = Table.SelectColumns(Source, {"Date"}) in Selected`,
the parser records the projection and graph construction resolves its source
column names through `sourceColumn` (falling back to model names when absent).
These column edges yield `Needs manual review`, not proven active use.

This is deliberately bounded support, not general M lineage. Other shapes,
multiple M partitions, or unresolved selected columns emit warnings without
inventing column edges. Do not interpret unprotected columns as safe to delete
when these warnings are present; inspect the query and relationship evidence.
Date-like names and data types are not used to guess a backing column.
Only actual M partitions are parsed for query dependencies; calculated partition
DAX is not interpreted as M. Shared expressions (load-disabled queries in
`expressions.tmdl`) are followed only when a partition references them: exact
lineage evaluates the referenced expression in place (cycle-guarded; unsupported M
there makes the owner's lineage unsupported), and the fallback reference scanner
walks them to the loaded tables behind them, recording the path in the evidence
reason (`Query 'Clean' references query 'Raw' through load-disabled query
'Staging'`). Load-disabled queries are not graph nodes and have no cleanup status.
Quoted identifiers count only outside comments and text literals. Ordinary business queries use complete column demands when available and otherwise
retain conservative query-level behavior.

### Supported M expressions and conservative boundaries

`parsers/m_lineage.py` returns symbolic included/excluded column names and schema
requirements. It parses named steps, direct query references, nested
`Table.SelectColumns`, `Table.RemoveColumns`, and `Table.Combine`. Select/remove
accept literal column lists and optionally `MissingField.Ignore`. Names and
comments are tokenized separately; local bindings are case-sensitive.

Default select/remove operations retain explicit schema requirements even when
later steps discard those columns. Requirements are unioned across repeated
inputs and partitions. No source schema is assumed complete. Graph construction
maps source names through `sourceColumn`, then emits
`POWERQUERY_COLUMN_DEPENDENCY` evidence with manual-review semantics.

### Usage-aware lineage

`parse_column_lineage` returns a `ColumnLineage` that keeps the parsed expression,
so source demands can be evaluated for any output demand: all outputs (above) or a
single output column. `build_graph` evaluates each loaded (non-calculated) column of
the owner by its `sourceColumn` and adds a `POWERQUERY_COLUMN_LINEAGE` edge from it
to every upstream column that can flow into it (`ColumnDemand.feeds`, which ignores
schema requirements). The classifier propagates Used along these edges like DAX
edges, then passes manual review from source to target; an unused source gives the
target nothing. Evidence path example:

    Visual -> Sales[Amount] -> Power Query append -> Sales 2023[Amount]

Upstream columns in the schema requirements still get `POWERQUERY_COLUMN_DEPENDENCY`
(manual review), because removing them breaks refresh regardless of use. So do
upstream columns that would flow into an output no model column loads (stale
metadata), and, when any loaded column lacks `sourceColumn` or a single-output
evaluation fails, every column the all-output demand accepts. Added columns flow
from their generator reads; an expanded alias flows from its inner field only.
Filter reads and join keys are requirements, not flows.

Every M partition must be supported before an ordinary query's blanket column
protection is narrowed. Unsupported syntax, unresolved references, cycles, and
complexity limits return unknown lineage and preserve the query-level fallback.
An empty proven column demand is distinct from unknown lineage. Query nodes
remain available for row-level dependencies even when no column is demanded.
Internal auto-date scope continues to use the separately bounded projection path.

Operation semantics follow Microsoft's documentation:
[SelectColumns](https://learn.microsoft.com/en-us/powerquery-m/table-selectcolumns),
[RemoveColumns](https://learn.microsoft.com/en-us/powerquery-m/table-removecolumns),
and [Combine](https://learn.microsoft.com/en-us/powerquery-m/table-combine).

### Rename and type transformations

Literal `Table.RenameColumns` pairs map downstream column demands and schema
requirements back to their original source names. Independent pairs in one call
and chains of separate calls are supported. Overlapping/duplicate pairs fall
back because their collision behavior needs a known schema. With
`MissingField.Ignore`, both the old name and an already-existing new name may be
origins, so both remain protected when demanded.

`Table.TransformColumnTypes` accepts literal pairs using scalar `type` values or
recognized numeric `.Type` constants, with an optional literal culture string.
All conversion inputs remain schema requirements even after later projections.
Dynamic types, culture records, and shadowed library symbols return unknown
lineage. This does not execute conversions or validate source values.

References: [RenameColumns](https://learn.microsoft.com/en-us/powerquery-m/table-renamecolumns)
and [TransformColumnTypes](https://learn.microsoft.com/en-us/powerquery-m/table-transformcolumntypes).

### Row filters and computed columns

`Table.SelectRows` and `Table.AddColumn` accept a bounded scalar `each` grammar:
direct `[Column]` or `[#"Column name"]` reads, numeric/text/logical/null literals,
unary operators, arithmetic, comparisons, logical operators, parentheses, and
conditionals. All conditional branches contribute dependencies. Parsing collects
reads without executing M or inferring runtime values.

Filter inputs remain required independently of the projected output. Added
column names are removed from upstream demands and replaced by generator reads.
Generator reads remain conservatively required even if the added column is
later discarded. This composes with separate add, rename, and projection steps.
Optional added-column types are limited to scalar `type` literals.

Unknown function calls, external bindings, explicit lambda parameters, dynamic/optional
field access, and nested record reads remain unsupported. Unknown expressions
preserve query-level fallback. Quoted identifiers are distinct from scalar
keywords, so a query named `true` is not mistaken for the logical literal.

References: [SelectRows](https://learn.microsoft.com/en-us/powerquery-m/table-selectrows)
and [AddColumn](https://learn.microsoft.com/en-us/powerquery-m/table-addcolumn).

### Joins and nested-table expansion

`Table.Join` and `Table.NestedJoin` accept literal string keys or nonempty lists
of unique keys with equal lengths on each side. Default join behavior and named
inner/left-outer/right-outer/full-outer kinds are supported. Both key sets are
always operational requirements. Flat joins conservatively send output-name
demands to both inputs because source schemas are not assumed complete.

Nested joins separate the generated nested column from ordinary left-side
columns. If the nested column survives, its right-side contents retain broad
protection; if it is discarded, right-side keys remain protected.
`Table.ExpandTableColumn` resolves a directly preceding nested join through
local aliases or `let` wrappers. Literal inner names and optional output aliases
map to the right input; left output demands exclude those generated aliases.
All expanded inner names remain schema requirements after projection.

Unknown nested provenance, unsupported intervening transformations, dynamic/mismatched keys,
custom comparers, join algorithms, unsupported kinds, duplicate output aliases,
and shadowed built-ins fall back. Alias resolution shares depth/work limits with
the lineage traversal. No join is executed and no cardinality is inferred.

References: [Join](https://learn.microsoft.com/en-us/powerquery-m/table-join),
[NestedJoin](https://learn.microsoft.com/en-us/powerquery-m/table-nestedjoin),
and [ExpandTableColumn](https://learn.microsoft.com/en-us/powerquery-m/table-expandtablecolumn).

### Scalar function semantics and filtered expansion

`m_scalar_functions.py` is an immutable allowlist of scalar built-ins and accepted
argument counts. Calls may nest within row expressions; all argument reads are
unioned. Every row-expression node records the called symbols, which are checked
against its lexical scope and model query names before lineage is accepted.
Unknown or shadowed calls fall back rather than assuming argument-only behavior.
Runtime values and types are not evaluated.

Supported row filters may intervene between a nested join and expansion.
Resolution accumulates predicate reads with their original lexical scope checks.
Left-side predicate reads remain required even after projection. Reading the
nested value protects all right-side contents conservatively. Aliases, filters,
let wrappers, and column selection/removal/renaming share the bounded resolution
traversal. Schema steps reuse the ordinary backward demand mapping. Renames map
both nested identity and predicate reads; schema-only requirements on the nested
column do not demand all its contents. Removed nested columns and ambiguous
`MissingField.Ignore` renames fall back. Other transformations still return
unknown provenance.

References: [Text.Contains](https://learn.microsoft.com/en-us/powerquery-m/text-contains),
[Number.Round](https://learn.microsoft.com/en-us/powerquery-m/number-round),
and [Date.Year](https://learn.microsoft.com/en-us/powerquery-m/date-year).

### Type conversions before nested expansion

The nested resolver accepts the same bounded scalar `Table.TransformColumnTypes`
syntax as ordinary lineage. Both paths share conversion-demand and symbol checks.
Converted fields remain required through earlier renames and later projections.
Conversions targeting the tracked nested column return unknown provenance; no
converted table contents or runtime conversion success are assumed.

### Presentation layer (`views`)

`pbi_usage_analyzer.views` is UI-agnostic and reads only an `AnalysisResult` (or a
graph plus findings): `catalog` (status/evidence/category labels; rule metadata in
`health.engine.RULE_INFO`), `explain` (evidence paths from the classifier's
`ROOT_EVIDENCE`/`PROPAGATING_EVIDENCE`/`OWNER_DEPENDENCY` sets, so explanations
cannot disagree with classification), and `rows` (frozen rows, stable keys,
filters). Reports may use it; it never imports reporting or a GUI toolkit (tested).
`reporting.files.write_reports` writes the standard files for the CLI and the GUI.
Design and phases: [GUI_DESIGN.md](GUI_DESIGN.md). The desktop viewer lives in the
separate package `pbi_usage_analyzer_gui` (optional PySide6 dependency); it renders
`views` rows and calls the API and `write_reports`, nothing else.

### Public application API

`pbi_usage_analyzer.analyze_project(path)` owns discovery, graph construction,
classification, diagnostic collection, and summary creation. It returns an
`AnalysisResult`; CLI and synthetic validation call this same entry point.
Analysis performs no terminal output or report writes. Fatal errors propagate.

The result exposes `project`, `findings`, `graph`, `objects`, `diagnostics`, and
`summary`. Its `context` retains parser details required by existing renderers.
Each call owns its graph and findings; a frozen result wrapper does not make the
nested data immutable. Business totals exclude internal objects, whose counts
are retained separately. Parsers and graph construction emit structured diagnostics directly. Existing
warning lists are derived compatibility views, preserving report text without
duplicating diagnostic state.

The API has no reporting-library dependency. Health findings are separate from
cleanup findings; serialization, progress events, and cancellation remain future work.

### Diagnostic contract

Shared types live in `diagnostics.py` and remain importable from the package API.
Diagnostics contain `code`, `severity`, `message`, `source_file`, optional
`object_ref`, and optional one-based `line`/`column` positions. Missing locations
are `None`; file-level diagnostics do not claim expression-level precision.

| Code | Origin | Location |
| --- | --- | --- |
| `TMDL_PARSE_FAILED` | Table parser failure | TMDL file |
| `PBIR_READ_FAILED` | Report definition load failure; raw text still scanned | JSON file; line/column for JSON decoding errors |
| `TMDL_DECODE_REPLACED` | Invalid UTF-8 in any definition TMDL file; bytes replaced | TMDL file |
| `M_LINEAGE_INCOMPLETE` | Unsupported M lineage | TMDL file and owning query |
| `AUTODATE_BACKING_COLUMN_UNRESOLVED` | Unresolved internal query projection | Referencing TMDL file and query |
| `AUTODATE_SOURCE_COLUMN_UNRESOLVED` | Selected source column cannot be matched | Referencing TMDL file and query |
| `DAX_UNTERMINATED_LITERAL` | Unterminated DAX string/block comment; tail kept as evidence | TMDL file and owning measure/column |

All current diagnostics have warning severity. Fatal exceptions still propagate.
The `warnings` property returns a fresh list of warning messages for existing
renderers; callers adding diagnostics must append to `diagnostics` instead.
Diagnostic ordering follows the existing parser/graph warning order.

### Model-health evaluation

Relationship parsing returns structured metadata once. Graph construction uses
its endpoint references; the health engine consumes the same parsed records
without changing dependency evidence or cleanup classifications. Relationship
headers delimit records, including adjacent records without blank separators.
Only direct relationship properties are interpreted, not nested annotation text.

`health/model.py` defines advisory findings and `health/engine.py` invokes the
explicit rule registry after cleanup classification. `AnalysisResult.health_findings`
contains stable rule IDs, category, severity, confidence, relationship scope,
explanation, evidence, recommendation and source file/header line. Report writers
receive these findings and render them without evaluating rules themselves.

`RELATIONSHIP_BIDIRECTIONAL` detects explicitly configured `bothDirections` on
active relationships (including the default active state) with parsed endpoints.
It is an advisory warning, not proof of ambiguity or poor performance. Inactive,
unknown and incomplete configurations are skipped. One-to-one and bridge designs
may legitimately need bidirectional filtering; the recommendation preserves that
caveat. Model cardinalities, runtime filter paths and performance are not inferred.

Reference: [Microsoft bidirectional relationship guidance](https://learn.microsoft.com/en-us/power-bi/guidance/relationships-bidirectional-filtering).

### Many-to-many relationship rule

Relationship metadata retains explicit `fromCardinality` and `toCardinality`
values, leaving omissions empty. `RELATIONSHIP_MANY_TO_MANY` applies the TMDL
defaults to omissions (`fromCardinality` many, `toCardinality` one; Power BI Desktop
writes many-to-many as only `toCardinality: many`) and requires many at both ends,
an active state (explicit or default), and parsed endpoints. Unknown and inactive
configurations are skipped. It does not infer data uniqueness, table roles or
runtime behavior.

The rule emits an advisory warning with endpoint/cardinality evidence and source
location. Its recommendation distinguishes fact-to-fact shared dimensions,
dimension bridges and legitimate higher-grain facts. It can coexist with the
bidirectional rule and never changes graph evidence or cleanup status.

Reference: [Microsoft many-to-many guidance](https://learn.microsoft.com/en-us/power-bi/guidance/relationships-many-to-many).

### Measure description opportunities

`ModelObject.description` stores parsed adjacent TMDL `///` descriptions and
`source_line` identifies the declaration. Empty text means absent/blank; `None`
means unknown or not parsed. Alternate `description:` syntax is conservatively
unknown. The rule engine consumes model objects as well as relationships.

`MEASURE_DESCRIPTION_MISSING` emits informational findings for parsed business
measures with empty descriptions. Internal auto-date objects are excluded.
Hidden business measures remain eligible for author-facing documentation.
Descriptions are not extracted from DAX strings, ordinary comments, or table/
column descriptions. No source content is changed, and descriptions do not
participate in dependency evidence or cleanup classification.

Reference: [TMDL descriptions](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview#descriptions).

`DAX_REFERENCE_UNRESOLVED` uses `parsers.dax.unresolved_references` with a
`DaxIndex` built from the model objects, so it applies the same masking and
qualified-table rules as dependency extraction. Columns now record `source_line`
like measures, so findings and JSON exports locate calculated columns.

`MEASURE_DUPLICATE_EXPRESSION` groups measures by `parsers.dax_lexer.normalize_dax`,
a comparison key built from the same tokenizer as `mask_dax`: comments dropped,
whitespace collapsed, names/functions casefolded, simple quoted table names
unquoted, string literals exact; unterminated input yields no key.

`parsers/m_queries.py` collects every M source as an `MQuery` (name, kind:
partition / expression / parameter, source, file, per-line file numbers) from
table partitions and `expressions.tmdl`, stored on the analysis context as
`m_queries`. `m_string_literals` scans M text literals outside comments and quoted
identifiers. `appended_query_refs` returns bare query identifiers in `Table.Combine({...})`
lists (comment/string-masked, local `let` names excluded). `POWERQUERY_HARDCODED_PATH`,
`folder_listing` returns `Folder.Files` calls, the first `[Content]` read and possible
file selections. `POWERQUERY_LOCAL_SERVER`, `POWERQUERY_APPEND_INPUT_LOADED`,
`POWERQUERY_ANNUAL_APPEND` and `POWERQUERY_FOLDER_UNFILTERED` consume these; dependency extraction
still uses its own partition reader; shared expressions reach it as
`shared_sources` (followed from partitions, not graph nodes).

### Health finding filters

The health engine has one explicit registry of stable IDs, evaluators and input
kinds. Each entry names the parsed inputs its evaluator receives, in order
(`relationships`, `objects`, `m_queries`); `RELATIONSHIP_TEXT_KEY` takes
relationships and objects to read endpoint data types. CLI choices and API filter
validation derive their IDs from that registry.
`health/filtering.py` normalizes selections and provides a pure, order-preserving
filter usable on existing findings. API options are validated before project I/O.

`None` is unrestricted; empty selections match nothing. Values within a dimension
are ORed; rule IDs and severities intersect. Invalid values raise `ValueError`
in the API and argparse errors in the CLI. Rule evaluation remains independent
of selection; filtering changes only returned/exported health findings, not
cleanup findings, diagnostics, evidence or summary counts.

### Recorded health-filter scope

`AnalysisResult.health_filter_scope` is a frozen `HealthFilterScope` containing
sorted, deduplicated rule IDs and severities plus total and selected finding
counts. Unrestricted dimensions remain `None`; empty selections remain empty
tuples. The API derives counts from the evaluated and selected findings once.

The CLI passes this metadata with findings to both renderers. A shared display
helper formats the scope; text Model health and Excel Summary include counts and
selection labels even when no findings remain. Legacy calls with no metadata
are marked “Not recorded,” not assumed unrestricted. In-memory filtering returns
a subset and does not mutate or recalculate an existing result's scope.

### Versioned JSON export

`reporting/json_report.py` projects `AnalysisResult` into schema version 1 without
rerunning analysis. Public helpers return a JSON-compatible dictionary or string,
or write UTF-8 to an explicitly supplied path. The CLI `--json` option adds a
report in the project root while preserving its existing text/Excel return values.

Top-level fields are `schema_version`, `analyzer_version`, `project`, `summary`,
`objects`, `dependency_evidence`, `cleanup_findings`, `diagnostics`,
`health_findings`, and `health_filter_scope`. Object references retain type,
table and name rather than ambiguous label-only identifiers. Cleanup findings
include an enum-name `status_id` plus display `status`. Paths are strings;
enums use values; tuples become arrays; unknown optional values remain null.

Objects are sorted by reference, keys are sorted, and no run timestamp is added.
Other arrays preserve analyzer order. Unicode is retained and nonfinite numbers
are rejected. Serialization completes before opening the output file. Graph
indexes, parser context and arbitrary object metadata are excluded. The export
includes local paths and parsed expressions; it is not an anonymized artifact.
Breaking export changes require a schema-version change. No import/deserialization
API is implemented. The export schema and development validation are described below.

### JSON Schema contract checks

`schemas/analysis-result-v1.schema.json` is a standalone Draft 2020-12 schema
with local references only. It defines every exported record and requires all
fields, rejecting additional fields. Cleanup status IDs and display values must
agree. Counts are nonnegative integers; known line/column positions are positive.
Null optional values and empty filter arrays remain distinct and valid.
Rule, evidence and diagnostic IDs follow an extensible identifier pattern.

Development uses `jsonschema` from `requirements-dev.txt`. Runtime analysis and
export do not import it. Both bootstrap scripts install development requirements.
Unit tests validate the schema itself, all synthetic exports with filter variants,
and malformed-document mutations. The synthetic validator also checks each
scenario's export. Schema validation checks structure, not graph semantics or
cross-field arithmetic; semantic invariants remain regression assertions.

### Standalone saved-export validation

`tools/validation/validate_json_export.py` loads the bundled schema relative to
its own location and validates a saved UTF-8 JSON document. It does not import
the analyzer, write files or depend on the current working directory. Duplicate
object keys and nonstandard numeric constants are rejected before schema checking.

Direct exit codes are 0 (valid), 1 (invalid input content/version), and 2
(usage/dependency/read/schema failure). Errors go to stderr, success to stdout.
Schema errors are ordered by escaped JSON Pointer and message; syntax errors
retain decoder line/column positions. `make validate-json EXPORT=...` wraps the
command, but callers needing exact exit codes should use the Python command.

### Saved-export consistency validation

After schema validation, `tools/validation/export_consistency.py` checks reference
uniqueness, cleanup coverage of model columns/measures, status-derived summary
counts, dependency targets and model-owned sources, query totals, health counts,
and recorded filter membership. It returns sorted JSON Pointer/message pairs
without importing the analyzer or modifying input. Both saved-export and
synthetic validators use these checks; inconsistent documents fail with exit 1.

Report-field sources and synthetic `Special:` table owners on RLS, field-parameter
and calculation-group evidence need not appear in model objects. Diagnostic
references can intentionally identify unresolved objects and are not constrained.
Query totals count only query-target query-dependency evidence, excluding column
fallback protections. Filtered pre-selection health totals can only be bounded;
unfiltered totals must equal the exported list length. These checks establish
internal consistency, not the correctness of original static analysis.

### Alpha coverage boundary

The [format coverage matrix](FORMAT_COVERAGE.md) distinguishes implementation
subsets, heuristics, tested examples and unsupported forms. Architecture goals
elsewhere in this document are not a claim of complete Power BI format support.

### Performance and determinism

`build_graph` builds one `DaxIndex` (table set, measures by name, non-internal
columns by name) and passes it to ordinary, special and failed-file DAX
resolution. `mask_dax` is a single regex tokenizer whose semantics are pinned by
a differential test against the former character loop. The report measure net
extracts DAX-style `Table[Field]` pairs once per file. Hierarchy levels are kept
in declaration order; outputs must not depend on `set` iteration order.

### Unqualified DAX references

`dax_dependencies(..., row_table=...)` resolves unqualified `[Name]` in order:
measure in the owner's table, unique measure model-wide, then a column of
`row_table` when the row context is certain (the table of a calculated column; the
table of an RLS `tablePermission`). These produce `DAX_DEPENDENCY` (RLS:
`RLS_DEPENDENCY`). Otherwise a same-named non-internal column yields
`DAX_UNQUALIFIED_COLUMN_REFERENCE` (manual review, never propagated), narrowed to
tables the masked expression names; this covers iterator arguments without binding
row context. Special-DAX converts only `DAX_DEPENDENCY` edges into special roots.
Unquoted DAX table names cannot contain spaces, so a qualified match's table is the
longest trailing word sequence that is a known table: `RETURN [Margin]` and
`NOT Sales[Flag]` resolve correctly. Scenario 28 covers this.

### DAX lexical masking

`parsers/dax_lexer.py` blanks DAX strings (with doubled-quote escapes) and `//`,
`--` and `/* */` comments, preserving offsets, newlines, and quoted/bracketed
identifiers. Ordinary measure/calculated-column dependencies are extracted from the
masked text. An unterminated string or block comment is left unmasked for ordinary
dependencies, so uncertain lexing never removes evidence, and reported as
`DAX_UNTERMINATED_LITERAL`. Special-DAX extraction masks such tails, which only
suppresses promotions to Used. Quoted table names unescape `''`; bracketed names
unescape `]]`. This is lexical masking, not a DAX grammar. Scenario 25 covers it.

`parsers/tmdl.py::extract_expression` uses the same masker to find where a
non-fenced multiline expression ends: the first line whose masked text begins with
`name:` or a known child keyword (`annotation`, `changedProperty`,
`extendedProperty`, `formatStringDefinition`, `isHidden`, ...). Indentation alone
is not relied on because Desktop writes tab-indented TMDL. An unterminated literal
masks the remaining block, so the expression extends rather than truncates.
Scenario 26 covers tab-indented expressions with colons in strings/comments.

### Damaged source files

Source files are read through `util.read_source_text` (UTF-8, BOM tolerated,
invalid bytes replaced) so one damaged file cannot abort analysis; `load_json`
also tolerates a BOM. Missing evidence is recovered only within the damaged scope:

- Unreadable PBIR JSON: raw text joins the report safety net; for these files the
  net also covers measures (`RAW_REPORT_REFERENCE`, manual review).
- TMDL table file whose parser raised (`TMDL_PARSE_FAILED`): its text is scanned
  for DAX references to known objects (`INCOMPLETE_SOURCE`, manual review).
- Column/measure whose name contains U+FFFD after decoding: `INCOMPLETE_SOURCE`,
  because references to its real name cannot be matched.

Unrelated objects are not downgraded. Scenario 27 and `tests/test_incomplete_sources.py`
cover these paths.

### Scoped special DAX evidence

`parsers/special_dax.py` replaces file-wide marker scanning. It descends through
recognized TMDL table/role/calculation-group/calculated-partition declarations,
extracts table-permission and calculation-item expressions (including item format
strings), and resolves only actual NAMEOF arguments for field-parameter evidence.
Annotations and unrelated declarations do not become expression roots. Inline,
continued, multiline and fenced expressions retain source declaration lines.

A bounded lexical pass masks DAX strings and comments while preserving quoted
identifiers and newlines. It does not evaluate DAX or establish item activation;
calculation-item targets remain manual review absent other usage. The same
masker (`parsers/dax_lexer.py`) is applied to ordinary DAX dependencies. Unsupported
TMDL shapes and broader calculation-group selection expressions remain gaps.
Scenario 24 records the false-use regression; scenarios 21–23 retain positive
coverage. No business-project names are special-cased.
