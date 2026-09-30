# Agent handoff — current working state

Last updated: 2026-09-30. This file is intended to let a new agent continue without
chat history. Treat source files and a fresh `git status` as authoritative if this
snapshot becomes stale. Update this handoff after material changes.

## Start here

1. Read [AGENTS.md](../AGENTS.md), this file, [architecture](architecture.md),
   [roadmap](ROADMAP.md), [development](DEVELOPMENT.md), and [Ubuntu setup](UBUNTU_SETUP.md).
2. Read [format coverage](FORMAT_COVERAGE.md) before making support claims.
3. Inspect `git status --short` and the relevant source/tests before editing.
4. Preserve the existing working tree. Substantial implemented work is uncommitted
   and many essential files are untracked. Do not reset, clean, or reconstruct the
   project from HEAD. A plain `git diff` omits untracked files.
5. Run the verification commands below when continuing implementation.

The product is a supervised engineering alpha: a deterministic Power BI PBIP/PBIR
usage and model-health analyzer. It has a graph-based core, CLI, library API,
text/Excel/JSON exports, synthetic fixtures, and advisory rules. No GUI or AI
service is implemented. Correctness and evidence-based conservatism take priority;
`Likely unused` never means safe to delete.

## Repository and publication state

- Working location: `/home/haakon/Desktop/pbi_usage_analyzer_ubuntu_agentic`.
- Origin: `https://github.com/HaakonEidemHaakstad/pbi_usage_analyzer.git` (private).
  Plain HTTPS git has no stored credentials; SSH works
  (`git@github.com:HaakonEidemHaakstad/pbi_usage_analyzer.git`). The `gh` CLI is
  installed and authenticated (keyring, git protocol SSH) as of 2026-09-30, so
  `gh run list` / `gh run view --log` can check CI.
- 2026-09-30: local and remote histories had identical trees but different commit
  IDs (no merge base; earlier connector-based publication). Local `main` was moved
  onto remote `main` (`5a4e5f9`) with `git reset --soft`, keeping all work, and the
  former local history was kept as branch `local-history-backup` (at `f1e2876`,
  not pushed). All work described here was then committed as one commit on top of
  `5a4e5f9` and pushed as a fast-forward. Check `git log -1` / `git status` for the
  current state.
- Hosted CI ("Analyzer checks", Python 3.12 / Ubuntu) passed on `75d5132`
  (run 36768770213): fixtures reproducible, 142 tests, 195 synthetic checks,
  runtime smoke test. Check `gh run list` for later commits.
