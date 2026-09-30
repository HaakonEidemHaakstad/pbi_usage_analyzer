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
- extend bounded column-level Power Query lineage beyond select/remove/combine
- stale/fallback reference handling
- synthetic regression fixtures

Exit criterion:
Classification changes are explainable and the synthetic suite gives useful,
stable ground truth.

## Phase 2 — Best-practice / model-health rules

Add a structured rule engine separate from cleanup classification.

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

Consolidate analysis into a UI-agnostic API such as:

    result = analyze_project(path)

The result should expose structured findings, diagnostics, dependencies,
statistics and evidence.

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
