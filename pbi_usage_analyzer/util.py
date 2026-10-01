from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path):
    # json rejects a leading byte-order mark; utf-8-sig tolerates one.
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def read_source_text(path: Path) -> tuple[str, bool]:
    """Read a UTF-8 source file, tolerating a BOM and undecodable bytes.

    Returns the text and whether invalid bytes were replaced with U+FFFD, so one
    damaged file cannot abort the analysis. Callers report replacement.
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        return data.decode("utf-8-sig", errors="replace"), True


def clean_name(name: object | None) -> str | None:
    if name is None:
        return None
    value = str(name).strip()
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        # Whitespace inside quotes is part of the display name (e.g. ' Country'
        # from a CSV header); only matching keys (norm) trim it.
        value = value[1:-1].replace("''", "'")
    return value


def norm(value: object | None) -> str:
    cleaned = clean_name(value)
    return "" if cleaned is None else cleaned.strip().casefold()


def norm_key(table: object | None, field: object | None) -> tuple[str, str]:
    return norm(table), norm(field)


def is_internal_table(table: str | None) -> bool:
    if not table:
        return False
    lowered = table.casefold()
    return lowered.startswith("localdatetable_") or lowered.startswith("datetabletemplate_")


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip())
