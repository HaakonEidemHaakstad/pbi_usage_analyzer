"""Bounded extraction of special DAX expressions from TMDL declarations."""
from dataclasses import dataclass
from pathlib import Path
import re

from ..model import Evidence, EvidenceType, ObjectRef, ObjectType
from ..util import indentation, read_source_text
from .dax import dax_dependencies
from .dax_lexer import mask_dax_literals
from .tmdl import split_object_definition


def nameof_arguments(expression: str) -> list[str]:
    # Consume identifier tokens before looking for a function token, so text
    # inside a quoted table name or bracketed field cannot introduce a call.
    token = re.compile(r"'(?:[^']|'')*'|\[(?:[^\]]|\]\])*\]|\bNAMEOF\s*\(", re.I)
    result = []
    for match in token.finditer(expression):
        if match.group().startswith(("'", '[')):
            continue
        start = match.end()
        # Supported NAMEOF form: a single object reference, no nested calls.
        identifier = re.compile(r"\s*(?:'(?:[^']|'')*'|[^\[(),']+)?\s*\[(?:[^\]]|\]\])*\]\s*\)")
        argument = identifier.match(expression, start)
        if argument:
            result.append(argument.group()[:-1])
    return result


@dataclass(frozen=True)
class SpecialExpression:
    kind: EvidenceType
    expression: str
    line: int
    # Table whose row context is certain (an RLS table permission's table).
    row_table: str | None = None


def extract_special_expressions(text: str) -> list[SpecialExpression]:
    lines = mask_dax_literals(text).splitlines()
    found = []

    def children(start, end, context):
        i = start
        while i < end:
            raw = lines[i]
            stripped = raw.strip()
            if not stripped or stripped.startswith('//'):
                i += 1
                continue
            indent = indentation(raw)
            stop = i + 1
            while stop < end and (not lines[stop].strip() or indentation(lines[stop]) > indent):
                stop += 1
            keyword = stripped.split(None, 1)[0].lower()
            # Only descend through recognized containers. Annotation contents,
            # descriptions, and unrelated declarations cannot become DAX roots.
            if keyword in {'table', 'role', 'calculationgroup', 'partition'}:
                next_context = context + (keyword,)
                if keyword == 'partition' and not re.search(r'=\s*calculated\s*$', stripped, re.I):
                    i = stop
                    continue
                children(i + 1, stop, next_context)
            else:
                kind = None
                if keyword == 'tablepermission' and context and context[-1] == 'role':
                    kind = EvidenceType.RLS_DEPENDENCY
                elif ((keyword == 'calculationitem' and context and context[-1] == 'calculationgroup')
                      or (keyword == 'formatstringdefinition' and context and context[-1] == 'calculationitem')):
                    kind = EvidenceType.CALCULATION_GROUP_DEPENDENCY
                candidate = kind is not None or (keyword in {'measure', 'column'} and context and context[-1] == 'table') or (keyword == 'source' and context and context[-1] == 'partition')
                if candidate:
                    _, has_expression, inline = split_object_definition(stripped)
                    if has_expression:
                        body = []
                        fenced = inline == '```'
                        if inline and not fenced:
                            body.append(inline)
                        if fenced:
                            for line in lines[i + 1:stop]:
                                if line.strip() == '```':
                                    break
                                body.append(line)
                        else:
                            for line in lines[i + 1:stop]:
                                value = line.strip()
                                # Properties are separate from the default DAX expression.
                                if re.match(r'^[A-Za-z][A-Za-z0-9]*\s*:', value) or value.startswith(('annotation ', 'extendedProperty ', 'formatStringDefinition', 'isHidden')):
                                    break
                                body.append(line)
                        expression = mask_dax_literals('\n'.join(body))
                        if kind == EvidenceType.RLS_DEPENDENCY:
                            table = split_object_definition(stripped.split(None, 1)[1])[0]
                            found.append(SpecialExpression(kind, expression, i + 1, table))
                        elif kind is not None:
                            found.append(SpecialExpression(kind, expression, i + 1))
                        else:
                            for argument in nameof_arguments(expression):
                                found.append(SpecialExpression(EvidenceType.FIELD_PARAMETER_DEPENDENCY, argument, i + 1))
                if keyword == 'calculationitem' and context and context[-1] == 'calculationgroup':
                    children(i + 1, stop, context + ('calculationitem',))
            i = stop

    children(0, len(lines), ())
    return found


def special_dax_evidence(path: Path, columns, measures) -> list[Evidence]:
    owner = ObjectRef(ObjectType.TABLE, f'Special:{path.name}')
    evidence = []
    for item in extract_special_expressions(read_source_text(path)[0]):
        for edge in dax_dependencies(owner, item.expression, columns, measures, row_table=item.row_table):
            # Only proven references become special roots; unresolved row-context
            # guesses must not be promoted to Used.
            if edge.evidence_type != EvidenceType.DAX_DEPENDENCY:
                continue
            evidence.append(Evidence(owner, edge.target, item.kind,
                                    f'Referenced by {item.kind.value} in {path.name}:{item.line}',
                                    str(path), 'medium'))
    return evidence
