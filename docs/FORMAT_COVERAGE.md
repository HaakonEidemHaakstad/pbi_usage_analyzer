# Format coverage and alpha scope

This is an engineering alpha for supervised, static analysis of local PBIP/PBIR
projects. This document describes implemented behavior, not full conformance to
Power BI format specifications. “Tested” means the linked fixtures or tests cover
the stated shape; it does not certify every construct in that format.

The core does not execute DAX or M, refresh a model, query production sources, or
verify results in Power BI. `Likely unused` is an investigation candidate, not
permission to delete. Unsupported syntax is not universally detected: a missing
warning does not establish complete coverage.

## Input discovery and semantic model

| Area | Implemented boundary | Evidence and remaining gaps |
| --- | --- | --- |
| Project discovery | Accepts a folder; selects one matching `.Report`/`.SemanticModel` pair, or a sole pair with differing names. Ambiguity is fatal. | [Discovery implementation](../pbi_usage_analyzer/discovery.py), [API tests](../tests/test_api.py). Does not resolve model/report associations from PBIP/PBIR manifests or accept a PBIP file directly. |
| TMDL objects | Reads table files under `definition/tables/*.tmdl`; extracts columns, measures, hierarchies and selected properties using line/indentation parsing. | [Parser](../pbi_usage_analyzer/parsers/tmdl.py). Not a full TMDL grammar. Multi-table files and partial declarations across files are not reliably supported. |
| Column metadata | Extracts source-column names, data types, hidden flags, sort metadata and calculated expressions in recognized blocks. | [Auto-date and source mapping tests](../tests/test_autodate.py). Does not provide exhaustive annotation/property interpretation. |
| Measure descriptions | Adjacent same-indentation `///` lines, including multiline and blank descriptions. Unknown `description:` forms suppress the missing-description rule. | [Description tests](../tests/test_measure_health.py), [scenario 20](../tools/validation/validation_suite/20_measure_descriptions). No description-quality assessment. Measure hidden metadata is not currently parsed. |
| Identifier matching | Trimming, TMDL quote removal/unescaping and Unicode casefolding for model matching. | [Normalization tests](../tests/test_normalization.py). Original display names are retained. DAX token recognition remains narrower than normalization. |
| Relationships | Reads direct endpoint, filter-direction, active-state and explicit cardinality properties in `definition/relationships.tmdl`; headers delimit adjacent records. Both resolved endpoints receive dependency evidence. | [Scenario 03](../tools/validation/validation_suite/03_relationship_only), [health tests](../tests/test_health.py). Does not validate uniqueness, execute filtering, or infer cardinalities from data. Alternate relationship storage is unsupported. |
| Hierarchies and sort-by | Resolved hierarchy members and sort-by columns become graph edges; propagation depends on usage evidence. | [Scenario 04](../tools/validation/validation_suite/04_sort_by), [scenario 05](../tools/validation/validation_suite/05_hierarchy). Not all report hierarchy-level shapes resolve. |
| Internal auto-date objects | Separates `LocalDateTable_*` and `DateTableTemplate_*`; excludes internal objects from business totals and cleanup candidates. Relationships and bounded M projection can identify backing columns. | [Scenario 08](../tools/validation/validation_suite/08_autodate_scope_guard), [auto-date tests](../tests/test_autodate.py). Unresolved internal M references warn without protecting an entire upstream table. This is not general calendar-expression interpretation. |

## Report and DAX coverage

