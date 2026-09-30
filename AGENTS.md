# AGENTS.md — Power BI Model Health Analyzer

## Project stage

This repository has moved beyond the scope of a one-off script.

Treat it as a maintained software project with:
- explicit architecture
- regression tests
- synthetic validation fixtures
- version control
- stable internal data models
- multiple front ends planned over time (CLI/reporting first, GUI later)
- optional AI-assisted interpretation later

Do not solve substantial changes by adding ad-hoc logic to whichever file is convenient.
Prefer changes that strengthen the architecture and leave the project easier to extend.

A future intuitive GUI is a design requirement now, even though the GUI itself is not yet a development priority.

## Mission

Build and maintain a conservative static-analysis and model-health tool for Power BI PBIP/PBIR projects.

The product should eventually cover three related concerns:

1. Dependency and lineage analysis
2. Cleanup / unused-object analysis
3. Best-practice and model-health assessment with concrete recommendations

The core analyzer must remain deterministic and useful without an AI service.
AI may later be added as an optional advisory layer over structured findings.

## Primary risk principle

The cleanup analyzer has asymmetric error costs:

- False positive: an object is reported as unused although it is required.
- False negative: an unused object is retained or sent to manual review.

False positives are more dangerous because users may delete required objects.

When evidence is credible but insufficient, prefer `Needs manual review` over `Likely unused`.

However, conservatism must be evidence-based. A weak textual occurrence must not protect an entire table.

Never present `Likely unused` as equivalent to `safe to delete`.

## Architecture invariant

This is a dependency-graph application, not a collection of independent regex checks.

Pipeline:

1. Discover PBIP/PBIR project structure.
2. Parse source formats into structured objects and evidence.
3. Build one dependency graph.
4. Propagate proven usage through the graph.
5. Classify objects from graph evidence.
6. Run model-health / best-practice rules against structured analysis state.
7. Produce structured `AnalysisResult` / `Finding` data.
8. Render that data through CLI, text, Excel, and later GUI front ends.

Parsers must not directly decide final status.
Report writers must not contain analysis logic.
GUI code must never become the home of domain logic.

## UI-agnostic core

Design every change so the core analyzer can be called as a Python library.

Do not require terminal I/O for core analysis.

Avoid `print()` inside parsers, graph construction, classification, or rule evaluation.
Return structured diagnostics instead.

Prefer an eventual API shaped roughly like:

    result = analyze_project(path)

where `result` contains:
- project metadata
- discovered model objects
- dependency graph/evidence
- cleanup classifications
- model-health findings
- warnings/errors/notes
- summary statistics

A future GUI must be able to consume this result without re-running or re-implementing analysis logic.

## Structured findings

Best-practice and model-health rules should emit structured findings, not prose-only messages.

A finding should have stable fields such as:

- rule_id
- category
- severity
- confidence
- object_ref / scope
- title
- explanation
- evidence
- recommendation
- source locations

Use stable IDs so a future GUI can filter findings and users can suppress/acknowledge specific rules.

Differentiate:
- deterministic rule violations
- heuristics
- informational opportunities

Do not label subjective architectural preferences as hard errors.

## Future GUI requirement

The intended product path includes an intuitive GUI after the analysis and rule engines stabilize.

Therefore:
- keep presentation separate from analysis
- use enums / stable identifiers rather than prose as internal state
- keep short labels separate from long explanations
- expose progress and diagnostics in structured form
- make long-running analysis cancellable/progress-reportable where practical
- avoid global mutable state
- do not add a GUI framework dependency to the core package

When GUI development begins, prefer a thin desktop front end over the existing Python API rather than duplicating logic.

## Future AI layer

AI is optional and should sit above deterministic analysis:

    static analysis
        -> structured findings/evidence
        -> optional AI synthesis/prioritization

Do not send a PBIP project to an AI service merely to discover dependencies that can be parsed deterministically.

Possible future AI responsibilities:
- summarize patterns across many findings
- explain likely architectural themes
- prioritize remediation
- draft a migration/refactoring plan
- translate technical findings for nontechnical users

