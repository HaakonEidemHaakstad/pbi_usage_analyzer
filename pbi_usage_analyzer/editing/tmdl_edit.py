"""Text-preserving edits of single properties in a TMDL table file.

Only the lines of the edited property change: indentation style, line endings, a
byte-order mark, property order and every other line are kept, so a diff shows
exactly the intended change. Values are written as the TMDL specification asks
(text quoted only when needed, `""` inside quotes; descriptions as `///` lines
directly above the object) and as Power BI Desktop writes them (`isHidden` after
`dataType`, `changedProperty = IsHidden` on columns).

Anything outside the layouts handled here raises `EditError` instead of guessing:
unterminated or repeated ``` fences, `description:` properties, dynamic format strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import ObjectRef, ObjectType
from ..parsers.tmdl import COLUMN_HEADER, MEASURE_HEADER, TABLE_HEADER, split_object_definition
from ..util import clean_name, norm

BOM = "﻿"
_HEADERS = {ObjectType.COLUMN: COLUMN_HEADER, ObjectType.MEASURE: MEASURE_HEADER}
_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*(:|$)")
# Child objects inside a column/measure; simple properties come before them.
_CHILD = re.compile(r"^(annotation|extendedProperty|variation|changedProperty|formatStringDefinition|"
                    r"detailRowsDefinition|kpi|relatedColumnDetails|alternateOf)\b", re.I)


class EditError(Exception):
    """The edit cannot be made safely; `code` is stable, the message explains why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TmdlDocument:
    """A decoded TMDL file that re-encodes byte for byte when unchanged."""
    lines: tuple[str, ...]
    newline: str
    bom: bool

    @classmethod
    def decode(cls, data: bytes) -> "TmdlDocument":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EditError("TMDL_NOT_UTF8", f"the file is not valid UTF-8 ({exc.reason})") from exc
        bom = text.startswith(BOM)
        if bom:
            text = text[1:]
        newline = "\r\n" if "\r\n" in text else "\n"
        return cls(tuple(text.split(newline)), newline, bom)

    def encode(self) -> bytes:
        return ((BOM if self.bom else "") + self.newline.join(self.lines)).encode("utf-8")


@dataclass(frozen=True)
class ObjectProperties:
    """Current values of the editable properties (None: not set)."""
    description: str | None
    display_folder: str | None
    format_string: str | None
    hidden: bool
    dynamic_format: bool


@dataclass(frozen=True)
class _Span:
    header: int        # index of the header line
    end: int           # index after the object's block
    indent: str        # header indentation
    prop_indent: str   # indentation of the object's properties
    props: int         # index of the first property line (after a multi-line expression)
    children: int      # index of the first child object, or `end`
    fenced: bool


