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

If this edge is proven from the M partition source, columns in `Ledger 2024` are protected as `Needs manual review` unless stronger evidence exists.

This is deliberately conservative because query-level lineage does not prove every upstream column is propagated.

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
Relationship endpoints still protect the exact backing column as `Used`.
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
DAX is not interpreted as M. Ordinary business queries use complete column demands when available and otherwise
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
and let wrappers share the bounded resolution traversal; other transformations
still return unknown provenance.

References: [Text.Contains](https://learn.microsoft.com/en-us/powerquery-m/text-contains),
[Number.Round](https://learn.microsoft.com/en-us/powerquery-m/number-round),
and [Date.Year](https://learn.microsoft.com/en-us/powerquery-m/date-year).