- Follow AGENTS.md: do not commit or push without explicit user instructions. The
  user authorized committing/pushing on 2026-09-30 ("feel free to commit and push
  at your leisure"); treat that as covering routine completed work in this sequence.

The user's latest request was to continue work from this handoff; the previous
agent was interrupted while documenting. Its claims were re-verified on 2026-09-30
(all counts matched; runtime smoke test rerun and passing). The planned DAX
masking task, the TMDL expression-boundary fix and damaged-source handling were
then implemented. When asked to proceed, use the next-work section.

## Implemented work in the current tree

| Area | State and entry points |
| --- | --- |
| M lineage | `parsers/m_lineage.py` supports bounded projection/removal/rename/type conversion, filters/computed columns, joins and nested expansion. Nested expansion now follows filters, selection/removal/renaming and scalar type conversions. Unsupported shapes fall back; schema and join-key requirements remain protected. |
| Auto-date | Internal objects excluded from business totals and cleanup candidates. Only resolved backing columns receive internal-query protection; no blanket upstream-table protection. See `tests/test_autodate.py` and scenario 08. |
| Application API | `api.py`: `analyze_project(path, *, health_rule_ids=None, health_severities=None)`. No terminal output or report writes. Returns project paths, graph, cleanup findings, diagnostics, summaries, selected health findings and filter scope. CLI and synthetic validator share this entry point. |
| Diagnostics | `diagnostics.py` provides stable codes, severity, message, source file, optional location/object reference. Parser/context `warnings` is a derived compatibility list; append to `diagnostics`, not `warnings`. |
| Health rules | `health/engine.py` registry: `RELATIONSHIP_BIDIRECTIONAL`, `RELATIONSHIP_MANY_TO_MANY`, `MEASURE_DESCRIPTION_MISSING`. Advisory findings remain separate from cleanup. Description opportunities have `info` severity; relationship findings have `warning` severity. |
| Relationships | Structured records in `parsers/relationships.py` shared by graph and rules. Adjacent declarations no longer lose endpoint evidence. Cardinalities are explicit-only for health detection. |
| Descriptions | `ModelObject.description` is empty for absent/blank parsed descriptions, `None` when unknown/not parsed. Adjacent TMDL `///` descriptions are read for measures. Internal measures excluded from documentation rule. |
| Health selection | `health/filtering.py`: exact IDs/severities, OR within each selection and AND between selections. `None` is unrestricted; empty iterable selects none. Unknown values fail before project I/O. `HealthFilterScope` records canonical selections and before/after counts. |
| Reports | CLI writes text and Excel; `--json` adds JSON. Health scope is shown even for an empty selection. Low-level writers without scope metadata report it as not recorded. |
| JSON | `reporting/json_report.py`: `analysis_to_dict`, `generate_json`, `write_json`. Version 1 exports retain paths, expressions, object refs, evidence, diagnostics and filter scope, but exclude parser context/arbitrary metadata. `schemas/analysis-result-v1.schema.json` is the structural contract. |
| Export validation | `tools/validation/validate_json_export.py` checks saved UTF-8 JSON without loading PBIP. Rejects malformed JSON, duplicate keys and nonstandard constants. `export_consistency.py` checks totals, reference integrity, cleanup coverage and filter scope after schema validation. |
| Reproducibility | `check_fixture_drift.py` generates in a temporary directory and compares paths/bytes without rewriting the corpus. `check_runtime.py` creates a disposable venv containing only runtime requirements and tests API/CLI and exports. |
| CI | `.github/workflows/ci.yml`: Ubuntu 24.04, Python 3.12, commit-pinned actions, read-only permissions, compilation, drift check, tests, synthetic validation and runtime smoke test. |
| Special DAX | `parsers/special_dax.py` replaces file-wide marker scanning with bounded declaration/expression extraction. Details below. |
| Case study | Latest change: multi-source bad-practice package generator and build guide. Details below. |
| Real project | Previous change: AdventureWorks validation; PBIR `SourceRef.Entity`/hierarchy-level fix; M case-sensitivity fix. Details below. |
| Report safety net | Previous change: one tighter rule for columns and measures in readable PBIR files. Details below. |
| Performance | Previous change: DAX indexes, regex masker, per-file report extraction, determinism fix, `make benchmark`. Details below. |
| Report measures | Previous change: measure rule in the PBIR raw safety net (`parsers/pbir.py`). Details below. |
| Unqualified DAX | Previous change: row-context column resolution and keyword-before-bracket fix in `parsers/dax.py`. Details below. |
| Damaged sources | Previous change: scoped evidence recovery for unreadable/undecodable files. Details below. |
| TMDL expressions | Previous fix: multiline expression boundaries in `parsers/tmdl.py`. Details below. |
| DAX lexing | Previous feature: `parsers/dax_lexer.py` (`mask_dax`, `mask_dax_literals`) shared by ordinary and special DAX. Details below. |

## Latest change: bad-practice case study sources

- User request (2026-09-30): use the AdventureWorks raw data to assemble a complex
  bad-practice case with multiple source types for a Power BI case study. Power BI
  Desktop runs on a **separate Windows PC**; sources chosen: MariaDB, Excel, CSV
  folder, JSON.
- `tools/casestudy/adventureworks_mess.py RAW_DIR [--out] [--force]` writes a
  portable package (default `~/Desktop/AW_case_sources`, outside the repo; the raw
  data is course material and is not committed). Contents and traps: see
  docs/CASE_STUDY_ADVENTUREWORKS.md. MariaDB runs on the Windows PC from the SQL
  scripts; nothing on this host is exposed to the network (Docker is not
  installed here, and the existing compose file binds to 127.0.0.1).
- Real data defects found and used: the customer CSV is ISO-8859-1 and ends with
  junk/footer rows (`30---`, `Export date ...`, `Source ...`); the typed `customers`
  table keeps only integer keys (then unique), `stg_customers_raw` keeps the junk.
  `Sales Data/` in the raw folder duplicates the yearly files byte for byte.
- SQL is verified by executing the generator's SQLite dialect (identical data
  statements; only DDL/date functions differ) in `tests/test_casestudy_sources.py`,
  which uses a tiny synthetic raw folder so CI needs no course data. Not verified
  against a real MariaDB server.
