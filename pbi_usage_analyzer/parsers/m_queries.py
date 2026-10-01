"""Collect Power Query (M) sources from TMDL: table partitions and shared expressions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from ..util import clean_name, indentation, read_source_text
from .tmdl import PROPERTY_LINE, PROPERTY_PREFIXES, split_object_definition

EXPRESSION_HEADER = re.compile(r"^(\s*)expression\s+(.+?)\s*$")
PARTITION_HEADER = re.compile(r"^(\s*)partition\s+.+=\s*m\s*$", re.I)
TABLE_HEADER = re.compile(r"^\s*table\s+(.+?)\s*$")
PARAMETER_META = re.compile(r"\bmeta\s*\[[^\]]*\bIsParameterQuery\s*=\s*true", re.I)


class MQueryKind(str, Enum):
    PARTITION = "partition"
    EXPRESSION = "expression"
    PARAMETER = "parameter"


@dataclass(frozen=True)
class MQuery:
    name: str
    kind: MQueryKind
    source: str
    source_file: str
    lines: tuple[int, ...]  # 1-based file line of each source line

    @property
    def line(self) -> int:
        return self.lines[0]

    def file_line(self, source_line: int) -> int:
        """File line for a 1-based line within ``source``."""
        return self.lines[source_line - 1]


def _numbered(parts: list[tuple[int, str]]) -> tuple[str, tuple[int, ...]]:
    while parts and not parts[0][1]:
        parts = parts[1:]
    while parts and not parts[-1][1]:
        parts = parts[:-1]
    return "\n".join(text for _, text in parts), tuple(number for number, _ in parts)


def _body(lines: list[str], start: int, header_indent: int) -> list[tuple[int, str]]:
    """(file line, text) after a header until indentation returns or a property starts."""
    body: list[tuple[int, str]] = []
    fenced = False
    i = start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped == "```":
            fenced = not fenced
            i += 1
            continue
        if not fenced and stripped:
            if indentation(raw) <= header_indent:
                break
            if stripped.startswith(PROPERTY_PREFIXES) or PROPERTY_LINE.match(stripped):
                break
        body.append((i + 1, stripped))
        i += 1
    return body


def _partitions(path: Path, lines: list[str]) -> list[MQuery]:
    table = next((clean_name(m.group(1)) for m in map(TABLE_HEADER.match, lines) if m), None)
    queries = []
    for i, line in enumerate(lines):
        header = PARTITION_HEADER.match(line)
        if not header:
            continue
        indent = len(header.group(1))
        for j in range(i + 1, len(lines)):
            stripped = lines[j].strip()
            if stripped and indentation(lines[j]) <= indent:
                break
            if stripped.startswith("source ="):
                inline = stripped[len("source ="):].strip()
                source, numbers = _numbered(([(j + 1, inline)] if inline else [])
                                            + _body(lines, j + 1, indentation(lines[j])))
                if source:
                    queries.append(MQuery(table or path.stem, MQueryKind.PARTITION, source, str(path), numbers))
                break
    return queries


def _expressions(path: Path, lines: list[str]) -> list[MQuery]:
    queries = []
    for i, line in enumerate(lines):
        header = EXPRESSION_HEADER.match(line)
        if not header:
            continue
        name, has_value, inline = split_object_definition(header.group(2))
        if not has_value:
            continue
        inline = "" if inline == "```" else inline
        source, numbers = _numbered(([(i + 1, inline)] if inline else []) + _body(lines, i + 1, len(header.group(1))))
        if not source:
            continue
        kind = MQueryKind.PARAMETER if PARAMETER_META.search(source) else MQueryKind.EXPRESSION
        queries.append(MQuery(name, kind, source, str(path), numbers))
    return queries


def collect_m_queries(model_folder: Path) -> list[MQuery]:
    """M sources of import partitions and shared expressions, in file order."""
    definition = model_folder / "definition"
    queries: list[MQuery] = []
    for path in sorted((definition / "tables").glob("*.tmdl")):
        queries += _partitions(path, read_source_text(path)[0].splitlines())
    expressions = definition / "expressions.tmdl"
    if expressions.is_file():
        queries += _expressions(expressions, read_source_text(expressions)[0].splitlines())
    return queries


COMBINE_CALL = re.compile(r'(?<![\w.#"])Table\.Combine\s*\(\s*\{')
QUOTED_IDENTIFIER = re.compile(r'#"((?:[^"]|"")*)"')
SIMPLE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Names bound with `name =` (let steps, record fields; `if a = b` over-collects,
# which only hides references). Field access `[name]` is excluded.
BOUND_NAME = re.compile(r'(?:(?<![\w.#\["])#"((?:[^"]|"")*)"|(?<![\w.#"\[])([A-Za-z_]\w*))\s*=(?![=>])')


def _mask_m(source: str) -> str:
    """Blank comments and text literals (same offsets/newlines); keep `#"..."` names."""
    out = list(source)
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = len(source) if end < 0 else end + 2
        elif source[i] == '"' or source.startswith('#"', i):
            identifier = source[i] == "#"
            end = i + (2 if identifier else 1)
            while end < len(source):
                if source.startswith('""', end):
                    end += 2
                elif source[end] == '"':
                    end += 1
                    break
                else:
                    end += 1
            if identifier:
                i = end
                continue
        else:
            i += 1
            continue
        for j in range(i, end):
            if out[j] != "\n":
                out[j] = " "
        i = end
    return "".join(out)


def _list_items(masked: str, start: int) -> list[str] | None:
    """Top-level items of the `{...}` list whose contents start at ``start``."""
    items, depth, i, item_start = [], 0, start, start
    while i < len(masked):
        if masked.startswith('#"', i):
            match = QUOTED_IDENTIFIER.match(masked, i)
            i = match.end() if match else len(masked)
            continue
        char = masked[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                if char != "}":
                    return None
                items.append(masked[item_start:i].strip())
                return [item for item in items if item]
            depth -= 1
        elif char == "," and depth == 0:
            items.append(masked[item_start:i].strip())
            item_start = i + 1
        i += 1
    return None


def appended_query_refs(source: str) -> list[tuple[str, int]]:
    """Names appended by `Table.Combine({...})` as (name, 1-based line within source).

    Only list items that are a bare identifier naming no local binding are
    returned; other expressions (steps, function calls) are not references.
    Callers must still check the name against known queries (M is case-sensitive).
    """
    masked = _mask_m(source)
    local = {match.group(1).replace('""', '"') if match.group(1) is not None else match.group(2)
             for match in BOUND_NAME.finditer(masked)}
    refs: list[tuple[str, int]] = []
    for call in COMBINE_CALL.finditer(masked):
        items = _list_items(masked, call.end())
        if items is None:
            continue
        line = masked.count("\n", 0, call.start()) + 1
        for item in items:
            quoted = QUOTED_IDENTIFIER.fullmatch(item)
            if quoted:
                name = quoted.group(1).replace('""', '"')
            elif SIMPLE_IDENTIFIER.fullmatch(item):
                name = item
            else:
                continue
            if name not in local:
                refs.append((name, line))
    return refs


def m_string_literals(source: str) -> list[tuple[str, int]]:
    """M text literals as (value, 1-based line within source), skipping comments.

    `#"..."` quoted identifiers are names, not literals. Doubled quotes are escapes;
    M has no backslash escapes.
    """
    literals: list[tuple[str, int]] = []
    i, line = 0, 1
    while i < len(source):
        char = source[i]
        if char == "\n":
            line += 1
            i += 1
        elif source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = len(source) if end < 0 else end + 2
            line += source.count("\n", i, end)
            i = end
        elif char == '"' or source.startswith('#"', i):
            identifier = char == "#"
            start_line = line
            i += 2 if identifier else 1
            value = []
            while i < len(source):
                if source[i] == '"':
                    if source.startswith('""', i):
                        value.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                if source[i] == "\n":
                    line += 1
                value.append(source[i])
                i += 1
            if not identifier:
                literals.append(("".join(value), start_line))
        else:
            i += 1
    return literals
