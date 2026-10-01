# Roadmap

## Product direction

This project is no longer treated as a one-off unused-column script.
It is evolving into a Power BI model-health analyzer with a reusable core.

The preferred development order is intentionally staged so presentation layers
do not outrun correctness.

## Phase 1 — Analyzer correctness and validation

Priority:
- dependency graph correctness
- PBIR coverage
- DAX dependency propagation
- relationship/hierarchy/sort dependencies
- precise Power Query query dependencies
- auto-date isolation
- extend bounded column-level Power Query lineage through selection, removal, and renaming of nested-table columns
- stale/fallback reference handling
- synthetic regression fixtures

Exit criterion:
Classification changes are explainable and the synthetic suite gives useful,
stable ground truth.

## Phase 2 — Best-practice / model-health rules

Implemented a structured rule engine separate from cleanup classification,
with an advisory bidirectional relationship rule and text/Excel/API output.

Rule families:
- source architecture
- Power Query maintainability
- semantic-model design
- relationships
- DAX
- metadata/naming
- performance
- maintainability

Rules need stable IDs, severity, confidence, evidence, and actionable
recommendations.

## Phase 3 — Stable application API

Implemented: a public UI-agnostic API:

    result = analyze_project(path)

The result exposes cleanup findings, diagnostics, dependencies, statistics and
evidence. The CLI and synthetic validator use this entry point. Parser-specific
diagnostic codes and available source locations are implemented.

Add progress reporting/cancellation hooks if analysis duration makes them useful.

## Phase 4 — Intuitive GUI

Build a thin GUI over the application API.

Likely capabilities:
- choose PBIP project
- run analysis
- dashboard/model-health overview
- Cleanup / Manual review / Best practices tabs
- searchable/filterable findings
- details/evidence side panel
- dependency graph exploration
- export text/Excel
- progress and diagnostics

Do not move analysis logic into the GUI.

## Phase 5 — Optional AI advisory layer

AI should consume structured deterministic findings rather than replace parsing.

Possible use:
- prioritize remediation
- synthesize architectural patterns
- explain findings for different audiences
- propose migration/refactoring plans

Core analysis must remain fully usable offline and without API credentials.


## Cross-cutting validation — Database-backed integration validation

Maintain an optional disposable MariaDB environment for tests that need a real
relational source.

It complements rather than replaces synthetic static fixtures.

Future database-backed validation can cover:
- realistic fact/dimension sources
- annual/staging tables
- views
- schema evolution
- source-column reduction
- connector behavior
- query-folding experiments where Power BI tooling makes them observable

Completed: nested expansion now follows column selection, removal, and renaming,
with schema requirements and renamed predicate reads retained. Ambiguous nested
identity falls back conservatively. Bounded type conversions before expansion are also complete, with conversion
requirements preserved and nested-column conversions rejected. The public structured analysis API is now implemented.
Parser-specific diagnostic codes and available source locations are implemented.
The first relationship rule and separate model-health engine are implemented.
Explicit many-to-many relationship findings are implemented.
Missing measure descriptions now produce informational documentation findings.
Rule-ID and severity filtering in the API and CLI is implemented.
Applied filter scope and before/after finding counts are recorded in results
and exported reports. Versioned JSON export is implemented for automation.
JSON Schema version 1 is published and checked by regression/synthetic validation.
Standalone saved-export validation is implemented.
Semantic checks for exported totals, references and filter scope are implemented.
Continuous integration for compilation, regression and synthetic validation is
configured, including a non-mutating generated fixture drift check.
Runtime-dependencies-only API/CLI and export smoke testing is included in CI.
The [format coverage matrix](FORMAT_COVERAGE.md) documents tested subsets and
known alpha gaps. Dedicated field-parameter, RLS and calculation-item fixtures
now verify positive references, evidence provenance and classification boundaries.
Special DAX scanning is scoped to relevant expressions with negative regressions.
Ordinary DAX dependency extraction masks strings and comments (scenario 25) and
unescapes `''`/`]]` in identifiers.
Multiline TMDL expressions end only at property-shaped lines evaluated on
DAX-masked text (scenario 26); colons in DAX strings/comments no longer truncate them.
Damaged sources add scoped manual-review evidence (scenario 27): unreadable report
JSON is raw-scanned (columns and measures), failed TMDL table files are scanned for
DAX references, and BOM/invalid UTF-8 no longer abort or hide files.
Unqualified DAX columns resolve in certain row contexts (calculated columns, RLS);
other unqualified columns are manual review (scenario 28). Keywords/variables before
`[` no longer swallow measure references (`RETURN [Measure]`).
The report safety net covers measures in readable files with a stricter rule
(scenario 29).
DAX name indexes are built once per analysis, masking uses a regex tokenizer and
the report measure net extracts qualified names once per file: the generated
3,300-object model went from 5.4 s to about 1 s with identical output.
Evidence order no longer depends on the hash seed.
The report safety net uses one qualified/whole-name rule for columns and measures
in readable files (scenario 30); substrings and JSON keys no longer protect columns.
First real-project check (AdventureWorks): current-format PBIR `SourceRef.Entity`
fields and nested hierarchy levels are now resolved; M simple identifiers match
case-sensitively (scenarios 31–32; optional integration test).
A multi-source bad-practice case study (MariaDB, Excel, CSV, JSON) has a source
generator and a build guide with an answer key (docs/CASE_STUDY_ADVENTUREWORKS.md).
`DAX_REFERENCE_UNRESOLVED` reports references to missing columns/measures.
`POWERQUERY_HARDCODED_PATH` reports literal drive/UNC paths in partitions and shared queries.
`POWERQUERY_APPEND_INPUT_LOADED` and `POWERQUERY_ANNUAL_APPEND` report loaded append
inputs and year-named append inputs (scenario 35).
`POWERQUERY_FOLDER_UNFILTERED` reports folder combines without file selection (scenario 36).
Next: build it in Power BI Desktop and score the analyzer; turn the answer key's
remaining "not yet" items (duplicate measures, server names, text keys,
name-based staging) into health rules; then GUI planning.
