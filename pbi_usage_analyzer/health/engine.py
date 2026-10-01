from collections.abc import Iterable

from ..model import ModelObject
from ..parsers.relationships import Relationship
from .model import HealthFinding
from ..parsers.m_queries import MQuery
from .rules import (annual_appends, bidirectional_relationships, hardcoded_m_paths, loaded_append_inputs,
                    many_to_many_relationships, missing_measure_descriptions, unresolved_dax_references)


RULES = (
    ("RELATIONSHIP_BIDIRECTIONAL", bidirectional_relationships, "relationships"),
    ("RELATIONSHIP_MANY_TO_MANY", many_to_many_relationships, "relationships"),
    ("MEASURE_DESCRIPTION_MISSING", missing_measure_descriptions, "objects"),
    ("DAX_REFERENCE_UNRESOLVED", unresolved_dax_references, "objects"),
    ("POWERQUERY_HARDCODED_PATH", hardcoded_m_paths, "m_queries"),
    ("POWERQUERY_APPEND_INPUT_LOADED", loaded_append_inputs, "m_queries"),
    ("POWERQUERY_ANNUAL_APPEND", annual_appends, "m_queries"),
)


def evaluate_health(relationships: list[Relationship], objects: Iterable[ModelObject] = (),
                    m_queries: Iterable[MQuery] = ()) -> list[HealthFinding]:
    """Evaluate deterministic rules over parsed state without changing the graph."""
    inputs = {"relationships": relationships, "objects": tuple(objects), "m_queries": tuple(m_queries)}
    return [finding for _, rule, source in RULES for finding in rule(inputs[source])]
