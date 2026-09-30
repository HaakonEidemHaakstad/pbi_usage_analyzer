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
