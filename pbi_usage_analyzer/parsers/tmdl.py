from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..diagnostics import Diagnostic, DiagnosticCollection, DiagnosticSeverity
from ..model import ModelObject, ObjectRef, ObjectType
from ..util import clean_name, indentation, read_source_text
from .dax_lexer import mask_dax_literals

TABLE_HEADER = re.compile(r"^\s*table\s+(.+?)\s*$", re.I)
COLUMN_HEADER = re.compile(r"^(\s*)column\s+(.+?)\s*$", re.I)
MEASURE_HEADER = re.compile(r"^(\s*)measure\s+(.+?)\s*$", re.I)
HIERARCHY_HEADER = re.compile(r"^(\s*)hierarchy\s+(.+?)\s*$", re.I)

PROPERTY_PREFIXES = (
    "dataType:", "formatString:", "lineageTag:", "summarizeBy:", "sourceColumn:",
    "displayFolder:", "description:", "dataCategory:", "sortByColumn:", "changedProperty",
    "annotation ", "variation ", "hierarchy ", "partition ", "isHidden",
    "extendedProperty ", "formatStringDefinition",
)
# A TMDL property begins its line with `name:`. DAX has no such syntax, but DAX
# strings/comments can contain colons, so the check runs on masked text.
PROPERTY_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9]*\s*:")


@dataclass
class TmdlModel(DiagnosticCollection):
    objects: list[ModelObject] = field(default_factory=list)
    # Level columns in declaration order (deterministic evidence/export order).
    hierarchies: dict[ObjectRef, tuple[ObjectRef, ...]] = field(default_factory=dict)
    table_files: dict[str, Path] = field(default_factory=dict)
    failed_files: list[Path] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def split_object_definition(text: str) -> tuple[str, bool, str]:
    text = text.strip()
    in_quote = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "'":
            if in_quote and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_quote = not in_quote
        elif char == "=" and not in_quote:
            return clean_name(text[:i]) or "", True, text[i + 1:].strip()
        i += 1
    return clean_name(text) or "", False, ""


def get_object_block(lines: list[str], start_index: int, base_indent: int) -> tuple[list[str], int]:
    block: list[str] = []
    i = start_index + 1
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            block.append(line)
            i += 1
            continue
        if indentation(line) <= base_indent:
            break
        block.append(line)
        i += 1
    return block, i


def extract_expression(inline_expression: str, block: list[str], base_indent: int) -> str:
    inline_expression = inline_expression.strip()
    if inline_expression and inline_expression != "```":
        return inline_expression

    out: list[str] = []
    inside_fence = inline_expression == "```"
    masked_lines = mask_dax_literals("\n".join(block)).split("\n")
    for line, masked in zip(block, masked_lines):
        stripped = line.strip()
        if not stripped:
            continue
        current_indent = indentation(line)
        if stripped == "```":
            if inside_fence:
                break
            inside_fence = True
            continue
        if inside_fence:
            out.append(stripped)
            continue
        if current_indent <= base_indent + 8:
            masked = masked.strip()
            if masked.startswith(PROPERTY_PREFIXES) or PROPERTY_LINE.match(masked):
                break
        out.append(stripped)
    return "\n".join(out).strip()


def measure_description(lines: list[str], index: int, block: list[str]) -> str | None:
    """Read adjacent TMDL description comments; unknown alternate syntax is skipped."""
    descriptions = []
    preceding = index - 1
    while preceding >= 0:
        line = lines[preceding]
        if indentation(line) != indentation(lines[index]) or not line.strip().startswith("///"):
            break
        descriptions.append(line.strip()[3:].strip())
        preceding -= 1
    if descriptions:
        return "\n".join(reversed(descriptions))
    # Do not report missing documentation when an alternate description form
    # exists but its value has not been parsed confidently.
    if any(line.strip().startswith("description:") for line in block):
        return None
    return ""


