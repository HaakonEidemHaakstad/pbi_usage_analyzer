# Power BI Usage Analyzer

This repository is intended to be opened as a project in VS Code.

Start here:

- [AGENTS.md](AGENTS.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)

Windows quick start:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

Then run:

```shell
python -m unittest discover -s tests -v
```


## Power BI Usage Analyzer V2

This is a modular version of the analyzer for Power BI PBIP/PBIR projects.

The goal is to identify cleanup candidates in the semantic model without incorrectly suggesting the deletion of objects required by the report or model.

V2 uses an explicit dependency graph. Parsers identify objects and dependencies, while a separate classifier determines whether objects are used.

## Architecture

The analysis pipeline is:

    PBIR + TMDL + DAX + relationships + hierarchies + Power Query/M
                              |
                              v
                       Dependency graph
                              |
                              v
                       Usage propagation
                              |
                              v
                        Classification
                              |
                 +------------+------------+
                 |                         |
                 v                         v
          TXT summary report          Excel audit

The classifications are:

- **Used**: Strong evidence shows that the object is required.
- **Needs manual review**: A credible dependency or reference exists, but the analysis cannot confidently establish active use.
- **Likely unused**: No known report usage or relevant dependency was found.
- **Internal / auto-generated**: An internal Power BI object.

"Likely unused" does not mean "guaranteed safe to delete."

## Installation

Python 3 is required. Ubuntu/Linux is the primary development platform.

Create a local Python environment and install dependencies:

```bash
make setup
```

See [Ubuntu setup](docs/UBUNTU_SETUP.md). Docker is optional for normal tests, although `make check` reports it as a missing prerequisite when it is unavailable.

## Running the analyzer

From the repository root:

```bash
make analyze PROJECT="/path/to/PBIP-project"
```

Alternatively, use the project's Python virtual environment:

```bash
.venv/bin/python run_analyzer.py "/path/to/PBIP-project"
```

The expected project structure is typically:

```text
Project.pbip
Project.Report/
Project.SemanticModel/
```

## Output

The analyzer creates:

```text
<Project>_usage_summary_v2.txt
<Project>_usage_analysis_v2.xlsx
```

## Analysis sources

V2 inspects:

- visual, page, and report references in PBIR
- measures and columns in TMDL
- DAX dependencies
- relationships
- hierarchies
- sort-by-column metadata
- Power BI auto-date objects
- field parameters / `NAMEOF` where identifiable
- some RLS and calculation-group references
- Power Query/M dependencies between queries
- raw PBIR references as a safety net

## Power Query / M

The M parser infers query dependencies only from actual M expressions in partition `source =` blocks.

For example, this expression in a `Ledger` query:

```powerquery
Table.Combine({#"Removed Columns", #"Ledger 2024"})
```

should identify `Ledger` as depending on `Ledger 2024`.

A table name appearing only in metadata, DAX, a string, or a comment must not create a Power Query dependency.

Internal `LocalDateTable_*` and `DateTableTemplate_*` objects are excluded from business-object counts. They protect only specifically identified columns through relationships or supported `Table.SelectColumns` expressions. Unresolved auto-date lineage produces warnings.

V2 distinguishes query-level lineage from column-level lineage. A query-level dependency from a normal model table currently protects upstream columns conservatively as "Needs manual review." This does not mean that every column is required.

## Column-level Power Query lineage

The analyzer traces source-column requirements through complete expressions using
`Table.SelectColumns`, `Table.RemoveColumns`, and `Table.Combine`, including named
steps and nested calls. Column lists must be literal lists. Select/remove support
an optional `MissingField.Ignore` argument. Requirements from multiple M
partitions are combined.

Supported expressions narrow upstream protection to output columns and columns
required by the transformation's schema. For example, default `RemoveColumns`
still requires the removed column to exist; `MissingField.Ignore` allows it to be
absent. Column-level evidence remains **Needs manual review**, not proven active
use. Source names are resolved through TMDL `sourceColumn` metadata.

If any partition uses unsupported syntax, ordinary queries retain conservative
query-level protection. Internal auto-date queries retain their separate bounded
scope. This is static analysis, not execution of M or a complete schema inference
engine.

## Next planned improvement

Extend lineage to renaming and type transformations, then joins, filters, and
computed columns while preserving their operational dependencies. General M
expressions, dynamic column lists, and connector-specific schemas remain outside
the current bounded implementation.

## Development

Agent and development guidelines are in [AGENTS.md](AGENTS.md).

Run the checks with:

```bash
make compile
make test
make validate
```

Extend regression coverage whenever a new class of bug is discovered.


## Optional MariaDB integration

See:

- [docs/MARIADB_INTEGRATION.md](docs/MARIADB_INTEGRATION.md)
- [docs/PRIVILEGED_ACCESS.md](docs/PRIVILEGED_ACCESS.md)

The MariaDB environment is disposable and Docker-based. Do not store a sudo
password in the repository or give the coding agent a reusable OS credential.

## Ubuntu / VS Code quick start

Ubuntu is now the primary development platform.

    make check
    make setup
    make test
    make validate

Optional MariaDB integration:

    make db-up
    make db-down
    make db-reset

See:

- [docs/UBUNTU_SETUP.md](docs/UBUNTU_SETUP.md)
