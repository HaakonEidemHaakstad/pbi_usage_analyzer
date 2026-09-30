"""Bounded DAX lexical masking shared by ordinary and special DAX extraction."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaskedDax:
    """Expression with strings/comments blanked; offsets and line breaks are unchanged."""
    text: str
    unterminated: str | None = None
    unterminated_offset: int | None = None


def mask_dax(expression: str, *, keep_unterminated: bool = False) -> MaskedDax:
    """Blank DAX strings and comments while preserving quoted/bracketed identifiers.

    An unterminated string or block comment is reported. By default it is masked
    to the end of the input; with ``keep_unterminated`` its text is left intact so
    callers that must stay conservative do not lose dependency evidence.
    """
    out = list(expression)
    i = 0
    while i < len(expression):
        start = i
        char = expression[i]
        unterminated = None
        if char in "'[":
            end = "'" if char == "'" else ']'
            i += 1
            while i < len(expression):
                if expression[i] == end:
                    i += 1
                    if i < len(expression) and expression[i] == end:
                        i += 1
                        continue
                    break
                i += 1
            continue
        if char == '"':
            i += 1
            unterminated = 'string'
            while i < len(expression):
                if expression[i] == '"':
                    i += 1
                    if i < len(expression) and expression[i] == '"':
                        i += 1
                        continue
                    unterminated = None
                    break
                i += 1
        elif expression.startswith('//', i) or expression.startswith('--', i):
            end = expression.find('\n', i)
            i = len(expression) if end < 0 else end
        elif expression.startswith('/*', i):
            end = expression.find('*/', i + 2)
            if end < 0:
                unterminated = 'block comment'
                i = len(expression)
            else:
                i = end + 2
        else:
            i += 1
            continue
        if unterminated:
            if not keep_unterminated:
                _blank(out, start, i)
            return MaskedDax(''.join(out), unterminated, start)
        _blank(out, start, i)
    return MaskedDax(''.join(out))


def mask_dax_literals(expression: str) -> str:
    """Remove strings/comments while preserving quoted identifiers and line breaks."""
    return mask_dax(expression).text


def _blank(out: list[str], start: int, end: int) -> None:
    for position in range(start, end):
        if out[position] not in '\r\n':
            out[position] = ' '