def _leading(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def _is_header(line: str, ref: ObjectRef) -> bool:
    if ref.object_type == ObjectType.TABLE:
        match = TABLE_HEADER.match(line)
        return bool(match) and not _leading(line) and norm(clean_name(match.group(1))) == norm(ref.table)
    match = _HEADERS[ref.object_type].match(line)
    if not match or not match.group(1):
        return False
    name = split_object_definition(match.group(2))[0]
    return norm(name) == norm(ref.name)


def _locate(lines: tuple[str, ...], ref: ObjectRef) -> _Span:
    if ref.object_type not in (ObjectType.TABLE, ObjectType.COLUMN, ObjectType.MEASURE):
        raise EditError("OBJECT_TYPE_UNSUPPORTED", f"{ref.object_type.value.lower()}s cannot be edited")
    hits = [i for i, line in enumerate(lines) if _is_header(line, ref)]
    if not hits:
        raise EditError("OBJECT_NOT_IN_FILE", f"{ref.label} is not declared in this file")
    if len(hits) > 1:
        raise EditError("OBJECT_DECLARED_TWICE", f"{ref.label} is declared more than once in this file")
    header = hits[0]
    indent = _leading(lines[header])
    inline = ""
    if ref.object_type != ObjectType.TABLE:
        _, has_expression, inline = split_object_definition(_HEADERS[ref.object_type].match(lines[header]).group(2))
    end = header + 1
    if inline == "```":
        # Fenced content may have any indentation, so skip to the closing fence first.
        while end < len(lines) and lines[end].strip() != "```":
            end += 1
        end = min(end + 1, len(lines))
    while end < len(lines) and (not lines[end].strip() or len(_leading(lines[end])) > len(indent)):
        end += 1
    while end > header + 1 and not lines[end - 1].strip():
        end -= 1  # trailing blank lines belong between objects
    if ref.object_type == ObjectType.TABLE:
        return _Span(header, end, indent, "", end, end, False)
    block = [i for i in range(header + 1, end) if lines[i].strip()]
    fences = [i for i in block if lines[i].strip() == "```"]
    fenced = bool(fences)
    candidates = block
    if inline == "```" and fences:
        # Power BI Desktop fences an expression with trailing whitespace; the content may
        # have any indentation, and the properties follow the closing fence.
        candidates = [i for i in block if i > fences[0]]
        fenced = len(fences) > 1  # more fences than one expression: not a layout handled here
    elif inline == "```":
        fenced = True
    elif has_expression and not inline and block:
        # A multi-line expression follows the header, one level deeper than the properties.
        depth = len(_leading(lines[block[0]]))
        candidates = [i for i in block if len(_leading(lines[i])) < depth]
    if candidates:
        prop_indent = min((_leading(lines[i]) for i in candidates), key=len)
    else:
        prop_indent = indent + ("\t" if "\t" in indent or not indent else indent)
    props = next((i for i in candidates if _leading(lines[i]) == prop_indent), end)
    children = next((i for i in block if i >= props and _leading(lines[i]) == prop_indent
                     and _CHILD.match(lines[i].strip())), end)
    return _Span(header, end, indent, prop_indent, props, children, fenced)


def _property_lines(lines: tuple[str, ...], span: _Span) -> list[int]:
    return [i for i in range(span.props, span.children) if _leading(lines[i]) == span.prop_indent]


def _find(lines: tuple[str, ...], span: _Span, key: str) -> list[int]:
    found = []
    for i in _property_lines(lines, span):
        match = _KEY.match(lines[i].strip())
        if match and match.group(1).casefold() == key.casefold():
            found.append(i)
    return found


def _hidden_flags(lines: tuple[str, ...], span: _Span) -> tuple[list[int], bool]:
    """`isHidden` property lines and whether they make the object hidden."""
    flags = _find(lines, span, "isHidden")
    hidden = any(_value(lines[i]).casefold() in ("", "true") for i in flags)
    return flags, hidden


def _value(line: str) -> str:
    raw = line.split(":", 1)[1].strip() if ":" in line else ""
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('""', '"')
    return raw


def tmdl_text(value: str) -> str:
    """A text property value as TMDL needs it: quoted when it has outer whitespace or quotes."""
    if value != value.strip() or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def normalize_description(value: str) -> str:
    """The description as it reads back from `///` lines (each line trimmed)."""
    return "\n".join(line.strip() for line in value.strip().splitlines())


def _description_lines(lines: tuple[str, ...], span: _Span) -> range:
    start = span.header
    while start > 0 and _leading(lines[start - 1]) == span.indent and lines[start - 1].strip().startswith("///"):
        start -= 1
    return range(start, span.header)


def read_properties(document: TmdlDocument, ref: ObjectRef) -> ObjectProperties:
    lines = document.lines
    span = _locate(lines, ref)
    described = _description_lines(lines, span)
    description = ("\n".join(lines[i].strip()[3:].strip() for i in described) if described else None)
    if ref.object_type == ObjectType.TABLE:
        return ObjectProperties(description, None, None, False, False)
    folder = _find(lines, span, "displayFolder")
    fmt = _find(lines, span, "formatString")
    hidden = _hidden_flags(lines, span)[1]
    dynamic = any(_leading(lines[i]) == span.prop_indent and lines[i].strip().startswith("formatStringDefinition")
                  for i in range(span.props, span.end))
    return ObjectProperties(description, _value(lines[folder[0]]) if folder else None,
                            _value(lines[fmt[0]]) if fmt else None, hidden, dynamic)


def _checked_span(lines: tuple[str, ...], ref: ObjectRef) -> _Span:
    span = _locate(lines, ref)
    if span.fenced:
        raise EditError("TMDL_LAYOUT_UNSUPPORTED",
                        f"{ref.label} has a ``` fenced expression whose end this editor cannot determine")
    return span


def set_description(document: TmdlDocument, ref: ObjectRef, value: str) -> TmdlDocument:
    lines = document.lines
    span = _checked_span(lines, ref)
    if ref.object_type != ObjectType.TABLE and _find(lines, span, "description"):
        raise EditError("TMDL_LAYOUT_UNSUPPORTED",
                        f"{ref.label} has a description: property; this editor only writes /// descriptions")
    text = normalize_description(value)
    new = [f"{span.indent}///{' ' + line if line else ''}" for line in text.split("\n")] if text else []
    described = _description_lines(lines, span)
    return _replace(document, described.start, span.header, new)


def set_property(document: TmdlDocument, ref: ObjectRef, key: str, value: str | None) -> TmdlDocument:
    """Set (or with None remove) a simple text property such as displayFolder or formatString."""
    lines = document.lines
    span = _checked_span(lines, ref)
    if ref.object_type == ObjectType.TABLE:
        raise EditError("OBJECT_TYPE_UNSUPPORTED", f"{key} cannot be set on a table")
    existing = _find(lines, span, key)
    if key == "formatString":
        if any(_leading(lines[i]) == span.prop_indent and lines[i].strip().startswith("formatStringDefinition")
               for i in range(span.props, span.end)):
            raise EditError("TMDL_LAYOUT_UNSUPPORTED",
                            f"{ref.label} has a dynamic format string (formatStringDefinition)")
    new = [] if value is None else [f"{span.prop_indent}{key}: {tmdl_text(value)}"]
    if existing:
        document = _replace(document, existing[0], existing[0] + 1, new)
        for i in reversed(existing[1:]):  # a duplicate would not deserialize; drop it
            document = _replace(document, i, i + 1, [])
        return document
    if not new:
        return document
    lineage = _find(lines, span, "lineageTag")
    properties = _property_lines(lines, span)
    at = lineage[0] if lineage else (properties[-1] + 1 if properties else span.props)
    return _replace(document, at, at, new)


def set_hidden(document: TmdlDocument, ref: ObjectRef, hidden: bool) -> TmdlDocument:
    lines = document.lines
    span = _checked_span(lines, ref)
    if ref.object_type == ObjectType.TABLE:
        raise EditError("OBJECT_TYPE_UNSUPPORTED", "tables cannot be hidden with this editor")
    flags = _hidden_flags(lines, span)[0]
    if ref.object_type == ObjectType.COLUMN and not any(
            _leading(lines[i]) == span.prop_indent and re.match(r"changedProperty\s*=\s*IsHidden\s*$",
                                                                 lines[i].strip(), re.I)
            for i in range(span.props, span.end)):
        # Power BI Desktop records a user-changed visibility this way on columns.
        child = span.children
        if child < span.end:
            document = _replace(document, child, child, [f"{span.prop_indent}changedProperty = IsHidden", ""])
        else:
            last = max([span.header] + [i for i in range(span.header + 1, span.end) if lines[i].strip()])
            document = _replace(document, last + 1, last + 1, ["", f"{span.prop_indent}changedProperty = IsHidden"])
    for i in reversed(flags):
        document = _replace(document, i, i + 1, [])
    if hidden:
        lines = document.lines
        span = _locate(lines, ref)
        data_type = _find(lines, span, "dataType")
        at = data_type[0] + 1 if data_type else span.props
        document = _replace(document, at, at, [f"{span.prop_indent}isHidden"])
    return document


def _replace(document: TmdlDocument, start: int, stop: int, new: list[str]) -> TmdlDocument:
    lines = list(document.lines)
    lines[start:stop] = new
    return TmdlDocument(tuple(lines), document.newline, document.bom)
