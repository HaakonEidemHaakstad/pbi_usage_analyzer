from collections.abc import Iterable
from pathlib import Path
import re

from ..model import ModelObject, ObjectType
from ..parsers.dax import DaxIndex, unresolved_references
from ..parsers.m_queries import MQuery, MQueryKind, appended_query_refs, folder_listing, m_string_literals
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


FILE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/])")
USER_PROFILE = re.compile(r"^[A-Za-z]:[\\/]Users[\\/][^\\/]+|OneDrive", re.I)


def hardcoded_m_paths(queries: Iterable[MQuery]) -> list[HealthFinding]:
    findings = []
    for query in queries:
        # A parameter is the recommended home for a path.
        if query.kind == MQueryKind.PARAMETER:
            continue
        paths: list[tuple[str, int]] = []
        for value, line in m_string_literals(query.source):
            if FILE_PATH.match(value) and value not in (p for p, _ in paths):
                paths.append((value, query.file_line(line)))
        if not paths:
            continue
        evidence = tuple(
            f"line {line}: {value}" + (" (user profile or OneDrive folder)" if USER_PROFILE.search(value) else "")
            for value, line in paths)
        findings.append(HealthFinding(
            rule_id="POWERQUERY_HARDCODED_PATH", category="power_query",
            severity=HealthSeverity.WARNING, confidence="high", scope=query.name,
            title="Move hard-coded file paths into parameters",
            explanation="This query reads from a literal local or network path. Refresh fails on "
                        "other machines and in the Power BI service unless the same path exists "
                        "there (the service needs a gateway for local and network files). Paths "
                        "inside a personal user or OneDrive folder are the most fragile.",
            evidence=evidence,
            recommendation="Create a text parameter for the folder (Manage Parameters) and build paths "
                           "from it, for example File.Contents(DataFolder & \"\\sales.csv\"). For shared "
                           "models, prefer a shared location such as SharePoint or a database and plan "
                           "the gateway. A single-user file may accept the path, but record the decision.",
            source_file=query.source_file, line=paths[0][1],
        ))
    return findings


def _appends(queries: tuple[MQuery, ...]) -> list[tuple[MQuery, MQuery, int]]:
    """(appending query, appended query, file line of Table.Combine), first occurrence each."""
    by_name = {query.name: query for query in queries if query.kind != MQueryKind.PARAMETER}
    appends, seen = [], set()
    for owner in queries:
        if owner.kind == MQueryKind.PARAMETER:
            continue
        for name, line in appended_query_refs(owner.source):
            appended = by_name.get(name)
            if appended is None or appended.name == owner.name or (owner.name, name) in seen:
                continue
            seen.add((owner.name, name))
            appends.append((owner, appended, owner.file_line(line)))
    return appends


def loaded_append_inputs(queries: Iterable[MQuery]) -> list[HealthFinding]:
    appended_by: dict[str, list[tuple[MQuery, int]]] = {}
    inputs: dict[str, MQuery] = {}
    for owner, appended, line in _appends(tuple(queries)):
        # TMDL keeps loaded queries as table partitions; load-disabled ones are expressions.
        if owner.kind == MQueryKind.PARTITION and appended.kind == MQueryKind.PARTITION:
            appended_by.setdefault(appended.name, []).append((owner, line))
            inputs[appended.name] = appended
    findings = []
    for name, owners in appended_by.items():
        query = inputs[name]
        findings.append(HealthFinding(
            rule_id="POWERQUERY_APPEND_INPUT_LOADED", category="power_query",
            severity=HealthSeverity.WARNING, confidence="high", scope=name,
            title="Disable load for queries that only feed an append",
            explanation="This query is loaded as a model table and is also appended into another "
                        "loaded table, so its rows are imported twice. That increases model size and "
                        "refresh time, and report authors can use the partial table by mistake.",
            evidence=(*(f"Appended by query '{owner.name}' (Table.Combine, {Path(owner.source_file).name} "
                        f"line {line})" for owner, line in owners),
                      f"'{name}' has an import partition, so it is loaded as a model table"),
            recommendation="If nothing uses this table directly (check its cleanup statuses and the "
                           "report), clear Enable load for the query in the Power Query editor; the "
                           "append keeps working and the query becomes a shared expression. If reports "
                           "use it, consider pointing them at the appended table instead.",
            source_file=query.source_file, line=query.line,
        ))
    return findings


