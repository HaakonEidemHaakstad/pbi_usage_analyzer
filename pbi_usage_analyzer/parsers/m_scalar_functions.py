"""Explicit scalar functions whose dependencies are confined to their arguments.

Only these arities are supported. Comparers, culture options, rounding modes,
callbacks, and dynamic calls require additional semantics and remain unknown.
This registry describes dependency behavior, not runtime type validation.
"""

from types import MappingProxyType


SCALAR_ARITIES = MappingProxyType({
    "Text.Contains": frozenset({2}),
    "Text.StartsWith": frozenset({2}),
    "Text.EndsWith": frozenset({2}),
    "Text.Lower": frozenset({1}),
    "Text.Upper": frozenset({1}),
    "Text.Trim": frozenset({1}),
    "Text.Length": frozenset({1}),
    "Text.Replace": frozenset({3}),
    "Text.From": frozenset({1}),
    "Number.Abs": frozenset({1}),
    "Number.Round": frozenset({1, 2}),
    "Number.From": frozenset({1}),
    "Date.Year": frozenset({1}),
    "Date.Month": frozenset({1}),
    "Date.Day": frozenset({1}),
    "Date.From": frozenset({1}),
})
