from collections.abc import Iterable

from ..model import ModelObject
from ..parsers.relationships import Relationship
from .model import HealthFinding
from .rules import (bidirectional_relationships, many_to_many_relationships, missing_measure_descriptions,
                    unresolved_dax_references)


RULES = (
    ("RELATIONSHIP_BIDIRECTIONAL", bidirectional_relationships, "relationships"),
    ("RELATIONSHIP_MANY_TO_MANY", many_to_many_relationships, "relationships"),
    ("MEASURE_DESCRIPTION_MISSING", missing_measure_descriptions, "objects"),
    ("DAX_REFERENCE_UNRESOLVED", unresolved_dax_references, "objects"),
)


def evaluate_health(relationships: list[Relationship], objects: Iterable[ModelObject] = ()) -> list[HealthFinding]:
    """Evaluate deterministic rules over parsed state without changing the graph."""
    inputs = {"relationships": relationships, "objects": tuple(objects)}
    return [finding for _, rule, source in RULES for finding in rule(inputs[source])]