def unfiltered_folder_sources(queries: Iterable[MQuery]) -> list[HealthFinding]:
    findings = []
    for query in queries:
        if query.kind == MQueryKind.PARAMETER:
            continue
        listing = folder_listing(query.source)
        # A listing without content reads is a file inventory, not a combine.
        if listing is None or listing.content_line is None or listing.selections:
            continue
        evidence = [f"line {query.file_line(line)}: Folder.Files({argument})" for line, argument in listing.calls]
        evidence.append(f"line {query.file_line(listing.content_line)}: reads file contents ([Content])")
        evidence.append("Only the hidden-files filter Power BI adds by default" if listing.hidden_filter_lines
                        else "No filter on file name, extension, folder path or date")
        findings.append(HealthFinding(
            rule_id="POWERQUERY_FOLDER_UNFILTERED", category="power_query",
            # Absence of a filter is inferred; a custom function may still select files.
            severity=HealthSeverity.WARNING, confidence="medium", scope=query.name,
            title="Filter folder sources to the intended files",
            explanation="This query combines the contents of every file in a folder, including "
                        "subfolders. Any extra file placed there later, such as a copy, backup, "
                        "export or temporary Excel lock file, is combined without warning and can "
                        "double count rows or break the refresh.",
            evidence=tuple(evidence),
            recommendation="Add a filter step right after the folder source, for example on "
                           "Extension and a Name pattern (Table.SelectRows(Source, each [Extension] = "
                           "\".csv\" and Text.StartsWith([Name], \"Sales\"))). Check the folder for "
                           "duplicates now. If the folder is controlled and all files belong, "
                           "record that decision.",
            source_file=query.source_file, line=query.file_line(listing.calls[0][0]),
        ))
    return findings


YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def annual_appends(queries: Iterable[MQuery]) -> list[HealthFinding]:
    yearly: dict[str, list[tuple[MQuery, int, str]]] = {}
    owners: dict[str, MQuery] = {}
    for owner, appended, line in _appends(tuple(queries)):
        year = YEAR.search(appended.name)
        if year:
            yearly.setdefault(owner.name, []).append((appended, line, year.group()))
            owners[owner.name] = owner
    findings = []
    for name, appended in yearly.items():
        owner = owners[name]
        years = sorted({year for _, _, year in appended})
        findings.append(HealthFinding(
            rule_id="POWERQUERY_ANNUAL_APPEND", category="power_query",
            severity=HealthSeverity.INFO,
            # One year-named input may be an archive beside a current query.
            confidence="high" if len(years) > 1 else "medium", scope=name,
            title="Replace the hard-coded yearly append with one parameterized source",
            explanation="This query appends separate queries whose names contain years. Each new year "
                        "then needs a new query and an edit to the append; a forgotten year silently "
                        "leaves data out. Per-year queries also repeat the same transformation steps.",
            evidence=tuple(f"Appends '{query.name}' (year {year}) at {Path(owner.source_file).name} line {line}"
                           for query, line, year in appended),
            recommendation="Where the yearly sources share a structure, load them through one query: "
                           "a folder source filtered by file name, one database table or view with a "
                           "date filter, or a custom function invoked per file. Consider incremental "
                           "refresh for large history. Keep separate queries if the years genuinely "
                           "differ in structure, and record that decision.",
            source_file=owner.source_file, line=appended[0][1],
        ))
    return findings