def parse_table_file(path: Path) -> tuple[list[ModelObject], dict[ObjectRef, tuple[ObjectRef, ...]]]:
    text, _ = read_source_text(path)
    lines = text.splitlines()
    table = None
    for line in lines:
        m = TABLE_HEADER.match(line)
        if m:
            table = clean_name(m.group(1))
            break
    if not table:
        return [], {}

    objects: list[ModelObject] = []
    hierarchies: dict[ObjectRef, tuple[ObjectRef, ...]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        mm = MEASURE_HEADER.match(line)
        if mm:
            base_indent = len(mm.group(1))
            name, has_expression, inline = split_object_definition(mm.group(2))
            block, next_i = get_object_block(lines, i, base_indent)
            expression = extract_expression(inline, block, base_indent) if has_expression else ""
            objects.append(ModelObject(
                ref=ObjectRef(ObjectType.MEASURE, table, name),
                source_file=str(path),
                calculated=True,
                expression=expression,
                description=measure_description(lines, i, block),
                source_line=i + 1,
            ))
            i = next_i
            continue

        mc = COLUMN_HEADER.match(line)
        if mc:
            base_indent = len(mc.group(1))
            name, calculated, inline = split_object_definition(mc.group(2))
            block, next_i = get_object_block(lines, i, base_indent)
            expression = extract_expression(inline, block, base_indent) if calculated else ""
            hidden = False
            sort_by = None
            source_column = None
            data_type = None
            for bl in block:
                stripped = bl.strip()
                if stripped == "isHidden":
                    hidden = True
                elif stripped.startswith("sortByColumn:"):
                    sort_by = clean_name(stripped.split(":", 1)[1].strip())
                elif stripped.startswith("sourceColumn:"):
                    source_column = clean_name(stripped.split(":", 1)[1].strip())
                elif stripped.startswith("dataType:"):
                    data_type = stripped.split(":", 1)[1].strip()
            objects.append(ModelObject(
                ref=ObjectRef(ObjectType.COLUMN, table, name),
                source_file=str(path),
                hidden=hidden,
                calculated=calculated,
                source_column=source_column,
                data_type=data_type,
                expression=expression,
                source_line=i + 1,
                sort_by_column=sort_by,
            ))
            i = next_i
            continue

        mh = HIERARCHY_HEADER.match(line)
        if mh:
            base_indent = len(mh.group(1))
            name = clean_name(mh.group(2)) or ""
            block, next_i = get_object_block(lines, i, base_indent)
            href = ObjectRef(ObjectType.HIERARCHY, table, name)
            cols: dict[ObjectRef, None] = {}
            for bl in block:
                stripped = bl.strip()
                if stripped.startswith("column:"):
                    col = clean_name(stripped.split(":", 1)[1].strip()) or ""
                    cols[ObjectRef(ObjectType.COLUMN, table, col)] = None
            hierarchies[href] = tuple(cols)
            objects.append(ModelObject(ref=href, source_file=str(path)))
            i = next_i
            continue
        i += 1

    objects.append(ModelObject(ref=ObjectRef(ObjectType.TABLE, table), source_file=str(path)))
    return objects, hierarchies


def parse_model(model_folder: Path) -> TmdlModel:
    definition = model_folder / "definition"
    tables_folder = definition / "tables"
    if not tables_folder.exists():
        raise FileNotFoundError(f"TMDL tables folder not found: {tables_folder}")

    result = TmdlModel()
    for path in sorted(definition.rglob("*.tmdl")):
        if read_source_text(path)[1]:
            result.diagnostics.append(Diagnostic(
                "TMDL_DECODE_REPLACED", DiagnosticSeverity.WARNING,
                f"{path.name} is not valid UTF-8; undecodable bytes were replaced. "
                "References containing them cannot be resolved.", source_file=str(path)))
    for path in sorted(tables_folder.glob("*.tmdl")):
        try:
            objects, hierarchies = parse_table_file(path)
            result.objects.extend(objects)
            result.hierarchies.update(hierarchies)
            for obj in objects:
                if obj.ref.object_type == ObjectType.TABLE:
                    result.table_files[obj.ref.table] = path
        except Exception as exc:
            result.failed_files.append(path)
            result.diagnostics.append(Diagnostic(
                "TMDL_PARSE_FAILED", DiagnosticSeverity.WARNING,
                f"Could not parse {path.name}: {exc}", source_file=str(path)))
    return result