- The guide's answer key is a prediction. When the user returns the PBIP, derive
  ground truth independently (as for AdventureWorks), record expectations, and
  investigate differences. Its "Not yet" items are the health-rule backlog.

## Previous change: first real-project validation (AdventureWorks)

- Project: `~/Desktop/AW` (`AdventureWorks Report.pbip`, user's course material;
  read-only, not in the repo; its M contains the author's local Windows paths).
  9 tables, 72 columns, 24 measures, 1 page, 6 visuals; current PBIR
  visualContainer format; auto-date disabled; no RLS/calculation groups/field
  parameters/sort-by. Analyzed through the API only (the CLI writes reports next to
  the project).
- Ground truth: an independent subagent derived statuses from raw files without
  seeing analyzer code or output. Main agent verified disagreements.
- Bug 1 (critical): current PBIR fields use `"SourceRef": {"Entity": "T"}`;
  `_table_from_expression` only handled `SourceRef.Source` aliases, so no visual
  field resolved (0 of 15 used measures Used; only the tightened raw net kept them
  at manual review). Also `Hierarchy` names are under key `"Hierarchy"` and
  `HierarchyLevel` nests its hierarchy. Fixed in `parsers/pbir.py`; added
  `PropertyVariationSource` -> business column (PBIR shape, no real sample yet).
  Synthetic fixtures had only used the query-command alias form.
- Bug 2: `_find_query_refs` matched simple identifiers with `re.I`, so
  `{"ReturnDate", type date}` created a dependency on query `Date` (forbidden by
  AGENTS.md). Now case-sensitive and not inside dotted/`#` identifiers.
- Result: 79/96 exact; all 41 Used agree; no false `Likely unused`; 17 by-design
  manual reviews (unused DAX owners; unused hierarchy levels). Expectations in
  `tests/integration/adventureworks_expected.json`; run with
  `PBI_AW_PROJECT=~/Desktop/AW make test`.
- Scenarios 31 (`31_pbir_entity_refs`) and 32 (`32_m_case_sensitive_refs`);
  tests `tests/test_pbir_entity_refs.py`, `tests/test_powerquery.py`. No evidence or
  status changes in scenarios 01–30 or the large model.
- Observed, not acted on: `Total Revenue (CC)` references nonexistent
  `'Sales data'[Revenue]` (candidate health rule: DAX reference to a missing
  object); `Total Customers` uses `'Sales Data'` (case differs; resolves correctly).
  Design question: objects referenced only by Likely-unused owners are manual review;
  a clearer sub-reason in reports could help users.

## Previous change: tighter report safety net for columns

- Old column rule (readable files): column-name substring anywhere in the file's
  values and keys, plus table-name substring or a unique column name. Observed
  noise: key `"name"` protected `Customers[Name]` (scenarios 14–17); `t1`/`c1`
  inside `t10`/`c10` produced 145 hits in the large model; title `Total` protected
  `Budget[Total]` (scenario 29).
- New shared rule `_readable_hit_files` (columns and measures) over `ReportText`
  (blob of values+keys, whole values, DAX-style pairs, unqualified `[Field]` names):
  `_dotted_occurs` `Table.Field` with identifier boundaries, `'Table'[Field]`, or the
  exact name as a whole value / `[Field]` when the table name is a whole value in the
  same file. For measures this replaced "unique name AND table present" with "table
  present". Unreadable files keep the substring rule.
- Bug caught during implementation: `before in "_."` is True for an empty string, so
  a dotted match at the start of the text was rejected; now covered by a unit test.
- Fixture edit: scenario 29's `Visual3` no longer has `"entity": "Sales"`; with it,
  the new rule would give `Sales[Total]` manual review (title + table present). The
  title-plus-table case is recorded explicitly as `Sales[Year]` in scenario 30.
- Comparison with the previous commit: status changes only `Budget[Total]` (29)
  Needs manual review -> Likely unused. Raw hits removed in 14–17 (statuses held by M
  lineage) and 145 in the large model (statuses held by query-level M evidence).
  New scenario `30_report_column_safety_net`.
- Risk accepted: a real report that encodes a column only as a substring (e.g.
  `"Sales Amount"` without a dot or table value) is no longer protected by the net.
  Validate on real projects.

## Previous change: performance and determinism

- Profiled a generated 3,280-object model (`tools/validation/large_model.py`):
  5.4 s before, about 0.9–1.1 s after. Hotspots fixed:
  - `pbir._measure_hit_files` compiled/ran a regex per measure per file. Now
    `_qualified_field_refs` extracts `Table[Field]` pairs once per file; lookups are
    set membership. Theoretical difference: a `Table[Field]` nested inside a longer
    quoted table name is no longer found (the old per-measure regex could).
  - `dax_dependencies` rebuilt the table set and scanned all measures/columns per
    reference. `DaxIndex.build` (in `parsers/dax.py`) runs once in `build_graph`
    and is passed via `index=`; callers without it still work (built on demand).
  - `mask_dax` character loop replaced by one regex tokenizer. `tests/test_dax_lexical.py`
    keeps the old loop as `_reference_mask` and compares 10,000 random inputs.
- Found a pre-existing determinism bug while comparing: `TmdlModel.hierarchies`
  used `set` values, so hierarchy evidence order (and JSON/Excel row order) varied
  with `PYTHONHASHSEED`. Values are now declaration-ordered tuples.
  `tests/test_determinism.py` compares full exports under seeds 1 and 3 (failed before).
- Equivalence: with a fixed seed, evidence (order and content), findings,
  diagnostics and raw-hit rows are identical to the previous commit for all 29
  scenarios and the large model.
- `make benchmark` (also an informational CI step); `tests/test_large_model.py`
  checks samples on a small generated model; `PBI_PERF=1` enables a 3 s bound.

## Previous change: measure-aware report safety net

- Readable PBIR files previously raw-scanned only columns, so a measure referenced
  through an unrecognized structure (custom bindings, expression strings) was
  `Likely unused`.
- `parse_report` now tracks `accounted_measures` (structured or fallback matches)
  and per-file whole-string sets. Other non-internal measures get
  `RAW_REPORT_REFERENCE` (manual review) via `_measure_hit_files` when a file has a
  whole string `table.measure`, DAX-style `'Table'[Measure]`/`Table[Measure]` text
  (`_qualified_measure_pattern`, escaping `''`/`]]`, word boundary before plain
  names), or the exact measure name as a whole string when the name is unique among
  measures+columns and the file has the table name as a whole string.
- Tests: `tests/test_report_measure_safety_net.py` (failed before the change),
  scenario `29_report_measure_safety_net`.
- Comparison: no changes in 01–28. Scenario 29: `Sales[Revenue]`,
  `Sales[Gross Margin]`, `Sales[Bob's Helper]` Likely unused -> Needs manual review.
  Title `Total` (name not unique), substring `Revenue Growth rate`, and a bare name
  in a file without its table do not protect measures.
- Observed, not changed: the column rule is substring-based, so a title `Total`
  gives `Budget[Total]` manual review (recorded in scenario 29's expectations).
  Tightening it would change existing behavior; consider it separately.

## Previous change: unqualified DAX references

- Bug found and fixed: `QUALIFIED_DAX_REF` allows spaces/hyphens in unquoted table
  names and `\s*` spans newlines, so `VAR … RETURN [Margin]`, `Total - [Discount]`,
  `NOT [Margin]` were read as qualified references to tables `RETURN`/`Total -`/`NOT`
  and dropped; `FILTER(Sales, NOT Sales[Flag])` lost `Sales[Flag]`.
  `_qualified_table` now takes the longest trailing word sequence that names a known
  table; if none, the bracket is resolved as unqualified. Quoted `'Old'[X]` stays
  qualified (stale refs are not reinterpreted).
- `dax_dependencies(..., row_table=None)`: unqualified names resolve to measures
  first (unchanged), then to a `row_table` column (calculated columns pass their own
  table; special-DAX passes the RLS `tablePermission` table) as `DAX_DEPENDENCY`.
  Otherwise same-named non-internal columns get new
  `EvidenceType.DAX_UNQUALIFIED_COLUMN_REFERENCE` (classifier `MANUAL_REVIEW`, not
  propagated), narrowed to tables named in the masked expression.
- Special-DAX converts only `DAX_DEPENDENCY` edges into RLS/calculation-group/field
  parameter evidence, so heuristic matches never become Used roots.
- Tests: `tests/test_dax_unqualified.py` (failed against the old code), scenario
  `28_dax_unqualified_columns`.
- Comparison: no changes in 01–27. Scenario 28: `Sales[Region]` (RLS),
  `Sales[Quantity]`/`Sales[Price]` (calculated column) and `Sales[Cost Total]`/
  `Sales[Cost]` (`RETURN` fix) became Used; `Sales[Amount]` (`SUMX(Sales, [Amount])`)
  Likely unused -> Needs manual review. `Budget[Amount]` stays Likely unused.
- Known limits: a same-named measure suppresses column evidence in measures (DAX
  precedence is not modeled); calculation items with unqualified columns give no
  evidence; `dax_dependencies` scans the column/measure indexes per call
  (O(objects x expressions)); precompute indexes if large models are slow.

## Previous change: damaged source files

Problems found (2026-09-30):
- Invalid UTF-8 in any TMDL file crashed analysis: `TMDL_PARSE_FAILED` caught it in
  the table parser, but Power Query, special-DAX and relationship passes re-read with
  strict UTF-8.
- An unreadable `visual.json` was skipped by the raw safety net too, so fields used
  only there were `Likely unused`.
- BOM-prefixed JSON failed to load; BOM-prefixed TMDL hid its `table` header.

Changes:
- `util.read_source_text` (BOM-tolerant, replacement decoding) used by all TMDL
  readers; `load_json` uses `utf-8-sig`. `parse_model` emits `TMDL_DECODE_REPLACED`
  for any definition `*.tmdl` with invalid bytes and records `failed_files`.
- New `EvidenceType.INCOMPLETE_SOURCE` (in classifier `MANUAL_REVIEW`): DAX
  references raw-scanned from failed TMDL table files, and objects whose names
  contain U+FFFD. `build_graph` adds them; scope is per file/object, never model-wide.
- PBIR: unreadable files' raw text joins the safety net; for them it also checks
  measures. `raw_hits` rows now use keys `Type`, `Table`, `Field`, `Source files`
  (was `Column`), visible in the Excel "Raw report safety net" sheet.
- Tests: `tests/test_incomplete_sources.py` (parse failure via mock), scenario
  `27_incomplete_sources` (truncated JSON, BOM JSON/TMDL, Latin-1 TMDL).
- Comparison: no status changes in scenarios 01–26.
- Not changed: `M_LINEAGE_INCOMPLETE` already keeps query-level manual-review
  evidence; `DAX_UNTERMINATED_LITERAL` keeps evidence; auto-date diagnostics rely on
  relationship endpoints. Objects defined in a failed TMDL file remain absent.

## Previous change: TMDL multiline expression boundaries

- Bug: `extract_expression` ended a non-fenced multiline expression at any line
  containing `": "` or ending with `:` (the `base_indent + 8` guard is ineffective
  for tab-indented files because a tab counts as one character). `VAR label =
  "Total: "` or `// note: legacy` emptied the expression, so every referenced column
  could become `Likely unused`.
- Fix: a line ends the expression only if its DAX-masked text starts with
  `PROPERTY_LINE` (`name:`) or a `PROPERTY_PREFIXES` keyword. Added
  `extendedProperty ` and `formatStringDefinition` to the prefixes. Fenced and
  inline expressions are unchanged; inline + continuation lines are still not joined
  (TMDL validity of that form unverified).
- Special-DAX extraction already masks the file and uses an anchored property
  regex, so it did not have this bug.
- Tests: `tests/test_tmdl_expressions.py` (failed before the fix) and scenario
  `26_tmdl_expression_boundaries` (tab-indented).
- Comparison (old extractor monkeypatched in): extracted expressions differ only in
  scenario 26; statuses change only there — `Sales[Amount]`, `Sales[Cost]`,
  `Sales[Quantity]`, `Sales[Line Total]` Likely unused -> Used.
- Caution for comparisons: `git stash` of an individual file reverts it to HEAD and
  drops earlier uncommitted work in that file; monkeypatch old functions instead.

## Previous change: ordinary DAX string/comment masking

- `parsers/dax_lexer.py` holds the masker formerly in `special_dax.py` (moved to
  avoid a `dax` <-> `special_dax` import cycle; `special_dax` behavior unchanged).
  `mask_dax` also reports unterminated strings/block comments.
- `dax_dependencies` extracts references from masked text. An unterminated tail is
  left **unmasked** for ordinary dependencies (conservative: identical to previous
  behavior) and `build_graph` emits `DAX_UNTERMINATED_LITERAL`.
- Fixed a pre-existing identifier bug found by the new tests: quoted table names
  never unescaped `''` (so `'Bob''s'[X]` resolved nothing), and `]]` in bracketed
  names was unsupported. Both now resolve.
- Tests: `tests/test_dax_lexical.py` (confirmed failing against the old `dax.py`).
  Scenario 25 `25_dax_lexical_scope` has explicit expected statuses.
- Old/new comparison: no classification changes in scenarios 01–24. In scenario 25
  only `Sales[Legacy]`, `Sales[Old Margin]`, `Sales[Commented Only]` changed
  Used -> Likely unused; each is referenced solely inside a DAX comment or string.

## Earlier change: special DAX evidence scope

Previously, finding `NAMEOF(`, a role marker or a calculation-group marker anywhere
in a TMDL file caused all recognized DAX references in that file to receive special
evidence. Comments, strings, annotations and unrelated expressions could therefore
promote unused objects to Used.

The new parser:

- Masks DAX strings and line/block comments while preserving quoted identifiers
  and line breaks (`mask_dax_literals`).
- Descends recognized table, role, calculation-group and calculated-partition
  containers; ignores unrelated declarations and annotation contents.
- Extracts table-permission expressions for RLS and calculation-item expressions,
  including their format-string definitions, for calculation-group evidence.
- Promotes only actual NAMEOF arguments to field-parameter evidence, including
  calls with whitespace before the opening parenthesis. M partitions are excluded.
- Handles inline, continued, multiline and fenced expressions within its bounded
  grammar. Evidence reasons include declaration line numbers.
- Retains synthetic `Special:<filename>` owners. Saved-export consistency checks
  allow these external owners for the corresponding evidence types.

Positive scenarios 21–23 and `tests/test_special_dax.py` cover field parameters,
RLS, calculation items, provenance and activation limits. Scenario 24 guards
negative scope cases. The old/new classification comparison showed no changes
in scenarios 01–23. In scenario 24 only:

| Object | Old file-wide scan | New extraction |
| --- | --- | --- |
| Sales[Amount] | Used | Needs manual review |
| Sales[Revenue] | Used | Needs manual review |
| Sales[Unrelated] | Used | Likely unused |

These changes follow removal of false special-use evidence. Calculation-item
activation is still not proven; credible references remain manual review unless
other evidence proves usage. This is not full TMDL/DAX parsing.

## Next planned implementation

Waiting on the user: build the case study in Power BI Desktop (Windows PC) and
return the PBIP. Then score it (independent ground truth vs analyzer; record
expectations like `tests/integration/adventureworks_expected.json`). Engineering
candidates meanwhile, from the answer key's "Not yet" rows: health rules for
hard-coded paths/URLs in M, loaded staging/per-year queries, hard-coded annual
appends, text-key relationships, duplicate measures, `Folder.Files` without a
filter; a rule for DAX references to missing objects (AdventureWorks). GUI: none
exists; thin desktop front end over `analyze_project()` after more validation.

## Verification and environment

Primary host: Ubuntu, Python 3.12, existing `.venv`. Runtime requirements:
`requirements.txt` (pandas/openpyxl). Development requirements:
`requirements-dev.txt` (includes runtime requirements plus jsonschema).
Both bootstrap scripts install development requirements. Ordinary analysis/export
must not require jsonschema.

```bash
make check
make compile
make check-fixtures
make test
make validate
# Slower/network-dependent, isolated environment:
make check-runtime
# Saved export checks:
make validate-json EXPORT="/path/to/analysis.json"
```

Latest completed implementation checks:

- 175 unit/regression tests passed, 2 opt-in tests skipped (timing; AdventureWorks,
  which passes with `PBI_AW_PROJECT` set) (2026-09-30, after the case-study tools).
- 251 synthetic checks passed across 32 scenarios, including JSON schema and
  export consistency validation.
- Fixture reproducibility, compilation, and `git diff --check` passed.
- Runtime-only smoke test passed on 2026-09-30 after damaged-source handling;
  hosted CI reruns it on every push.
- Hosted GitHub Actions run passed on `75d5132` (2026-09-30).
- `make check` reports missing Docker. Docker is optional; do not install host
  packages or require it for ordinary tests. No real PBIP accuracy benchmark or
  Power BI refresh verification was completed in this development sequence.

Generate fixtures without deleting unrelated files during iteration:

```bash
.venv/bin/python tools/validation/generate_validation_suite.py tools/validation/validation_suite
```

`make fixtures` uses `--clean` and replaces the corpus. Prefer the non-clean command
unless replacement is intentional. `make check-fixtures` is non-mutating and also
flags stray generated reports. Synthetic expected statuses live in each scenario's
`expected.json`; optional `expected_health` entries specify exact health findings.

## Known limits and cautions

The [coverage matrix](FORMAT_COVERAGE.md) is the detailed reference. Key limits:

- Ordinary DAX is regex matching over string/comment-masked text, not a grammar.
- Special parsing is bounded; broader calculation-group selection expressions,
  full role/item semantics and general dynamic references remain gaps.
- PBIR supports selected recursive node shapes. Raw fallback is column-only and
  substring-based. File-level alias mapping is not full semantic-query scoping.
- TMDL multi-table files/partial declarations are not reliably supported.
- Damaged sources add only scoped manual-review evidence. Objects defined in a
  failed TMDL table file are absent from results; references containing undecodable
  bytes cannot be resolved. Treat results with diagnostics as incomplete.
- Unqualified DAX columns outside a certain row context are manual review only.
- M fallback is heuristic; precise lineage covers a bounded subset. Do not claim
  every unsupported expression necessarily produces protective evidence.
- Health confidence reflects detection, not proof of defects. Rules do not change
  cleanup statuses. Filtered pre-selection counts cannot be independently rebuilt
  from omitted findings in a saved export.
- Existing API results contain mutable graph/findings. If filtering again in memory,
  original recorded filter scope must not be reused as though it described the new subset.
- JSON exports include local paths and expressions. They are not anonymized and
  are not importable analysis sessions.

## Updating this handoff

After each material milestone, refresh the next step, last verified results, changed
behavior, and publication state. Avoid treating accumulated uncommitted work as
new-agent scratch files. Keep authorization boundaries in AGENTS.md intact.
