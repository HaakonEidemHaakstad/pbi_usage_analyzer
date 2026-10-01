from collections.abc import Iterable
from dataclasses import dataclass

from ..model import ModelObject
from ..parsers.relationships import Relationship
from .model import HealthFinding, HealthSeverity
from ..parsers.m_queries import MQuery
from .rules import (annual_appends, bidirectional_relationships, duplicate_measures, hardcoded_m_paths,
                    loaded_append_inputs, local_servers,
                    many_to_many_relationships, missing_measure_descriptions, text_key_relationships,
                    unfiltered_folder_sources, unresolved_dax_references)


# (rule ID, evaluator, names of the parsed inputs passed to it in order)
RULES = (
    ("RELATIONSHIP_BIDIRECTIONAL", bidirectional_relationships, ("relationships",)),
    ("RELATIONSHIP_MANY_TO_MANY", many_to_many_relationships, ("relationships",)),
    ("RELATIONSHIP_TEXT_KEY", text_key_relationships, ("relationships", "objects")),
    ("MEASURE_DESCRIPTION_MISSING", missing_measure_descriptions, ("objects",)),
    ("DAX_REFERENCE_UNRESOLVED", unresolved_dax_references, ("objects",)),
    ("MEASURE_DUPLICATE_EXPRESSION", duplicate_measures, ("objects",)),
    ("POWERQUERY_HARDCODED_PATH", hardcoded_m_paths, ("m_queries",)),
    ("POWERQUERY_LOCAL_SERVER", local_servers, ("m_queries",)),
    ("POWERQUERY_APPEND_INPUT_LOADED", loaded_append_inputs, ("m_queries",)),
    ("POWERQUERY_ANNUAL_APPEND", annual_appends, ("m_queries",)),
    ("POWERQUERY_FOLDER_UNFILTERED", unfiltered_folder_sources, ("m_queries",)),
)



@dataclass(frozen=True)
class RuleInfo:
    """Fixed metadata of a rule, available before any finding exists."""
    rule_id: str
    category: str
    severity: HealthSeverity
    name: str
    summary: str


_W, _I = HealthSeverity.WARNING, HealthSeverity.INFO
RULE_INFO = {info.rule_id: info for info in (
    RuleInfo("RELATIONSHIP_BIDIRECTIONAL", "relationships", _W, "Bidirectional relationship",
             "An active relationship filters in both directions."),
    RuleInfo("RELATIONSHIP_MANY_TO_MANY", "relationships", _W, "Many-to-many relationship",
             "An active relationship has many-to-many cardinality."),
    RuleInfo("RELATIONSHIP_TEXT_KEY", "relationships", _I, "Text relationship key",
             "A relationship joins on a text column."),
    RuleInfo("MEASURE_DESCRIPTION_MISSING", "metadata", _I, "Measure without description",
             "A measure has no description for report authors."),
    RuleInfo("DAX_REFERENCE_UNRESOLVED", "dax", _W, "Reference to a missing object",
             "DAX refers to a column or measure that the model does not contain."),
    RuleInfo("MEASURE_DUPLICATE_EXPRESSION", "dax", _I, "Duplicate measures",
             "Several measures have identical DAX."),
    RuleInfo("POWERQUERY_HARDCODED_PATH", "power_query", _W, "Hard-coded file path",
             "M reads from a literal drive or network path."),
    RuleInfo("POWERQUERY_LOCAL_SERVER", "power_query", _W, "Local server name",
             "M connects to localhost or another name for the local machine."),
    RuleInfo("POWERQUERY_APPEND_INPUT_LOADED", "power_query", _W, "Loaded append input",
             "A loaded query is also appended into another loaded table."),
    RuleInfo("POWERQUERY_ANNUAL_APPEND", "power_query", _I, "Hard-coded yearly append",
             "A query appends separate per-year queries."),
    RuleInfo("POWERQUERY_FOLDER_UNFILTERED", "power_query", _W, "Unfiltered folder source",
             "A folder is combined without selecting which files to read."),
)}


def evaluate_health(relationships: list[Relationship], objects: Iterable[ModelObject] = (),
                    m_queries: Iterable[MQuery] = ()) -> list[HealthFinding]:
    """Evaluate deterministic rules over parsed state without changing the graph."""
    inputs = {"relationships": relationships, "objects": tuple(objects), "m_queries": tuple(m_queries)}
    return [finding for _, rule, sources in RULES
            for finding in rule(*(inputs[source] for source in sources))]
