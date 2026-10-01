"""Bounded DAX lexical masking shared by ordinary and special DAX extraction."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MaskedDax:
    """Expression with strings/comments blanked; offsets and line breaks are unchanged."""
    text: str
    unterminated: str | None = None
    unterminated_offset: int | None = None


# Alternation order matches DAX precedence at a position: identifiers, strings,
# line comments (`//` before `/*`), block comments. A doubled quote/bracket is an
# escape; an optional closing delimiter lets unterminated tokens run to the end.
_TOKEN = re.compile(r"""
    (?P<identifier>'(?:[^']|'')*'?|\[(?:[^\]]|\]\])*\]?)
  | (?P<string>"(?:[^"]|"")*(?P<closed>"?))
  | (?P<line>//[^\n]*|--[^\n]*)
  | (?P<block>/\*(?:.*?(?P<block_end>\*/)|.*))
""", re.S | re.X)
_NOT_NEWLINE = re.compile(r"[^\r\n]")


def mask_dax(expression: str, *, keep_unterminated: bool = False) -> MaskedDax:
    """Blank DAX strings and comments while preserving quoted/bracketed identifiers.

    An unterminated string or block comment is reported. By default it is masked
    to the end of the input; with ``keep_unterminated`` its text is left intact so
    callers that must stay conservative do not lose dependency evidence.
    """
    pieces: list[str] = []
    position = 0
    for match in _TOKEN.finditer(expression):
        kind = match.lastgroup
        if kind == "identifier":
            continue
        unterminated = None
        if kind == "string" and not match.group("closed"):
            unterminated = "string"
        elif kind == "block" and not match.group("block_end"):
            unterminated = "block comment"
        pieces.append(expression[position:match.start()])
        if unterminated and keep_unterminated:
            pieces.append(match.group())
        else:
            pieces.append(_NOT_NEWLINE.sub(" ", match.group()))
        position = match.end()
        if unterminated:
            pieces.append(expression[position:])
            return MaskedDax("".join(pieces), unterminated, match.start())
    pieces.append(expression[position:])
    return MaskedDax("".join(pieces))


_SIMPLE_TABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SPACE_BY_SYMBOL = re.compile(r" (?=\W)|(?<=\W) ")


def _normalize_plain(text: str) -> str:
    text = " ".join(text.split()).casefold()
    return _SPACE_BY_SYMBOL.sub("", text)


def normalize_dax(expression: str) -> str | None:
    """Comparison key for DAX that differs only lexically, or None if unterminated.

    Comments are removed, whitespace is collapsed, and keywords, functions and
    object names compare case-insensitively (as DAX resolves them); `'Sales'`
    equals `Sales`. String literals stay exact.
    """
    parts: list[str] = []
    plain: list[str] = []
    position = 0

    def flush():
        parts.append(_normalize_plain("".join(plain)))
        plain.clear()

    for match in _TOKEN.finditer(expression):
        plain.append(expression[position:match.start()])
        position = match.end()
        token = match.group()
        kind = match.lastgroup
        if kind in {"line", "block"}:
            if kind == "block" and not match.group("block_end"):
                return None
            plain.append(" ")
            continue
        if kind == "string" and not match.group("closed"):
            return None
        flush()
        if kind == "string":
            parts.append(token)
        elif token.startswith("'"):
            if len(token) < 2 or not token.endswith("'"):
                return None
            name = token[1:-1].replace("''", "'").strip().casefold()
            parts.append(name if _SIMPLE_TABLE.fullmatch(name) else "'" + name.replace("'", "''") + "'")
        else:
            if not token.endswith("]"):
                return None
            parts.append("[" + token[1:-1].strip().casefold() + "]")
    plain.append(expression[position:])
    flush()
    return "".join(parts)


def mask_dax_literals(expression: str) -> str:
    """Remove strings/comments while preserving quoted identifiers and line breaks."""
    return mask_dax(expression).text
