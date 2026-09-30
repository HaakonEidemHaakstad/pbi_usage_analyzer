from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def clean_name(name: object | None) -> str | None:
    if name is None:
        return None
    value = str(name).strip()
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        value = value[1:-1].replace("''", "'")
    return value.strip()


def norm(value: object | None) -> str:
    cleaned = clean_name(value)
    return "" if cleaned is None else cleaned.casefold()


def norm_key(table: object | None, field: object | None) -> tuple[str, str]:
    return norm(table), norm(field)


def is_internal_table(table: str | None) -> bool:
    if not table:
        return False
    lowered = table.casefold()
    return lowered.startswith("localdatetable_") or lowered.startswith("datetabletemplate_")


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip())
