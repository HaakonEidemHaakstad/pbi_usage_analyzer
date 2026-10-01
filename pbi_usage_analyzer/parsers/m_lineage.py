"""Bounded, symbolic column demands for a deliberately small subset of M.

Unknown expressions fail closed: callers must retain query-level uncertainty.
No model schema is assumed complete, so removals remain symbolic exclusions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..util import norm
from .m_scalar_functions import SCALAR_ARITIES


@dataclass(frozen=True)
class ColumnDemand:
    included: frozenset[str] | None = None
    excluded: frozenset[str] = frozenset()

    required: frozenset[str] = frozenset()

    def union(self, other: ColumnDemand) -> ColumnDemand:
        merged = _union(self, other)
        return ColumnDemand(merged.included, merged.excluded, self.required | other.required)

    def accepts(self, name: str) -> bool:
        return norm(name) in self.required or self.feeds(name)

    def feeds(self, name: str) -> bool:
        """True when the column can flow into the demanded output (schema requirements aside)."""
        key = norm(name)
        return (self.included is None or key in self.included) and key not in self.excluded


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
            tokens.append(('quoted_identifier' if kind == 'identifier' else kind, value))
        elif source[i].isdecimal():
            match = re.match(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', source[i:])
            tokens.append(('number', match.group()))
            i += len(match.group())
        elif source[i:i + 2] in {'<=', '>=', '<>'}:
            tokens.append((source[i:i + 2], source[i:i + 2]))
            i += 2
        elif source[i] in '(){},=[]+-*/<>&':
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
        self.row_calls = set()

    def take(self, kind: str) -> str:
        actual, value = self.tokens[self.index]
        if actual != kind and not (kind == 'identifier' and actual == 'quoted_identifier'):
            raise _Unsupported()
        self.index += 1
        return value

    def at(self, kind: str) -> bool:
        return self.tokens[self.index][0] == kind

    def keyword(self, value: str) -> None:
        if self.tokens[self.index] != ('identifier', value):
            raise _Unsupported()
        self.index += 1

    def column_names(self, allow_single=False) -> tuple[str, ...]:
        if allow_single and self.at('string'):
            return (norm(self.take('string')),)
        self.take('{')
        names = []
        while not self.at('}'):
            names.append(norm(self.take('string')))
            if not self.at(','):
                break
            self.take(',')
        self.take('}')
        if not names or len(set(names)) != len(names):
            raise _Unsupported()
        return tuple(names)

    def row_expression(self, depth=0) -> frozenset[str]:
        """Collect reads from a closed scalar expression, never arbitrary M."""
        if depth > 80:
            raise _Unsupported()
        reads = self.row_atom(depth + 1)
        while self.tokens[self.index][0] not in {'string', 'quoted_identifier'} and self.tokens[self.index][1] in {
                '+', '-', '*', '/', '&', '=', '<>', '<', '>', '<=', '>=', 'and', 'or'}:
            self.index += 1
            reads |= self.row_atom(depth + 1)
        return reads

    def row_atom(self, depth) -> frozenset[str]:
        if depth > 80:
            raise _Unsupported()
        kind, value = self.tokens[self.index]
        if kind not in {'string', 'quoted_identifier'} and value in {'+', '-', 'not'}:
            self.index += 1
            return self.row_atom(depth + 1)
        if kind == '(':
            self.take('(')
            reads = self.row_expression(depth + 1)
            self.take(')')
            return reads
        if kind == '[':
            self.take('[')
            field = norm(self.take('identifier'))
            self.take(']')
            return frozenset({field})
        if kind == 'identifier' and value == 'if':
            self.index += 1
            reads = self.row_expression(depth + 1)
            self.keyword('then')
            reads |= self.row_expression(depth + 1)
            self.keyword('else')
            return reads | self.row_expression(depth + 1)
        if kind == 'identifier' and value in SCALAR_ARITIES:
            self.index += 1
            self.take('(')
            reads = frozenset()
            count = 0
            if not self.at(')'):
                while True:
                    reads |= self.row_expression(depth + 1)
                    count += 1
                    if not self.at(','):
                        break
                    self.take(',')
            self.take(')')
            if count not in SCALAR_ARITIES[value]:
                raise _Unsupported()
            self.row_calls.add(value)
            return reads
        if kind in {'number', 'string'} or (kind == 'identifier' and value in {'true', 'false', 'null'}):
            self.index += 1
            return frozenset()
        raise _Unsupported()

    def transformation_pairs(self, rename: bool):
        """Read literal rename/type pairs; reject dynamic expressions."""
        self.take('{')
        single = self.at('string')
        pairs = []
        type_refs = set()
        while not self.at('}'):
            if not single:
                self.take('{')
            column = norm(self.take('string'))
            self.take(',')
            if rename:
                value = norm(self.take('string'))
            else:
                value = self.take('identifier')
                if value == 'type':
                    value = self.take('identifier')
                    if value == 'nullable':
                        value = self.take('identifier')
                    if value not in {'any', 'number', 'text', 'date', 'time', 'datetime',
                                     'datetimezone', 'duration', 'logical', 'binary'}:
                        raise _Unsupported()
                elif value in {'Int64.Type', 'Int32.Type', 'Int16.Type', 'Int8.Type',
                               'Double.Type', 'Single.Type', 'Decimal.Type',
                               'Currency.Type', 'Percentage.Type'}:
                    type_refs.add(value)
                else:
                    raise _Unsupported()
            pairs.append((column, value))
            if single:
                break
            self.take('}')
            if not self.at(','):
                break
            self.take(',')
        self.take('}')
        old_names = [old for old, _ in pairs]
        if len(set(old_names)) != len(old_names):
            raise _Unsupported()
        if rename:
            new_names = [new for _, new in pairs]
            # Collisions and ordered rename chains require a known source schema.
            if len(set(new_names)) != len(new_names) or set(old_names) & set(new_names):
                raise _Unsupported()
        return pairs, type_refs

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
        if name in {'Table.Join', 'Table.NestedJoin'}:
            left = self.expression(depth + 1)
            self.take(',')
            left_keys = self.column_names(allow_single=True)
            self.take(',')
            right = self.expression(depth + 1)
            self.take(',')
            right_keys = self.column_names(allow_single=True)
            if len(left_keys) != len(right_keys):
                raise _Unsupported()
            nested = None
            if name == 'Table.NestedJoin':
                self.take(',')
                nested = norm(self.take('string'))
            join_kind = None
            if self.at(','):
                self.take(',')
                join_kind = self.take('identifier')
                if join_kind not in {'JoinKind.Inner', 'JoinKind.LeftOuter',
                                      'JoinKind.RightOuter', 'JoinKind.FullOuter'}:
                    raise _Unsupported()
            self.take(')')
            return ('join' if nested is None else 'nestedjoin', left, right,
                    frozenset(left_keys), frozenset(right_keys), nested, join_kind)
        if name == 'Table.ExpandTableColumn':
            upstream = self.expression(depth + 1)
            self.take(',')
            column = norm(self.take('string'))
            self.take(',')
            fields = self.column_names()
            outputs = fields
            if self.at(','):
                self.take(',')
                outputs = self.column_names()
            if len(fields) != len(outputs) or column in outputs:
                raise _Unsupported()
            self.take(')')
            return ('expand', upstream, column, fields, outputs)
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
        if name not in {'Table.SelectColumns', 'Table.RemoveColumns',
                        'Table.RenameColumns', 'Table.TransformColumnTypes',
                        'Table.SelectRows', 'Table.AddColumn'}:
            raise _Unsupported()
        upstream = self.expression(depth + 1)
        self.take(',')
        if name in {'Table.SelectRows', 'Table.AddColumn'}:
            added = None
            if name == 'Table.AddColumn':
                added = norm(self.take('string'))
                self.take(',')
            self.keyword('each')
            self.row_calls = set()
            reads = self.row_expression()
            calls = frozenset(self.row_calls)
            if added is not None and self.at(','):
                self.take(',')
                self.keyword('type')
                if not self.at('identifier'):
                    raise _Unsupported()
                column_type = self.take('identifier')
                if column_type == 'nullable':
                    if not self.at('identifier'):
                        raise _Unsupported()
                    column_type = self.take('identifier')
                if column_type not in {'any', 'number', 'text', 'date', 'time',
                                       'datetime', 'datetimezone', 'duration', 'logical', 'binary'}:
                    raise _Unsupported()
            self.take(')')
            return ('filter', upstream, reads, calls) if added is None else ('add', upstream, added, reads, calls)
        if name in {'Table.RenameColumns', 'Table.TransformColumnTypes'}:
            rename = name == 'Table.RenameColumns'
            pairs, type_refs = self.transformation_pairs(rename)
            ignore_missing = False
            if self.at(','):
                self.take(',')
                if rename:
                    if self.take('identifier') != 'MissingField.Ignore':
                        raise _Unsupported()
                    ignore_missing = True
                else:
                    self.take('string')  # Literal culture changes values, not lineage.
            self.take(')')
            return ('rename', upstream, pairs, ignore_missing) if rename else (
                'types', upstream, frozenset(column for column, _ in pairs), type_refs)
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


class ColumnLineage:
    """A parsed, supported M expression whose source demands can be evaluated
    for any output demand: all output columns, or a single output column."""

    def __init__(self, root, model_tables: dict[str, str], owner: str,
                 shared: dict[str, tuple | None] | None = None):
        self._root = root
        self._model_tables = model_tables
        self._owner = owner
        self._shared = shared or {}

    def demands(self, output: ColumnDemand = ColumnDemand()) -> dict[str, ColumnDemand] | None:
        """Source-column demands per referenced query, or None if evaluation fails."""
        try:
            return _evaluate(self._root, self._model_tables, self._owner, output, self._shared)
        except (_Unsupported, RecursionError):
            return None


def _parse(source: str):
    try:
        parser = _Parser(source)
        root = parser.expression()
        parser.take('end')
        return root
    except (_Unsupported, RecursionError):
        return None


def parse_shared_queries(sources: dict[str, str]) -> dict[str, tuple | None]:
    """Parse shared (load-disabled) queries by exact name; None marks unsupported M."""
    return {name: _parse(source) for name, source in sources.items()}


def parse_column_lineage(source: str, model_tables: dict[str, str], owner: str,
                         shared: dict[str, tuple | None] | None = None) -> ColumnLineage | None:
    """Return the lineage of a fully supported expression, or None when unproven.

    `shared` maps load-disabled query names to parsed roots (`parse_shared_queries`);
    references to them are traced through to the loaded tables they read.
    """
    root = _parse(source)
    if root is None:
        return None
    lineage = ColumnLineage(root, model_tables, owner, shared)
    return lineage if lineage.demands() is not None else None


def infer_column_demands(source: str, model_tables: dict[str, str], owner: str) -> dict[str, ColumnDemand] | None:
    """Return source-column demands for all outputs, or None when complete lineage is unproven."""
    lineage = parse_column_lineage(source, model_tables, owner)
    return None if lineage is None else lineage.demands()


def _evaluate(root, model_tables: dict[str, str], owner: str, output: ColumnDemand,
              shared: dict[str, tuple | None]) -> dict[str, ColumnDemand]:
    """Trace `output` backward to source demands; raise _Unsupported on unproven shapes."""
    result = {}
    active = set()
    remaining_visits = 10000

    def shadowed(name, scope):
        return name in scope or norm(name) in model_tables or name in shared

    def check_row_calls(calls, scope):
        if any(shadowed(name, scope) for name in calls):
            raise _Unsupported()

    def schema_demand(node, demand):
        kind = node[0]
        if kind == 'select':
            columns = node[2]
            selected = columns if demand.included is None else columns & demand.included
            return ColumnDemand(selected - demand.excluded, required=demand.required | (frozenset() if node[3] else columns))
        elif kind == 'remove':
            return ColumnDemand(demand.included, demand.excluded | node[2], demand.required | (frozenset() if node[3] else node[2]))
        elif kind == 'rename':
            inverse = {new: old for old, new in node[2]}
            old_names = frozenset(inverse.values())

            def back(names):
                mapped = frozenset(inverse.get(name, name) for name in names)
                # With Ignore, the old name may be absent and the new name
                # may already exist. Both possible origins remain protected.
                return mapped | names if node[3] else mapped

            included = None if demand.included is None else back(demand.included)
            excluded = frozenset(name for name in demand.excluded if name not in old_names)
            excluded = frozenset(inverse.get(name, name) for name in excluded)
            required = back(demand.required) | (frozenset() if node[3] else old_names)
            return ColumnDemand(included, excluded, required)

    def type_demand(node, demand, scope):
        symbols = {'Table.TransformColumnTypes'} | node[3]
        if any(shadowed(name, scope) for name in symbols):
            raise _Unsupported()
        return ColumnDemand(demand.included, demand.excluded, demand.required | node[2])

    def resolve_nested(node, scope, nested_name, demand, reads=frozenset(), depth=0):
        """Trace nested identity and left-side demands back to their join."""
        nonlocal remaining_visits
        remaining_visits -= 1
        if depth > 80 or remaining_visits < 0:
            raise _Unsupported()
        if node[0] == 'ref' and node[1] in scope:
            expression, binding_scope = scope[node[1]]
            return resolve_nested(expression, binding_scope, nested_name, demand, reads, depth + 1)
        if node[0] == 'let':
            nested = dict(scope)
            for name, expression in node[1].items():
                nested[name] = (expression, nested)
            return resolve_nested(node[2], nested, nested_name, demand, reads, depth + 1)
        if node[0] == 'filter':
            if shadowed('Table.SelectRows', scope):
                raise _Unsupported()
            check_row_calls(node[3], scope)
            return resolve_nested(node[1], scope, nested_name, demand, reads | node[2], depth + 1)
        if node[0] == 'types':
            if nested_name in node[2]:
                raise _Unsupported()
            return resolve_nested(node[1], scope, nested_name,
                                  type_demand(node, demand, scope), reads, depth + 1)
        if node[0] in {'select', 'remove', 'rename'}:
            intrinsic = {'select': 'Table.SelectColumns', 'remove': 'Table.RemoveColumns',
                         'rename': 'Table.RenameColumns'}[node[0]]
            if shadowed(intrinsic, scope):
                raise _Unsupported()
            if node[3] and shadowed('MissingField.Ignore', scope):
                raise _Unsupported()
            if node[0] == 'select' and nested_name not in node[2]:
                raise _Unsupported()
            if node[0] == 'remove' and nested_name in node[2]:
                raise _Unsupported()
            if node[0] == 'rename':
                inverse = {new: old for old, new in node[2]}
                # Ignore makes the origin of an affected nested name ambiguous.
                if nested_name in inverse.values() or (node[3] and nested_name in inverse):
                    raise _Unsupported()
                nested_name = inverse.get(nested_name, nested_name)
                mapped = frozenset(inverse.get(name, name) for name in reads)
                reads = mapped | reads if node[3] else mapped
            return resolve_nested(node[1], scope, nested_name,
                                  schema_demand(node, demand), reads, depth + 1)
        if node[0] != 'nestedjoin':
            raise _Unsupported()
        if shadowed('Table.NestedJoin', scope):
            raise _Unsupported()
        if node[6] and shadowed(node[6], scope):
            raise _Unsupported()
        if nested_name != node[5]:
            raise _Unsupported()
        return node, scope, demand, reads

    def visit(node, demand, scope, depth=0):
        nonlocal remaining_visits
        remaining_visits -= 1
        if depth > 80 or remaining_visits < 0:
            raise _Unsupported()
        kind = node[0]
        intrinsic = {'combine': 'Table.Combine', 'select': 'Table.SelectColumns',
                     'remove': 'Table.RemoveColumns', 'rename': 'Table.RenameColumns',
                     'types': 'Table.TransformColumnTypes', 'filter': 'Table.SelectRows',
                     'add': 'Table.AddColumn', 'join': 'Table.Join',
                     'nestedjoin': 'Table.NestedJoin', 'expand': 'Table.ExpandTableColumn'}.get(kind)
        if intrinsic and shadowed(intrinsic, scope):
            raise _Unsupported()
        if kind in {'select', 'remove', 'rename'} and node[3] and (
                shadowed('MissingField.Ignore', scope)):
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
            elif name in shared:
                # A load-disabled query: trace through it to the loaded tables it reads.
                key = ('shared', name)
                if shared[name] is None or key in active:
                    raise _Unsupported()
                active.add(key)
                visit(shared[name], demand, {}, depth + 1)
                active.remove(key)
            else:
                raise _Unsupported()
        elif kind == 'combine':
            for expression in node[1]:
                visit(expression, demand, scope, depth + 1)
        elif kind in {'select', 'remove', 'rename'}:
            visit(node[1], schema_demand(node, demand), scope, depth + 1)
        elif kind == 'types':
            visit(node[1], type_demand(node, demand, scope), scope, depth + 1)
        elif kind == 'filter':
            check_row_calls(node[3], scope)
            # Row membership depends on predicate columns regardless of output.
            visit(node[1], ColumnDemand(demand.included, demand.excluded,
                                       demand.required | node[2]), scope, depth + 1)
        elif kind == 'add':
            check_row_calls(node[4], scope)
            added = frozenset({node[2]})
            # A demanded added column flows from its generator reads.
            sources = node[3] if demand.feeds(node[2]) else frozenset()
            included = None if demand.included is None else (demand.included - added) | sources
            # Keep generator reads conservatively even if the output is dropped.
            visit(node[1], ColumnDemand(included, (demand.excluded - sources) | added,
                                       (demand.required - added) | node[3]), scope, depth + 1)
        elif kind in {'join', 'nestedjoin'}:
            if node[6] and shadowed(node[6], scope):
                raise _Unsupported()
            left_demand = demand
            right_demand = demand
            if kind == 'nestedjoin':
                generated = frozenset({node[5]})
                left_demand = ColumnDemand(
                    None if demand.included is None else demand.included - generated,
                    demand.excluded | generated, demand.required - generated)
                right_demand = ColumnDemand() if demand.accepts(node[5]) else ColumnDemand(frozenset())
            visit(node[1], ColumnDemand(left_demand.included, left_demand.excluded,
                                       left_demand.required | node[3]), scope, depth + 1)
            visit(node[2], ColumnDemand(right_demand.included, right_demand.excluded,
                                       right_demand.required | node[4]), scope, depth + 1)
        elif kind == 'expand':
            generated = frozenset(node[4]) | {node[2]}
            left_demand = ColumnDemand(
                None if demand.included is None else demand.included - generated,
                demand.excluded | generated, demand.required - generated)
            joined, join_scope, left_demand, filter_reads = resolve_nested(
                node[1], scope, node[2], left_demand)
            nested = frozenset({joined[5]})
            left_demand = ColumnDemand(
                None if left_demand.included is None else left_demand.included - nested,
                left_demand.excluded | nested,
                (left_demand.required | filter_reads) - nested | joined[3])
            # Every expanded name remains a schema requirement, even when
            # a later projection drops its output alias. Expansion also
            # depends on matching rows, so both join keys always survive.
            fed = frozenset(name for name, alias in zip(node[3], node[4]) if demand.feeds(alias))
            right_demand = ColumnDemand(fed, required=joined[4] | frozenset(node[3]))
            if joined[5] in filter_reads:
                right_demand = ColumnDemand(required=joined[4] | frozenset(node[3]))
            visit(joined[1], left_demand, join_scope, depth + 1)
            visit(joined[2], right_demand, join_scope, depth + 1)

    visit(root, output, {})
    return result
