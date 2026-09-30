# Power BI Usage Analyzer

This repository is intended to be opened as a project in VS Code.

Start here:

- [AGENTS.md](AGENTS.md)
- [Agent handoff and current state](docs/HANDOFF.md)
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
`Table.SelectColumns`, `Table.RemoveColumns`, `Table.Combine`,
`Table.RenameColumns`, `Table.TransformColumnTypes`, `Table.SelectRows`, and
`Table.AddColumn`, `Table.Join`, `Table.NestedJoin`, and
`Table.ExpandTableColumn`, including named
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

Renames support literal pairs or lists of independent pairs, optionally with
`MissingField.Ignore`. Separate rename steps can be chained. Type changes support
literal column/type pairs, standard scalar types, and an optional culture string.
Conversion columns remain protected even if a later projection removes them.
Dynamic mappings, overlapping rename pairs, and culture records retain fallback
behavior.

Row filters and computed columns support bounded `each` expressions with direct
field reads, scalar literals, arithmetic, comparisons, logical operators,
parentheses, and `if`/`then`/`else`. Predicate columns remain required after output
projection. Computed outputs map back to their input fields; generator reads are
retained conservatively even when the output is dropped. Unknown function calls, dynamic
field access, nested record access, and external bindings retain fallback behavior.

Joins support literal single/composite keys and default, inner, left outer,
right outer, or full outer kinds. Both input keys remain protected. Flat joins
conservatively apply output-name demands to both inputs. Nested expansion maps
explicit output aliases to the right-hand source when its input resolves directly
to a nested join through aliases, `let` wrappers, supported row filters, column selection/removal/renaming, or supported scalar type conversions. Expanded fields remain schema
requirements even if later discarded. Unexpanded nested results protect all
right-hand columns when retained.

Dynamic keys, comparers, join algorithms, semi/anti joins, and other transformations
between nested join and expansion remain unsupported and retain fallback.

Supported scalar calls include text contains/starts/ends checks, case conversion,
trimming, length, replacement and conversion; number absolute value, rounding and
conversion; and date year/month/day extraction and conversion. The exact function
names and accepted argument counts are listed in
[`m_scalar_functions.py`](pbi_usage_analyzer/parsers/m_scalar_functions.py).
Nested calls retain every argument's column reads. Custom comparers, additional
culture/rounding options, and shadowed functions remain unsupported.

Filters between a nested join and expansion retain their predicate dependencies.
A predicate reading the nested value conservatively protects its contents.

Type conversions before expansion retain converted input columns even when later
projected away. Conversions targeting the nested column, unknown types, and
shadowed conversion functions or type constants retain conservative fallback.

## Python library API

```python
from pbi_usage_analyzer import analyze_project

result = analyze_project("/path/to/PBIP-project")
print(result.summary.columns.business_total)
for finding in result.findings:
    print(finding.ref.label, finding.status.value)
```

`analyze_project()` accepts a project-folder string or `Path` and returns an
`AnalysisResult` containing project paths, cleanup findings, graph objects and
evidence, diagnostics, and summary counts. It does not print or write reports.
Internal objects are counted separately from business columns and measures.
Fatal discovery/read errors propagate to the caller; recoverable parser warnings
carry stable codes, source files, optional object references, and JSON error
line/column positions when available. Existing renderers can use
`result.context`. Results own mutable graph/finding data; they are not deeply
immutable or a JSON serialization format. Progress/cancellation hooks are not yet implemented.

## Model health

`result.health_findings` contains advisory findings separately from cleanup
classifications. Text reports include a Model health section; Excel includes a
Model health sheet. Each finding has a stable rule ID, relationship scope,
severity, confidence, evidence, recommendation, and source file/line.

