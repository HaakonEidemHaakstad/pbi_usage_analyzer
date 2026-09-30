POWER BI ANALYZER - SYNTHETIC VALIDATION TOOLS
================================================

PURPOSE

These scripts generate small synthetic PBIP/PBIR/TMDL projects with known
"ground truth", then run the analyzer against them.

This is more useful than random dummy rows alone because the analyzer is a
static dependency analyzer. The important test data is therefore model and
report structure: PBIR references, DAX, relationships, hierarchies, sort-by
metadata and Power Query/M dependencies.


FILES

generate_validation_suite.py
    Creates a validation_suite folder containing several independent projects.

validate_analyzer.py
    Runs the analyzer programmatically against every scenario and compares
    classifications with expected.json.


USAGE

1. Generate fixtures:

    python .\generate_validation_suite.py ".\validation_suite" --clean

2. Validate an analyzer checkout:

    python .\validate_analyzer.py "C:\path\to\pbi_usage_analyzer_v2" ".\validation_suite"


SCENARIOS

01_direct_visual
    Direct PBIR column use.

02_dax_transitive
    Visual -> Measure A -> Measure B -> source column.

03_relationship_only
    Relationship keys are protected even without direct report use.

04_sort_by
    A sort-by key is required by a used display column.

05_hierarchy
    A used hierarchy protects its member columns.

06_powerquery_append
    Query-level M dependency using Table.Combine and #"Archive".

07_m_false_positive_guards
    Query names in strings, comments and local let bindings must not create
    dependencies.

08_autodate_scope_guard
    Deliberately targets the current auto-date over-protection problem.
    Only the relevant date field should eventually be protected; unrelated
    source-table columns should remain eligible for analysis.

09_raw_report_safety_net
    An unresolved but credible raw PBIR occurrence should produce
    Needs manual review.


IMPORTANT

Scenario 08 is intentionally expected to fail with the current V2 analyzer.
That is useful: the validation suite is meant to encode desired behavior,
not merely reproduce current implementation behavior.

As bugs are fixed, keep the fixture and expected result. This turns every
real-world bug into a permanent regression test.
