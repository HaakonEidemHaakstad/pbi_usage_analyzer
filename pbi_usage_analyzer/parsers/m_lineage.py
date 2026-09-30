"""Bounded, symbolic column demands for a deliberately small subset of M.

Unknown expressions fail closed: callers must retain query-level uncertainty.
No model schema is assumed complete, so removals remain symbolic exclusions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..util import norm


@dataclass(frozen=True)
class ColumnDemand:
    included: frozenset[str] | None = None
    excluded: frozenset[str] = frozenset()

    required: frozenset[str] = frozenset()

    def union(self, other: ColumnDemand) -> ColumnDemand:
        merged = _union(self, other)
        return ColumnDemand(merged.included, merged.excluded, self.required | other.required)

    def accepts(self, name: str) -> bool:
        key = norm(name)
        return key in self.required or ((self.included is None or key in self.included) and key not in self.excluded)


def _union(left: ColumnDemand, right: ColumnDemand) -> ColumnDemand:
    if left.included is None and right.included is None:
        return ColumnDemand(None, left.excluded & right.excluded)
    if left.included is None:
        return ColumnDemand(None, left.excluded - (right.included - right.excluded))
    if right.included is None:
        return _union(right, left)
    return ColumnDemand((left.included - left.excluded) | (right.included - right.excluded))


class _Unsupported(ValueError):
    pass


def _tokens(source: str) -> list[tuple[str, str]]:
    tokens = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
        elif source.startswith('//', i):
            end = source.find('\n', i)
            i = len(source) if end < 0 else end + 1
        elif source.startswith('/*', i):
            i += 2
            depth = 1
            while i < len(source) and depth:
                if source.startswith('/*', i):
                    depth += 1
                    i += 2
                elif source.startswith('*/', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise _Unsupported()
        elif source[i] == '"' or source.startswith('#"', i):
            kind = 'identifier' if source[i] == '#' else 'string'
            i += 2 if kind == 'identifier' else 1
            value = ''
            while i < len(source):
                if source.startswith('""', i):
                    value += '"'
                    i += 2
                elif source[i] == '"':
                    i += 1
                    break
                else:
                    # M escape sequences require additional decoding. Reject them.
                    if source.startswith('#(', i):
                        raise _Unsupported()
                    value += source[i]
                    i += 1
            else:
                raise _Unsupported()
            tokens.append((kind, value))
        elif source[i] in '(){},=':
            tokens.append((source[i], source[i]))
            i += 1
        else:
            match = re.match(r'[^\W\d]\w*(?:\.[^\W\d]\w*)*', source[i:], re.UNICODE)
            if not match:
                raise _Unsupported()
            value = match.group()
            tokens.append((value if value in {'let', 'in'} else 'identifier', value))
            i += len(value)
        if len(tokens) > 10000:
            raise _Unsupported()
    return tokens + [('end', '')]


class _Parser:
    def __init__(self, source: str):
        self.tokens = _tokens(source)
        self.index = 0

    def take(self, kind: str) -> str:
        actual, value = self.tokens[self.index]
        if actual != kind:
            raise _Unsupported()
        self.index += 1
        return value

    def at(self, kind: str) -> bool:
        return self.tokens[self.index][0] == kind

    def expression(self, depth: int = 0):
        if depth > 80:
            raise _Unsupported()
        if self.at('let'):
            self.take('let')
            bindings = {}
            while True:
                name = self.take('identifier')
                if name in bindings or name in {'Table.SelectColumns', 'Table.RemoveColumns', 'Table.Combine', 'MissingField.Ignore'}:
                    raise _Unsupported()
                self.take('=')
                bindings[name] = self.expression(depth + 1)
                if not self.at(','):
                    break
                self.take(',')
            self.take('in')
            return ('let', bindings, self.expression(depth + 1))
        if self.at('('):
            self.take('(')
            expression = self.expression(depth + 1)
            self.take(')')
            return expression
        name = self.take('identifier')
        if not self.at('('):
            return ('ref', name)
        self.take('(')
        if name == 'Table.Combine':
            self.take('{')
            inputs = []
            if not self.at('}'):
                while True:
                    inputs.append(self.expression(depth + 1))
                    if not self.at(','):
                        break
                    self.take(',')
            self.take('}')
            self.take(')')
            return ('combine', inputs)
        if name not in {'Table.SelectColumns', 'Table.RemoveColumns'}:
            raise _Unsupported()
        upstream = self.expression(depth + 1)
        self.take(',')
        self.take('{')
        columns = set()
        if not self.at('}'):
            while True:
                columns.add(norm(self.take('string')))
                if not self.at(','):
                    break
                self.take(',')
        self.take('}')
        ignore_missing = False
        if self.at(','):
            self.take(',')
            if self.take('identifier') != 'MissingField.Ignore':
                raise _Unsupported()
            ignore_missing = True
        self.take(')')
        return ('select' if name == 'Table.SelectColumns' else 'remove', upstream, frozenset(columns), ignore_missing)


def infer_column_demands(source: str, model_tables: dict[str, str], owner: str) -> dict[str, ColumnDemand] | None:
    """Return source-column demands, or None when complete lineage is unproven."""
    try:
        parser = _Parser(source)
        root = parser.expression()
        parser.take('end')
        result = {}
        active = set()
        remaining_visits = 10000

        def visit(node, demand, scope, depth=0):
            nonlocal remaining_visits
            remaining_visits -= 1
            if depth > 80 or remaining_visits < 0:
                raise _Unsupported()
            kind = node[0]
            intrinsic = {'combine': 'Table.Combine', 'select': 'Table.SelectColumns',
                         'remove': 'Table.RemoveColumns'}.get(kind)
            if intrinsic and (intrinsic in scope or norm(intrinsic) in model_tables):
                raise _Unsupported()
            if kind in {'select', 'remove'} and node[3] and (
                    'MissingField.Ignore' in scope or norm('MissingField.Ignore') in model_tables):
                raise _Unsupported()
            if kind == 'let':
                nested = dict(scope)
                for name, expression in node[1].items():
                    nested[name] = (expression, nested)
                visit(node[2], demand, nested, depth + 1)
            elif kind == 'ref':
                name = node[1]
                if name in scope:
                    expression, binding_scope = scope[name]
                    key = (id(binding_scope), name)
                    if key in active:
                        raise _Unsupported()
                    active.add(key)
                    visit(expression, demand, binding_scope, depth + 1)
                    active.remove(key)
                elif norm(name) in model_tables and norm(name) != norm(owner):
                    table = model_tables[norm(name)]
                    result[table] = result[table].union(demand) if table in result else demand
                else:
                    raise _Unsupported()
            elif kind == 'combine':
                for expression in node[1]:
                    visit(expression, demand, scope, depth + 1)
            elif kind == 'select':
                columns = node[2]
                selected = columns if demand.included is None else columns & demand.included
                visit(node[1], ColumnDemand(selected - demand.excluded, required=demand.required | (frozenset() if node[3] else columns)), scope, depth + 1)
            elif kind == 'remove':
                visit(node[1], ColumnDemand(demand.included, demand.excluded | node[2], demand.required | (frozenset() if node[3] else node[2])), scope, depth + 1)

        visit(root, ColumnDemand(), {})
        return result
    except (_Unsupported, RecursionError):
        return None