The first rule, `RELATIONSHIP_BIDIRECTIONAL`, flags active relationships with
explicit `crossFilteringBehavior: bothDirections`. It recommends reviewing the
need for that setting, not automatically changing it. Inactive relationships and
unknown filter settings are skipped. High confidence describes the detected
configuration, not certainty of a performance problem. Findings do not modify
cleanup status. See [Microsoft's guidance](https://learn.microsoft.com/en-us/power-bi/guidance/relationships-bidirectional-filtering).

`RELATIONSHIP_MANY_TO_MANY` flags active relationships only when both
`fromCardinality` and `toCardinality` explicitly say `many`. Omitted or unknown
cardinalities are not inferred. Recommendations distinguish shared dimensions,
bridge designs, and legitimate higher-grain facts; the rule does not inspect
source data or prove incorrect totals. Inactive relationships are skipped.
See [Microsoft's many-to-many guidance](https://learn.microsoft.com/en-us/power-bi/guidance/relationships-many-to-many).

`MEASURE_DESCRIPTION_MISSING` is an informational documentation opportunity for
business measures with absent or blank descriptions. The parser reads adjacent
TMDL `///` description lines, including multiline descriptions. Internal auto-date
measures and uncertain alternate description syntax are skipped. The finding
does not imply an incorrect calculation or change cleanup status.

## Filtering model-health findings

```bash
.venv/bin/python run_analyzer.py /path/to/project --health-severity warning
.venv/bin/python run_analyzer.py /path/to/project --health-rule MEASURE_DESCRIPTION_MISSING --health-severity info
```

Both options are repeatable. Selections within an option are combined with OR;
rule and severity selections are combined with AND. Omitting an option includes
all values. Unknown IDs or severities are rejected. Filters affect health findings
in text/Excel exports, not cleanup classifications, diagnostics, or graph evidence.

```python
from pbi_usage_analyzer import analyze_project, filter_health_findings

result = analyze_project("/path/to/project", health_severities=["warning"])
selected = filter_health_findings(result.health_findings,
                                 rule_ids=["RELATIONSHIP_MANY_TO_MANY"])
```

API filters accept an iterable or a single string; severity enums also work.
`None` means unrestricted, while an empty iterable selects no findings. Filtering
preserves result order. To change filters without rerunning analysis, keep an
unfiltered result and use `filter_health_findings()` on it.

`result.health_filter_scope` records canonical rule/severity selections and the
health-finding counts before and after filtering. Text reports show this scope
in Model health; Excel includes it in Summary, even when zero findings are
selected. `None` selections mean all values; empty tuples mean no values.

When calling report writers directly, pass both `result.health_findings` and
`result.health_filter_scope`. Calls without scope metadata are labeled “Not
recorded.” If you filter findings again in memory, the original result's scope
still describes the original selection; do not reuse it for a different subset.

## JSON export

```bash
.venv/bin/python run_analyzer.py /path/to/project --json --health-severity warning
```

This also writes `<project>_usage_analysis_v2.json` in the project folder. Without
`--json`, the CLI continues to produce text and Excel only. Existing output files
with these report names are replaced on subsequent runs.

```python
from pbi_usage_analyzer import analyze_project, analysis_to_dict, generate_json, write_json

result = analyze_project("/path/to/project")
document = analysis_to_dict(result)  # JSON-compatible dictionary
content = generate_json(result)     # UTF-8-compatible Unicode string; no file writes
write_json("analysis.json", result)
```

JSON schema version 1 includes project paths, summary counts, model objects,
dependency evidence, cleanup findings, diagnostics, health findings, and recorded
filter scope. Cleanup entries include `status_id` (such as `LIKELY_UNUSED`) and a
display `status`. Optional values use JSON `null`; empty selections use `[]`.
The export contains local file paths and parsed expressions. Internal parser
state and arbitrary object metadata are excluded. It is an export format, not
a serialized Python object that can be loaded back into the analyzer.

The export contract is published in
[`schemas/analysis-result-v1.schema.json`](schemas/analysis-result-v1.schema.json)
using JSON Schema Draft 2020-12. Unit tests and `make validate` check exports
against it. Install development dependencies with `make setup` or
`.venv/bin/python -m pip install -r requirements-dev.txt`; ordinary analysis and
JSON export do not require the `jsonschema` package.

The schema rejects missing/unknown fields, invalid types, invalid status pairs,
and invalid locations. Rule and diagnostic IDs remain extensible. Structural
validation does not prove dependency correctness or cross-field count consistency;
regression tests check selected count invariants separately.

## Validate a saved JSON export

```bash
make validate-json EXPORT="/path/to/analysis.json"
# Direct command, useful when scripts need the exact exit status:
.venv/bin/python tools/validation/validate_json_export.py /path/to/analysis.json
```

The standalone command reads the bundled version 1 schema without opening a PBIP
project or modifying the export. Schema errors include JSON Pointer paths;
malformed JSON errors include line/column positions. Duplicate keys, nonstandard
numeric constants, and invalid UTF-8 are rejected.

Exit statuses for the direct command are `0` for a valid export, `1` for invalid
JSON/schema content (including unsupported versions), and `2` for usage, missing
files, schema-loading failures, or missing validation dependencies. GNU Make may
map a failed recipe to its own exit status. Install validation dependencies with
`make setup` or `.venv/bin/python -m pip install -r requirements-dev.txt`.
Validation checks structure and internal consistency; it does not rerun analysis
or prove the original dependency analysis correct.

Saved-export validation also checks summary counts against cleanup findings,
unique object/finding references, classification coverage, dependency endpoints,
query-dependency totals, and health filter membership/counts. Report-field sources
and known synthetic special owners are allowed outside the model-object list.
Diagnostic references may intentionally describe unresolved objects and are not
required to resolve. Filtered-out health findings cannot be reconstructed, so the
pre-filter total is checked for bounds rather than independently recounted.

## Continuous integration

[Analyzer checks](.github/workflows/ci.yml) runs on pushes, pull requests, and
manual dispatch using Ubuntu 24.04 and Python 3.12. It installs development
dependencies in `.venv`, then runs `make compile`, `make test`, and `make validate`.
Actions are pinned to commit revisions; repository permissions are read-only.
Pip download caching includes both requirements files in its cache key.

Docker/database integration remains optional. CI does not run the workstation
prerequisite check, which also checks for local tools such as VS Code.
The workflow must be committed and pushed before GitHub can run it; required
status checks in branch protection are configured separately.

## Fixture reproducibility

Run `make check-fixtures` to generate the synthetic corpus in a temporary
directory and compare file paths and bytes with `tools/validation/validation_suite`.
It checks source fixtures, expected results, and the manifest without rewriting
the corpus. CI runs it before the regression tests.

Changed, missing, and extra files are reported individually. Keep generated
analysis reports outside the corpus; extra files count as drift. To accept an
intentional generator change, review it and run `make fixtures`, which replaces
the corpus, then run `make check-fixtures` and `make validate`.

The direct command is `.venv/bin/python tools/validation/check_fixture_drift.py`.
An optional directory argument checks a different reference corpus. Exit codes
are 0 for a match, 1 for drift, and 2 for generation/read failures. Comparison is
byte-exact; it does not compare empty directories, permissions, or timestamps.

## Runtime dependency smoke test

`make check-runtime` creates a temporary virtual environment, installs only
`requirements.txt`, and verifies that `jsonschema` is absent. It tests library
analysis and JSON serialization, then CLI text/Excel/JSON exports and health
filtering on a temporary fixture copy. The environment and generated reports
are removed afterward; the repository's `.venv` and fixture corpus are unchanged.

CI runs this target after the main validation suite. It requires package-index
access (or a suitable pip cache), unlike the ordinary tests after setup. Python
user-site packages and inherited Python search paths are excluded from the worker.

## Alpha scope and known gaps

See the [format coverage matrix](docs/FORMAT_COVERAGE.md) for implemented subsets,
linked regression evidence, and known limitations. This is a supervised engineering
alpha: DAX, special model structures, and unknown report/M forms have incomplete
coverage. Unreadable report files and unparseable/undecodable TMDL add scoped
manual-review evidence, but objects defined in a failed TMDL file are absent from
results. Synthetic validation does not establish real-project accuracy.

## Next planned improvement

Resolve unqualified column references in DAX (for example a calculated column
`= [Quantity] * [Price]` or `SUMX(Sales, [Amount])`). Today only unqualified
measures resolve, so such columns can be missed and reported `Likely unused`.

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