| Area | Implemented boundary | Evidence and remaining gaps |
| --- | --- | --- |
| Report files | Inspects `definition/report.json`, `definition/pages/*/page.json`, and `definition/pages/*/visuals/*/visual.json`. | [PBIR parser](../pbi_usage_analyzer/parsers/pbir.py). Legacy PBIX/Layout and service-hosted models are not inputs. Missing report definitions do not automatically stop analysis. |
| Structured report references | Recursively recognizes `Column`, `Measure`, `Hierarchy`, and some `HierarchyLevel` nodes using `Entity`/`SourceRef` and `From` mappings. Nested column nodes can cover implicit aggregation. | [Scenario 01](../tools/validation/validation_suite/01_direct_visual). File traversal does not establish complete support for every filter, tooltip, drillthrough, formatting, projection or custom-visual structure. Alias mappings are collected per file, not resolved by a full semantic-query scope model. |
| Stale references and fallback | Records unresolved references and may match an otherwise unique field name across tables. | [PBIR parser](../pbi_usage_analyzer/parsers/pbir.py). Fallback matching is heuristic; inspect evidence before acting. Localized auto-date hierarchy handling uses a limited identifier list. |
| Raw report safety net | For fields not matched structurally, readable JSON counts only qualified forms (`Table.Field` with word boundaries, `'Table'[Field]`/`Table[Field]`) or the exact name as a whole string value or unqualified `[Field]` in a file whose string values include the table name; emits manual-review evidence. | [Scenario 09](../tools/validation/validation_suite/09_raw_report_safety_net), [scenario 29](../tools/validation/validation_suite/29_report_measure_safety_net), [scenario 30](../tools/validation/validation_suite/30_report_column_safety_net), [tests](../tests/test_report_measure_safety_net.py). Substrings, JSON keys and names without their table do not count, so references encoded differently in unknown structures can be missed. A title equal to a field name next to its table name still counts. Unreadable files (`PBIR_READ_FAILED`) use a looser substring rule for columns and measures ([scenario 27](../tools/validation/validation_suite/27_incomplete_sources)); names written with JSON escapes are not matched there. |
| DAX references | Regex recognition of qualified fields, local/uniquely named unqualified measures, and unqualified columns in a certain row context (calculated column's table, RLS permission table) over text with strings and comments masked; `''`/`]]` identifier escapes are unescaped; graph propagation is transitive. | [Scenario 02](../tools/validation/validation_suite/02_dax_transitive), [scenario 25](../tools/validation/validation_suite/25_dax_lexical_scope), [graph tests](../tests/test_graph.py), [lexical tests](../tests/test_dax_lexical.py), [scenario 28](../tools/validation/validation_suite/28_dax_unqualified_columns), [unqualified tests](../tests/test_dax_unqualified.py). No DAX grammar, variable binding, or runtime evaluation. Other unqualified column names (iterators, `FILTER`, virtual `ADDCOLUMNS` columns) give `DAX_UNQUALIFIED_COLUMN_REFERENCE` manual-review evidence, narrowed to tables named in the expression; a same-named measure takes precedence and suppresses it. Words before `[` (`RETURN`, `NOT`, variables) are a table only when they end in a known table name. Unterminated strings/block comments are kept unmasked with a `DAX_UNTERMINATED_LITERAL` diagnostic. Multiline TMDL expressions end at the first property-shaped line (`name:` or a known child keyword) after string/comment masking ([scenario 26](../tools/validation/validation_suite/26_tmdl_expression_boundaries), [boundary tests](../tests/test_tmdl_expressions.py)); an inline expression is not joined with continuation lines. |
| Field parameters, RLS, calculation groups | Extracts table-permission, calculation-item/format-string expressions, and actual NAMEOF arguments from recognized declarations; uses synthetic evidence owners. | [Graph construction](../pbi_usage_analyzer/analysis/build_graph.py). Bounded indentation/declaration parsing with comment/string masking, not complete parsing of roles/items or their execution semantics. Dedicated bounded examples now exist: [field parameters](../tools/validation/validation_suite/21_field_parameter), [RLS](../tools/validation/validation_suite/22_rls), and [calculation items](../tools/validation/validation_suite/23_calculation_item), with [evidence tests](../tests/test_special_dax.py). [Negative scope regression](../tools/validation/validation_suite/24_special_dax_scope) checks comments, strings, annotations and unrelated references. Full feature-family coverage remains a gap. |

## Power Query / M coverage

Only actual M partition expressions enter query dependency inference. Bounded
column lineage is accepted only when every relevant partition expression is
supported; otherwise recognized query references retain conservative fallback.
That fallback depends on finding a credible query reference—it does not prove
complete coverage of unknown expressions.

| Shape | Supported subset | Regression evidence |
| --- | --- | --- |
| Query references and append | Local `let` bindings, aliases, quoted identifiers and bounded `Table.Combine`. Query dependencies survive empty column demand. | [Scenario 06](../tools/validation/validation_suite/06_powerquery_append), [scenario 07](../tools/validation/validation_suite/07_m_false_positive_guards), [M tests](../tests/test_m_lineage.py). |
| Selection/removal | Literal column-name lists; supported `MissingField.Ignore`; default schema requirements retained. | [Scenario 10](../tools/validation/validation_suite/10_m_column_lineage), [scenario 11 fallback](../tools/validation/validation_suite/11_m_lineage_fallback). |
| Rename/type conversion | Bounded literal pairs, supported scalar types/type constants, literal culture for type conversion. | [Scenario 12](../tools/validation/validation_suite/12_m_rename_types). Overlapping rename pairs within one call, custom types and unsupported missing-field options fall back. |
| Filters/computed columns | Bounded `each` expressions with literal field reads, arithmetic/comparison/logical operators, conditionals and allowed scalar calls. | [Scenario 13](../tools/validation/validation_suite/13_m_rows_and_computed), [scenario 15](../tools/validation/validation_suite/15_m_scalar_filtered_join), [scalar allowlist](../pbi_usage_analyzer/parsers/m_scalar_functions.py). Unknown functions, dynamic lookup, comparers and unsupported argument forms fall back. |
| Joins and expansion | Literal matching key lists, default/inner/left/right/full outer joins, nested expansion with literal fields and aliases. Both keys remain requirements. | [Scenario 14](../tools/validation/validation_suite/14_m_join_expansion). Flat joins conservatively apply output-name demand to both sides. Unexpanded nested values can retain all right-side columns. |
| Steps before nested expansion | Aliases, `let`, supported filters, selection/removal/rename and scalar type conversions; tracks nested identity. | [Scenario 16](../tools/validation/validation_suite/16_m_nested_schema), [scenario 17](../tools/validation/validation_suite/17_m_nested_types). Ambiguous identity, removed nested columns or conversion of the nested column fall back. |

Not currently proven: general `Table.Group`, `Table.Sort`, arbitrary record/list
transformations, dynamic column/key expressions, custom functions, semi/anti joins,
join algorithms/comparers, or general connector/navigation expressions. Bounded
M parsing has depth/work limits and does not evaluate data or query folding.
The fallback scanner is a separate heuristic, not a complete M parser; the
string/comment/local-step regressions cover specific cases rather than every
possible lexical form. Ordinary M dependency evidence remains `Needs manual
review`, even when its column scope is narrowed.

## Health findings and output contracts

| Capability | Current scope | Evidence |
| --- | --- | --- |
| Bidirectional relationship advisory | Explicit `bothDirections`, active/default-active and parsed endpoints. Does not establish a performance defect. | [Scenario 18](../tools/validation/validation_suite/18_relationship_health). |
| Many-to-many advisory | Both cardinalities explicitly `many`, active/default-active and parsed endpoints. Omitted cardinalities are not inferred. | [Scenario 19](../tools/validation/validation_suite/19_many_to_many_health). |
| Measure documentation opportunity | Informational finding for absent/blank parsed descriptions on non-internal measures. | [Scenario 20](../tools/validation/validation_suite/20_measure_descriptions). |
| Library API | `analyze_project()` performs no report writes/terminal output; returns mutable underlying graph/finding state in a frozen result wrapper. | [API tests](../tests/test_api.py). No cancellation/progress, GUI, AI interpretation, or source editing. |
| Text/Excel/JSON | Report writers consume analysis results; health filters record selection/counts. JSON export has a version 1 schema. | [Filter tests](../tests/test_health_filters.py), [JSON tests](../tests/test_json_report.py), [schema](../schemas/analysis-result-v1.schema.json). No JSON import into an analysis session. |
| Export validation | Structural and internal consistency checks; permits documented external evidence owners. | [Schema tests](../tests/test_json_schema.py), [consistency tests](../tests/test_export_consistency.py). Cannot prove the underlying project was analyzed correctly or reconstruct omitted findings. |

## Evidence needed before broader release claims

The synthetic corpus and unit tests establish bounded regression coverage.
Fixture drift and runtime-only smoke checks improve reproducibility. They do not
substitute for a varied real-world corpus reviewed in Power BI. The current
validation work has not established representative real-project accuracy or
large-model performance. Hosted CI runs the same checks on Ubuntu; a passing run
shows the synthetic suite is reproducible, not that real-project results are accurate.

Basic RLS, calculation-item and field-parameter fixtures now check positive
references and evidence provenance. Special-expression negative cases now cover comments, strings and unrelated
declarations. Prioritize manual verification of nested query
aliases and unsupported report structures. Damaged sources produce scoped
`INCOMPLETE_SOURCE`/raw manual-review evidence ([scenario 27](../tools/validation/validation_suite/27_incomplete_sources),
[tests](../tests/test_incomplete_sources.py)), not a model-wide downgrade. Objects
defined in a failed TMDL table file do not appear in results, and references whose
text contains undecodable bytes cannot be resolved. Treat results with diagnostics
as incomplete.

Before expanding alpha claims, record expected statuses for representative real
projects, investigate every unexplained classification change, and validate
cleanup candidates against model refresh and report behavior. Other reports
sharing a semantic model remain outside the selected project's report evidence.
