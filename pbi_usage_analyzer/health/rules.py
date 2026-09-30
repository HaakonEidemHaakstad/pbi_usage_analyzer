from collections.abc import Iterable

from ..model import ModelObject, ObjectType
from ..parsers.dax import DaxIndex, unresolved_references
from ..util import norm_key
from ..util import is_internal_table
from ..parsers.relationships import Relationship
from .model import HealthFinding, HealthSeverity


def bidirectional_relationships(relationships: list[Relationship]) -> list[HealthFinding]:
    findings = []
    for relationship in relationships:
        if relationship.cross_filtering_behavior != "bothDirections":
            continue
        if relationship.is_active != "true":
            continue
        if not relationship.name or not relationship.from_column or not relationship.to_column:
            continue
        endpoints = tuple(f"{table}[{column}]" for table, column in
                          (relationship.from_column, relationship.to_column))
        findings.append(HealthFinding(
            rule_id="RELATIONSHIP_BIDIRECTIONAL", category="relationships",
            severity=HealthSeverity.WARNING, confidence="high", scope=relationship.name,
            title="Review bidirectional relationship filtering",
            explanation="This active relationship explicitly filters in both directions. "
                        "This can increase query cost and make filter behavior harder to understand; "
                        "the setting alone does not establish a defect or performance problem.",
            evidence=("crossFilteringBehavior: bothDirections", "isActive: true (explicit or default)", *endpoints),
            recommendation="Confirm why both directions are required. Where single-direction "
                           "filtering meets the requirements, test that change in a copy of the model "
                           "and validate measures, slicers and security behavior. Retain bidirectional "
                           "filtering when the relationship design requires it, including appropriate "
                           "one-to-one or bridge designs.",
            source_file=relationship.source_file, line=relationship.line,
        ))
    return findings


def many_to_many_relationships(relationships: list[Relationship]) -> list[HealthFinding]:
    findings = []
    for relationship in relationships:
        if relationship.from_cardinality != "many" or relationship.to_cardinality != "many":
            continue
        if relationship.is_active != "true":
            continue
        if not relationship.name or not relationship.from_column or not relationship.to_column:
            continue
        endpoints = tuple(f"{table}[{column}]" for table, column in
                          (relationship.from_column, relationship.to_column))
        findings.append(HealthFinding(
            rule_id="RELATIONSHIP_MANY_TO_MANY", category="relationships",
            severity=HealthSeverity.WARNING, confidence="high", scope=relationship.name,
            title="Review many-to-many relationship design",
            explanation="This active relationship explicitly declares many cardinality at both "
                        "ends. Review its intended grain and filter behavior. Metadata alone "
                        "does not establish duplicate keys, incorrect totals, or a performance problem.",
            evidence=("fromCardinality: many", "toCardinality: many",
                      "isActive: true (explicit or default)", *endpoints),
            recommendation="Confirm the grain and intended filtering of both tables. For fact-to-fact "
                           "relationships, consider shared dimensions; for many-to-many dimension "
                           "associations, consider a bridge with unique entity keys. Higher-grain fact "
                           "designs may legitimately use many-to-many cardinality. Test totals, "
                           "unmatched keys, slicers and security in a copy before changing the model; "
                           "do not switch cardinality without verifying key uniqueness.",
            source_file=relationship.source_file, line=relationship.line,
        ))
    return findings


def missing_measure_descriptions(objects: Iterable[ModelObject]) -> list[HealthFinding]:
    findings = []
    for obj in objects:
        if obj.ref.object_type != ObjectType.MEASURE or is_internal_table(obj.ref.table):
            continue
        if obj.description is None or obj.description.strip() or obj.source_line is None:
            continue
        findings.append(HealthFinding(
            rule_id="MEASURE_DESCRIPTION_MISSING", category="metadata",
            severity=HealthSeverity.INFO, confidence="high", scope=obj.ref.label,
            title="Document this measure",
            explanation="No nonblank TMDL description was found for this measure. "
                        "A description can help readers understand its business meaning; "
                        "this is a documentation opportunity, not a calculation defect.",
            evidence=("Measure description is absent or blank", obj.ref.label),
            recommendation="Add a description immediately above the measure using TMDL /// lines. "
                           "Explain its business meaning, units, and relevant filter or time assumptions. "
                           "Prioritize measures that other model authors or report users need to understand.",
            source_file=obj.source_file, line=obj.source_line,
        ))
    return findings


def unresolved_dax_references(objects: Iterable[ModelObject]) -> list[HealthFinding]:
    objects = tuple(objects)
    columns = {norm_key(o.ref.table, o.ref.name): o.ref for o in objects if o.ref.object_type == ObjectType.COLUMN}
    measures = {norm_key(o.ref.table, o.ref.name): o.ref for o in objects if o.ref.object_type == ObjectType.MEASURE}
    index = DaxIndex.build(columns, measures)
    findings = []
    for obj in objects:
        if obj.ref.object_type not in {ObjectType.COLUMN, ObjectType.MEASURE} or not obj.expression:
            continue
        # Findings need a source location; TMDL-parsed objects always have one.
        if is_internal_table(obj.ref.table) or obj.source_line is None:
            continue
        missing = unresolved_references(obj.expression, index)
        if not missing:
            continue
        evidence = tuple(
            f"'{table}'[{field}]: " + (f"table {table} has no column or measure named {field}" if known
                                       else f"no table named {table} in the parsed model")
            for table, field, known in missing)
        kind = "measure" if obj.ref.object_type == ObjectType.MEASURE else "calculated column"
        findings.append(HealthFinding(
            rule_id="DAX_REFERENCE_UNRESOLVED", category="dax",
            severity=HealthSeverity.WARNING,
            # A missing table may be one whose TMDL file could not be parsed.
            confidence="high" if all(known for _, _, known in missing) else "medium",
            scope=obj.ref.label,
            title=f"Fix references to missing model objects in this {kind}",
            explanation=f"This {kind} references model objects that do not exist in the parsed model. "
                        "Power BI reports an error when it evaluates such an expression, so visuals "
                        "using it show errors. This often follows a renamed or removed column.",
            evidence=evidence,
            recommendation="Update the reference to the current column or measure name, or remove the "
                           f"{kind} if it is no longer needed. If the referenced table exists but was not "
                           "parsed (see diagnostics), resolve that first and re-run the analysis.",
            source_file=obj.source_file, line=obj.source_line,
        ))
    return findings