Keep AI adapters isolated behind an interface so the analyzer works fully without API credentials or network access.

## PBIR report sources

Inspect report-, page-, and visual-level definitions when present, including:

- `definition/report.json`
- `definition/pages/*/page.json`
- `definition/pages/*/visuals/*/visual.json`

Consider:
- columns and measures
- implicit aggregations
- visual fields
- slicers
- filters at visual/page/report level
- drillthrough
- tooltip fields
- sort fields
- hierarchy and hierarchy-level references
- conditional formatting references
- semantic query/projection structures
- field parameters and indirect report structures

Do not assume a report reference always appears as a simple `Column -> Property` node.

After structured parsing, use a conservative raw-report safety net.
A credible unresolved occurrence should produce `Needs manual review`, not `Likely unused`.

## TMDL semantic model sources

Inspect the complete semantic model under `<project>.SemanticModel/definition/`.

Parse, where present:
- tables
- columns
- calculated columns
- measures
- hierarchies
- relationships
- partitions
- Power Query/M expressions
- calculation groups/items
- roles/RLS
- sort-by-column metadata
- `sourceColumn`
- data types
- field parameters / `NAMEOF`
- annotations when relevant

## DAX dependencies

Build dependency edges for:
- measure -> column
- measure -> measure
- calculated column -> column
- calculated column -> measure
- calculated table -> model objects where supported
- calculation items -> model objects
- RLS -> model objects
- field parameters -> model objects

Dependencies are transitive.

Example:

    Visual -> Measure A -> Measure B -> Column C

must protect Column C.

## Relationships

Both relationship endpoint columns are dependencies even if no visual references them.

## Hierarchies

Hierarchy levels protect their backing columns.

Treat Power BI internal auto-date objects separately from normal business-model objects.

`LocalDateTable_*` and `DateTableTemplate_*` must not:
- inflate business-column counts
- cause all columns of an upstream table to be protected
- appear as ordinary cleanup candidates

An auto-date dependency should protect only the specific backing date column when that relationship can be resolved.

## Sort-by

If Column A sorts by Column B, a used Column A protects Column B.

## Power Query / M

Power Query dependencies are first-class dependencies.

A query can be essential even if the report never references it directly.

Example:

    Hovedbok -> Hovedbok 2024

