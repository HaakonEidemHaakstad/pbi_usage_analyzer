from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..model import ModelObject, ObjectRef, ObjectType
from ..util import clean_name, indentation

TABLE_HEADER = re.compile(r"^\s*table\s+(.+?)\s*$", re.I)
COLUMN_HEADER = re.compile(r"^(\s*)column\s+(.+?)\s*$", re.I)
MEASURE_HEADER = re.compile(r"^(\s*)measure\s+(.+?)\s*$", re.I)
HIERARCHY_HEADER = re.compile(r"^(\s*)hierarchy\s+(.+?)\s*$", re.I)

PROPERTY_PREFIXES = (
    "dataType:", "formatString:", "lineageTag:", "summarizeBy:", "sourceColumn:",
    "displayFolder:", "description:", "dataCategory:", "sortByColumn:", "changedProperty",
    "annotation ", "variation ", "hierarchy ", "partition ", "isHidden",
)


@dataclass
class TmdlModel:
    objects: list[ModelObject] = field(default_factory=list)
    hierarchies: dict[ObjectRef, set[ObjectRef]] = field(default_factory=dict)
    table_files: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


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
    for line in block:
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
            if stripped.startswith(PROPERTY_PREFIXES) or ": " in stripped or stripped.endswith(":"):
                break
        out.append(stripped)
    return "\n".join(out).strip()


def parse_table_file(path: Path) -> tuple[list[ModelObject], dict[ObjectRef, set[ObjectRef]]]:
    text = path.read_text(encoding="utf-8")
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
    hierarchies: dict[ObjectRef, set[ObjectRef]] = {}
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
            cols: set[ObjectRef] = set()
            for bl in block:
                stripped = bl.strip()
                if stripped.startswith("column:"):
                    col = clean_name(stripped.split(":", 1)[1].strip()) or ""
                    cols.add(ObjectRef(ObjectType.COLUMN, table, col))
            hierarchies[href] = cols
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
    for path in sorted(tables_folder.glob("*.tmdl")):
        try:
            objects, hierarchies = parse_table_file(path)
            result.objects.extend(objects)
            result.hierarchies.update(hierarchies)
            for obj in objects:
                if obj.ref.object_type == ObjectType.TABLE:
                    result.table_files[obj.ref.table] = path
        except Exception as exc:
            result.warnings.append(f"Could not parse {path.name}: {exc}")
    return result