when M contains:

    Table.Combine({#"Fjernede kolonner", #"Hovedbok 2024"})

### Critical M rule

Infer query dependencies only from actual M partition expressions.

Never scan an entire TMDL file for table names and treat textual occurrence as a dependency.

Do not create dependencies from:
- strings
- comments
- DAX
- annotations
- column references
- local `let` step names
- unrelated TMDL metadata

Recognize strong query references such as `#"Query Name"`.
Simple identifiers require syntactic evidence.

### Query-level vs column-level lineage

A query-level dependency does not prove every upstream column is required.

Until column-level M lineage is proven, relevant upstream columns may be `Needs manual review`, not `Used`.

Develop column-level lineage incrementally for operations such as:
- `Table.SelectColumns`
- `Table.RemoveColumns`
- `Table.RenameColumns`
- `Table.TransformColumnTypes`
- `Table.ExpandTableColumn`
- `Table.NestedJoin`
- `Table.Join`
- `Table.Group`
- `Table.Sort`
- `Table.SelectRows`
- `Table.AddColumn`
- `Table.Combine`

## Identifier normalization

Maintain original display names plus separate normalized matching keys.

Matching should:
- trim leading/trailing whitespace
- remove TMDL quoting where appropriate
- unescape doubled apostrophes
- use Unicode-aware case-insensitive comparison (`casefold`)

Examples that should normally resolve together:
- `Beløp`
- `BELØP`
- `beløp`
- `'beløp '`

Never alter the original display name in reports.

## Status semantics

### Used
Strong evidence of active use, directly or through a proven dependency path.

### Needs manual review
Credible evidence exists but active use cannot be proven confidently.

Examples:
- unresolved PBIR reference
- query-level Power Query dependency without column lineage
- incomplete calculation-group/RLS parsing
- unknown/custom report structures

### Likely unused
No applicable parser or safety mechanism found known or credible dependency evidence.

### Internal / auto-generated
Power BI internal objects such as auto-date tables.

## Best-practice / model-health engine

Implement best-practice checks as explicit rules, separate from cleanup classification.

Rules should be testable and evidence-driven.

Potential categories:
- Source architecture
- Power Query
- Semantic model
- Relationships
- DAX
- Naming/metadata
- Performance
- Maintainability
- Report architecture

Examples of deterministic or high-confidence checks:
- staging query appears loaded into the semantic model
- redundant/no-op Power Query step
- hard-coded annual append pattern
- wide imported table with many confirmed unused source columns
- many auto-date tables / Auto Date-Time dependence
- relationship on inappropriate/high-cardinality text keys when confidently detectable
- bidirectional relationships
- many-to-many relationships
- hidden support/key columns that remain exposed
- measure metadata/description/display-folder gaps
- hard-coded file paths/URLs in M
- duplicate or near-duplicate measures when deterministic comparison supports it

A recommendation must explain:
1. what was detected
2. why it may matter
3. concrete remediation
4. confidence / caveats

Do not turn every style preference into a warning.

## Evidence paths

Keep human-readable evidence for every classification and rule.

Prefer dependency paths over booleans.

Examples:

    Visual -> Hovedbok[Omsetning] -> DAX -> Hovedbok[beløp]

    Hovedbok -> Power Query append -> Hovedbok 2024

## Regression tests

Every bug fix should become a regression test or synthetic validation scenario when feasible.

Required regression areas include:
1. implicit numeric aggregation
2. Unicode/case/whitespace normalization
3. Power Query append
4. no false M dependencies from strings/comments/metadata/local steps
5. no invented circular M dependencies
6. transitive DAX dependencies
7. relationship-only keys
8. sort-by-only keys
9. `NAMEOF(...)`
10. stale report references
11. auto-date scope isolation
12. raw PBIR safety-net behavior

## Synthetic validation workflow

Prefer explicit synthetic PBIP/PBIR/TMDL fixtures with known ground truth over random dummy rows.

For a real-world bug:
1. reproduce it in the smallest synthetic fixture possible
2. encode the expected result
3. confirm the test fails before the fix when practical
4. implement the fix
5. run the whole suite
6. retain the fixture permanently

The `Forvaltningskunder` project is an integration/regression reference, not the only test corpus.

## Known Forvaltningskunder regression facts

When that project is available:
- `Hovedbok` genuinely appends `Hovedbok 2024`.
- Do not invent unrelated dependencies on `Firma`, `Dates`, or `tjenesteoversikt`.
- `Hovedbok[beløp]` is heavily used and must never be `Likely unused`.
- Power BI auto-date tables must not cause unrelated columns in `Firma`, `Hovedbok`, or `tjenesteoversikt` to be protected.

## Validation workflow for significant changes

Run:
1. syntax/compile checks
2. unit/regression tests
3. synthetic validation suite
4. representative PBIP integration test when available
5. comparison against previous classification counts

Investigate large classification changes before accepting them.

A lower unused count is not automatically safer.
A higher unused count is not automatically more useful.

Large changes must be explainable through explicit evidence changes.

## Agentic development workflow

This repository is now expected to be developed in an IDE/repository workflow rather than through ad-hoc pasted scripts.

For nontrivial work:
1. inspect `AGENTS.md`, `docs/architecture.md`, and `docs/ROADMAP.md`
2. inspect relevant tests before editing
3. state the intended architecture-level change internally before modifying code
4. make the smallest coherent change that solves the issue
5. add/update tests and synthetic fixtures
6. run targeted tests first, then the full validation suite
7. inspect `git diff` for unintended changes
8. summarize what changed, evidence, tests run, and known limitations

Do not overwrite unrelated user changes.

Do not commit or push unless the user explicitly asks.

## Subagents

When the Codex environment supports subagents, use them selectively for independent work that benefits from separate context.

Good subagent tasks:
- inspect a new PBIR structure while the main agent works on architecture
- investigate TMDL or M syntax independently
- review a proposed parser change for false-positive risks
- run/triage noisy test suites
- compare old/new classification output
- review best-practice rules for false positives

Do not delegate:
- tiny tasks
- tightly sequential edits
- concurrent edits to the same files without explicit coordination

The main agent owns integration and must verify subagent conclusions before merging them into the codebase.

## Engineering style

Prefer small modules with one responsibility:
- project discovery
- PBIR parsing
- TMDL parsing
- DAX parsing
- M parsing
- graph construction
- classification
- best-practice rules
- reporting

Keep parsing, classification, rules, and reporting separate.

Collect warnings/errors/notes in structured form rather than raising exceptions for nonfatal validation issues.

Use exceptions for genuinely fatal conditions such as an unreadable/missing required project root.

Prefer standard-library solutions when reasonable. Add dependencies only when they materially improve correctness or maintainability.

Avoid module-level/global variable type annotations unless they are needed for correctness or tooling.

## Output expectations

User-facing output should remain concrete and understandable.

Plain-text summary remains the primary simple report.
Excel remains the technical audit artifact.

Future GUI should present the same structured findings rather than inventing a parallel analysis path.

## Local database integration environment

The repository includes an optional disposable MariaDB integration environment
under `integration/mariadb/`.

Use it only when a real relational source adds validation value. It is the
third test layer after unit tests and synthetic PBIP fixtures.

Requirements:
- synthetic data only
- never use organizational or production credentials
- never point automated integration tests at production systems
- database-backed tests must remain optional
- normal unit/regression tests must run without Docker or MariaDB
- prefer reproducible Docker Compose lifecycle over modifying a permanent
  machine-level MariaDB installation
- reset state rather than relying on manually accumulated database contents

When adding a database-backed bug scenario, keep expected behavior explicit and
add a corresponding static/synthetic fixture too when feasible.

## Privileged access and credentials

Do not request, record, read, store, echo, or commit the user's sudo password.

Never put an operating-system password in:
- repository files
- `.env`
- VS Code settings
- prompts/instructions
- scripts
- logs

Routine agent development should not require administrator privilege.

Prefer:
- `.venv` for Python isolation
- rootless containers where practical
- an already-authorized Docker runtime
- narrowly scoped, user-reviewed one-time machine setup

If a task genuinely requires elevated machine-level access, stop and explain
the exact command and why elevation is necessary. Let the user authorize that
operation interactively.

Do not propose or create blanket passwordless sudo such as:

    ALL=(ALL) NOPASSWD: ALL

If a narrowly scoped sudoers exception is ever justified, it must be limited
to specific reviewed commands and documented as an explicit security tradeoff.

## Primary host environment: Ubuntu

Assume Ubuntu/Linux is the primary development host unless the user explicitly
states otherwise.

Preferred project commands:

    make check
    make setup
    make compile
    make test
    make validate
    make db-up
    make db-down
    make db-reset

Prefer repository scripts/Makefile targets over inventing new host commands.

Before doing substantial work, verify the local project environment rather than
assuming tools are installed.

### Host bootstrap boundary

The agent may:
- inspect whether prerequisites exist
- create/use `.venv`
- install Python packages inside `.venv`
- run repository scripts
- run tests
- use Docker Compose when Docker is already available to the current user
- create/reset the disposable MariaDB integration environment

The agent must not silently modify the Ubuntu host or install privileged system
packages.

If Python venv support, Docker, Docker Compose, or another host prerequisite is
missing:
1. report exactly what is missing
2. point to `docs/UBUNTU_SETUP.md`
3. provide the user with the exact host-level step that needs interactive
   authorization when appropriate
4. continue with unprivileged work that does not require that prerequisite

Never request or store the user's sudo password.

### Docker integration

Docker/MariaDB is an optional integration-test layer, not a requirement for
unit/regression tests.

Use:

    make db-up

only after `docker info` succeeds for the current user.

If Docker access requires privilege, do not work around this by embedding sudo
or storing credentials. Stop at the host boundary and let the user configure
Docker access interactively.

