#!/usr/bin/env python3
"""Bounded, local Python syntax graphs. Static edges are not execution proof."""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import tokenize

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 512 * 1024
MAX_NODES = 20000
MAX_EDGES = 30000
MAX_UNRESOLVED = 20000
MAX_CALLS = 50000
MAX_SNAPSHOT = 32 * 1024 * 1024
KINDS = {'file', 'class', 'function', 'async_function'}
EDGE_KINDS = {'contains', 'imports', 'calls'}
SKIP_DIRS = {'node_modules', 'data', 'logs', 'runtime', 'private', 'secrets', 'credentials',
             'dist', 'build', 'venv', 'env', '__pycache__', 'site-packages', 'reports', 'exports', 'cache', 'tests', 'test', '__tests__'}
SKIP_FILES = {'config.py', 'settings.py', 'local_settings.py', 'secrets.py', 'credentials.py', 'keys.py'}


class GraphError(ValueError):
    pass


def identifier(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def clean_text(value, limit=600):
    value = value if isinstance(value, str) else ''
    value = re.sub(r'(?:/(?:Users|home)/[^\s"\'<>]+|[A-Za-z]:[\\/]Users[\\/][^\s"\'<>]+)', '[private path]', value)
    value = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})\b', '[credential]', value)
    value = re.sub(r'(?i)\b(api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*["\']?[^\s"\']{8,}', r'\1=[credential]', value)
    return value.strip()[:limit]


def relative_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\0' in value:
        raise GraphError('invalid relative source path')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in {'', '.', '..'} or ':' in x for x in value.split('/')):
        raise GraphError('source paths must stay relative')
    if p.suffix != '.py' or any(x.startswith('.') for x in p.parts):
        raise GraphError('source paths must name visible Python files')
    return value


def atomic_json(path, value):
    path = Path(path)
    if path.suffix != '.json':
        raise GraphError('graph output must use a .json extension')
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(encoded) > MAX_SNAPSHOT:
        raise GraphError('graph snapshot exceeds size limit; reduce indexing limits')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise GraphError('output cannot be symbolic')
    fd, temporary = tempfile.mkstemp(prefix='.graph-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, limit=MAX_SNAPSHOT):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise GraphError('missing, symbolic or oversized JSON')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise GraphError('JSON exceeds size limit')
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(GraphError('non-finite JSON')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GraphError('invalid JSON') from exc


def _positive(value, maximum=10000000):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum


def _hex(value, size):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is not None


def _validate_snapshot(raw):
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw.get('schema_version') != 1 or raw.get('module_id') != 'coding-graph' or raw.get('mode') not in {'live', 'demo'}:
        raise GraphError('unsupported graph snapshot')
    try:
        when = datetime.fromisoformat(raw['generated_at'].replace('Z', '+00:00'))
        if when.tzinfo is None:
            raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise GraphError('snapshot needs a timezone-aware observation time') from None
    base = raw.get('codebase')
    if (not isinstance(base, dict) or not isinstance(base.get('label'), str)
            or not isinstance(base.get('partial'), bool) or not isinstance(base.get('warnings'), list)
            or len(base['warnings']) > 1000 or any(not isinstance(w, str) or len(w) > 400 for w in base['warnings'])
            or not _hex(base.get('fingerprint'), 64)):
        raise GraphError('invalid codebase metadata')
    for key, limit in [('files', 5000), ('nodes', MAX_NODES), ('edges', MAX_EDGES), ('unresolved', MAX_UNRESOLVED)]:
        if not isinstance(raw.get(key), list) or len(raw[key]) > limit:
            raise GraphError('invalid or oversized graph collection: ' + key)
    paths = set()
    for f in raw['files']:
        if (not isinstance(f, dict) or relative_path(f.get('path')) in paths
                or not _hex(f.get('sha256'), 64)
                or not isinstance(f.get('size'), int) or isinstance(f['size'], bool) or not 0 <= f['size'] <= MAX_FILE):
            raise GraphError('invalid source manifest')
        paths.add(f['path'])
    if type(base.get('file_count')) is not int or base.get('file_count') != len(paths):
        raise GraphError('source manifest count mismatch')
    expected_fingerprint = hashlib.sha256(json.dumps(raw['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if base['fingerprint'] != expected_fingerprint:
        raise GraphError('source manifest fingerprint mismatch')
    ids = set()
    for n in raw['nodes']:
        if (not isinstance(n, dict) or not isinstance(n.get('id'), str) or not re.fullmatch('[0-9a-f]{24}', n['id'])
                or n['id'] in ids or n.get('kind') not in KINDS or n.get('file') not in paths
                or not _positive(n.get('line')) or not _positive(n.get('end_line')) or n['end_line'] < n['line']
                or any(not isinstance(n.get(k), str) or len(n[k]) > m for k, m in [('name', 500), ('qualname', 2000), ('docstring', 600)])):
            raise GraphError('invalid graph node')
        ids.add(n['id'])
    edge_ids = set()
    for e in raw['edges']:
        if (not isinstance(e, dict) or not isinstance(e.get('id'), str) or not re.fullmatch('[0-9a-f]{24}', e['id'])
                or e['id'] in edge_ids or e.get('source') not in ids or e.get('target') not in ids
                or e.get('kind') not in EDGE_KINDS or e.get('confidence') not in {'syntax', 'static_resolved'}
                or e.get('file') not in paths or not _positive(e.get('line'))):
            raise GraphError('invalid graph edge')
        edge_ids.add(e['id'])
    for u in raw['unresolved']:
        if (not isinstance(u, dict) or u.get('source') not in ids or u.get('file') not in paths or not _positive(u.get('line'))
                or any(not isinstance(u.get(k), str) or len(u[k]) > m for k, m in [('expression', 300), ('reason', 100)])):
            raise GraphError('invalid unresolved call')
    return raw


def validate_snapshot(raw):
    try:
        return _validate_snapshot(raw)
    except (TypeError, KeyError, AttributeError, OverflowError):
        raise GraphError('invalid graph snapshot field types') from None


@dataclass
class Scope:
    node_id: str
    kind: str
    file: str
    module: str
    qualname: str
    parent: object = None
    bindings: dict = field(default_factory=dict)
    dynamic: set = field(default_factory=set)
    blocked: bool = False

    def bind(self, name, value):
        self.bindings.setdefault(name, []).append(value)


class GraphBuilder:
    def __init__(self, label, mode='live'):
        self.label, self.mode = clean_text(label, 200), mode
        self.nodes, self.edges, self.unresolved, self.files = [], [], [], []
        self.modules, self.module_scopes, self.scopes = {}, {}, {}
        self.calls, self.imports = [], []
        self.partial, self.warnings, self.edge_keys = False, [], set()

    def warn(self, message):
        self.partial = True
        if len(self.warnings) < 1000 and message not in self.warnings:
            self.warnings.append(clean_text(message, 400))

    def node(self, kind, name, qualname, file, line, end_line, docstring=''):
        if len(self.nodes) >= MAX_NODES:
            raise GraphError('node_limit')
        n = {'id': identifier(kind, file, qualname, line), 'kind': kind, 'name': name[:500],
             'qualname': qualname[:2000], 'file': file, 'line': line, 'end_line': max(line, end_line),
             'docstring': clean_text(docstring)}
        self.nodes.append(n)
        return n

    def edge(self, source, target, kind, file, line, confidence='syntax'):
        key = (source, target, kind, file, line)
        if key in self.edge_keys:
            return
        if len(self.edges) >= MAX_EDGES:
            self.warn('edge_limit: additional edges omitted')
            return
        self.edge_keys.add(key)
        self.edges.append({'id': identifier(*key), 'source': source, 'target': target, 'kind': kind,
                           'confidence': confidence, 'file': file, 'line': line})

    def add_source(self, path, raw):
        path = relative_path(path)
        if len(raw) > MAX_FILE:
            self.warn(path + ': file_size_limit')
            return
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            code = raw.decode(encoding)
            tree = ast.parse(code, filename=path)
        except (SyntaxError, UnicodeError, ValueError, RecursionError, LookupError):
            self.warn(path + ': parse_error')
            return
        module = path[:-3].replace('/', '.')
        if module.endswith('.__init__'):
            module = module[:-9]
        elif module == '__init__':
            module = ''
        # A module name collision is retained as ambiguity, never resolved by order.
        file_node = self.node('file', PurePosixPath(path).name, module or '__root__', path, 1, max(1, len(code.splitlines())), ast.get_docstring(tree) or '')
        scope = Scope(file_node['id'], 'module', path, module, '')
        self.scopes[file_node['id']] = scope
        self.modules.setdefault(module, []).append(file_node['id'])
        self.module_scopes[file_node['id']] = scope
        self.files.append({'path': path, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
        visitor = IndexVisitor(self, scope)
        try:
            visitor.visit(tree)
        except (GraphError, RecursionError) as exc:
            self.warn(path + ': ' + ('node_limit' if isinstance(exc, GraphError) else 'AST_depth_limit'))

    def lookup(self, scope, name, seen=None):
        if scope.blocked:
            return None, 'nested_expression_scope'
        cursor = scope
        while cursor is not None:
            if cursor.blocked:
                return None, 'wildcard_or_nested_scope'
            if cursor.kind == 'class' and cursor is not scope:
                cursor = cursor.parent
                continue
            if name in cursor.dynamic:
                return None, 'global_or_nonlocal_binding'
            if name in cursor.bindings:
                bindings = cursor.bindings[name]
                if len(bindings) != 1 or bindings[0][0] == 'shadow':
                    return None, 'shadowed_or_ambiguous_binding'
                return bindings[0], ''
            cursor = cursor.parent
        return None, 'external_or_dynamic_name'

    def module_scope(self, name):
        candidates = self.modules.get(name, [])
        return self.module_scopes[candidates[0]] if len(candidates) == 1 else None

    def resolve_export(self, module, symbol, visited=None):
        visited = set() if visited is None else visited
        if len(visited) > 20 or (module, symbol) in visited:
            return None
        visited.add((module, symbol))
        scope = self.module_scope(module)
        if scope is None or symbol in scope.dynamic:
            return None
        values = scope.bindings.get(symbol, [])
        if len(values) != 1:
            return None
        value = values[0]
        if value[0] == 'node':
            return value[1]
        if value[0] == 'symbol':
            return self.resolve_export(value[1], value[2], visited)
        return None

    def resolve_call(self, scope, parts):
        if not parts:
            return None, 'dynamic_callee'
        binding, reason = self.lookup(scope, parts[0])
        if binding is None:
            return None, reason
        if binding[0] == 'node' and len(parts) == 1:
            return binding[1], ''
        if binding[0] == 'symbol' and len(parts) == 1:
            target = self.resolve_export(binding[1], binding[2])
            return target, '' if target else 'unresolved_import_symbol'
        if binding[0] == 'module' and len(parts) >= 2:
            full = binding[1].split('.') + parts[1:]
            module, name = '.'.join(full[:-1]), full[-1]
            # Imports only establish the explicitly loaded module or its parent.
            if module != binding[2] and not binding[2].startswith(module + '.'):
                return None, 'unproven_module_attribute'
            target = self.resolve_export(module, name)
            return target, '' if target else 'unresolved_module_attribute'
        return None, 'dynamic_attribute_or_callable'

    def finish(self):
        for scope, module, line in self.imports:
            target = self.module_scope(module)
            if target:
                self.edge(scope.node_id, target.node_id, 'imports', scope.file, line)
        for scope, parts, line in self.calls:
            target, reason = self.resolve_call(scope, parts)
            if target:
                self.edge(scope.node_id, target, 'calls', scope.file, line, 'static_resolved')
            elif len(self.unresolved) < MAX_UNRESOLVED:
                self.unresolved.append({'source': scope.node_id, 'expression': '.'.join(parts)[:300] if parts else '<dynamic call>',
                                        'file': scope.file, 'line': line, 'reason': reason})
            else:
                self.warn('unresolved_limit: additional unresolved calls omitted')
        fingerprint = hashlib.sha256(json.dumps(self.files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return validate_snapshot({'schema_version': 1, 'module_id': 'coding-graph', 'mode': self.mode, 'generated_at': utc_now(),
                                  'codebase': {'label': self.label, 'file_count': len(self.files), 'fingerprint': fingerprint,
                                               'partial': self.partial, 'warnings': self.warnings},
                                  'files': self.files, 'nodes': self.nodes, 'edges': self.edges, 'unresolved': self.unresolved})


def dotted(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return parent + [node.attr] if parent else []
    return []


class IndexVisitor(ast.NodeVisitor):
    def __init__(self, graph, scope):
        self.graph, self.scope = graph, scope

    def bind_target(self, node):
        if isinstance(node, ast.Name):
            self.scope.bind(node.id, ('shadow',))
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self.bind_target(element)
        elif isinstance(node, ast.Starred):
            self.bind_target(node.value)
        elif isinstance(node, (ast.Attribute, ast.Subscript)):
            # Mutating an imported/module attribute invalidates static resolution.
            value = node.value
            while isinstance(value, (ast.Attribute, ast.Subscript)):
                value = value.value
            if isinstance(value, ast.Name):
                self.scope.bind(value.id, ('shadow',))

    def definition(self, node, kind):
        for decorator in node.decorator_list:
            self.visit(decorator)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for value in [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]:
                self.visit(value)
        elif isinstance(node, ast.ClassDef):
            for value in [*node.bases, *[k.value for k in node.keywords]]:
                self.visit(value)
        prefix = self.scope.qualname + ('.<locals>.' if self.scope.kind == 'function' else '.') if self.scope.qualname else ''
        local = prefix + node.name
        full = (self.scope.module + '.' if self.scope.module else '') + local
        item = self.graph.node(kind, node.name, full, self.scope.file, node.lineno, node.end_lineno or node.lineno, ast.get_docstring(node) or '')
        self.graph.edge(self.scope.node_id, item['id'], 'contains', self.scope.file, node.lineno)
        self.scope.bind(node.name, ('node', item['id']))
        if node.decorator_list:
            self.scope.bind(node.name, ('shadow',))
        old = self.scope
        self.scope = Scope(item['id'], 'class' if kind == 'class' else 'function', old.file, old.module, local, old)
        self.graph.scopes[item['id']] = self.scope
        if kind != 'class':
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, *([node.args.vararg] if node.args.vararg else []), *([node.args.kwarg] if node.args.kwarg else [])]:
                self.scope.bind(arg.arg, ('shadow',))
        for statement in node.body:
            self.visit(statement)
        self.scope = old

    def visit_FunctionDef(self, node):
        self.definition(node, 'function')

    def visit_AsyncFunctionDef(self, node):
        self.definition(node, 'async_function')

    def visit_ClassDef(self, node):
        self.definition(node, 'class')

    def visit_Call(self, node):
        if len(self.graph.calls) < MAX_CALLS:
            self.graph.calls.append((self.scope, dotted(node.func), node.lineno))
        else:
            self.graph.warn('call_limit: additional call expressions omitted')
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            self.bind_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.bind_target(node.target)
        self.generic_visit(node)

    visit_AugAssign = visit_AnnAssign

    def visit_NamedExpr(self, node):
        self.bind_target(node.target)
        self.generic_visit(node)

    def visit_Delete(self, node):
        for target in node.targets:
            self.bind_target(target)

    def visit_For(self, node):
        self.bind_target(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars:
                self.bind_target(item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node):
        if node.name:
            self.scope.bind(node.name, ('shadow',))
        self.generic_visit(node)

    def visit_Global(self, node):
        self.scope.dynamic.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_Import(self, node):
        for alias in node.names:
            bound = alias.asname or alias.name.split('.')[0]
            module = alias.name if alias.asname else alias.name.split('.')[0]
            self.scope.bind(bound, ('module', module, alias.name))
            if len(self.graph.imports) < MAX_EDGES:
                self.graph.imports.append((self.scope, alias.name, node.lineno))
            else:
                self.graph.warn('import_limit: additional imports omitted')

    def visit_ImportFrom(self, node):
        module = node.module or ''
        if node.level:
            package = self.scope.module if PurePosixPath(self.scope.file).name == '__init__.py' else self.scope.module.rpartition('.')[0]
            parts = package.split('.') if package else []
            if node.level > len(parts) + 1:
                return
            module = '.'.join(parts[:len(parts) - node.level + 1] + ([module] if module else []))
        if len(self.graph.imports) < MAX_EDGES:
            self.graph.imports.append((self.scope, module, node.lineno))
        else:
            self.graph.warn('import_limit: additional imports omitted')
        for alias in node.names:
            if alias.name == '*':
                # Wildcard imports may shadow any name in this scope.
                self.scope.blocked = True
            else:
                self.scope.bind(alias.asname or alias.name, ('symbol', module, alias.name))

    def nested_expression(self, node):
        if not isinstance(node, ast.Lambda):
            # Assignment expressions in comprehensions bind the containing scope.
            for descendant in ast.walk(node):
                if isinstance(descendant, ast.NamedExpr):
                    self.bind_target(descendant.target)
        old = self.scope
        self.scope = Scope(old.node_id, 'function', old.file, old.module, old.qualname, old, blocked=True)
        self.generic_visit(node)
        self.scope = old

    visit_Lambda = nested_expression
    visit_ListComp = nested_expression
    visit_SetComp = nested_expression
    visit_DictComp = nested_expression
    visit_GeneratorExp = nested_expression

    def visit_MatchAs(self, node):
        if node.name:
            self.scope.bind(node.name, ('shadow',))
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self.scope.bind(node.rest, ('shadow',))
        self.generic_visit(node)


def index_project(project, max_files=500, max_bytes=10 * 1024 * 1024):
    initial = Path(project).expanduser().absolute()
    if initial.is_symlink() or not initial.is_dir():
        raise GraphError('project must be a real directory')
    root = initial.resolve()
    if not isinstance(max_files, int) or not 1 <= max_files <= 5000 or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 100 * 1024 * 1024:
        raise GraphError('invalid indexing limits')
    graph, total, count = GraphBuilder(root.name), 0, 0
    stop = False
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d.casefold() not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            if not name.endswith('.py') or name.startswith('.') or name.casefold() in SKIP_FILES or name.startswith('test_') or name.endswith('_test.py'):
                continue
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if count >= max_files:
                graph.warn('file_count_limit: additional Python files omitted')
                stop = True
                break
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or path.is_symlink() or not path.resolve().is_relative_to(root):
                    graph.warn(rel + ': symbolic_or_special_file_skipped')
                    continue
                if info.st_size > MAX_FILE:
                    graph.warn(rel + ': file_size_limit')
                    continue
                if total + info.st_size > max_bytes:
                    graph.warn('total_bytes_limit: additional Python files omitted')
                    stop = True
                    break
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                with os.fdopen(descriptor, 'rb') as handle:
                    raw = handle.read(MAX_FILE + 1)
                if len(raw) > MAX_FILE or total + len(raw) > max_bytes:
                    graph.warn(rel + ': changed_or_oversized_file')
                    continue
                total += len(raw)
                count += 1
                graph.add_source(rel, raw)
            except (OSError, ValueError, GraphError):
                graph.warn(rel + ': unreadable_or_invalid_path')
        if stop:
            break
    if not graph.files:
        graph.warn('no_indexed_files: no readable eligible Python source found')
    return graph.finish()


def demo_snapshot():
    graph = GraphBuilder('Fictional checkout demo', 'demo')
    graph.add_source('price.py', b'"""Fictional learning example, not a real project."""\ndef discount(amount):\n    """Apply a fictional discount."""\n    return amount * 0.9\n\ndef total(amount):\n    """Calculate a fictional total."""\n    return discount(amount)\n')
    graph.add_source('checkout.py', b'"""Fictional checkout flow."""\nimport price\n\ndef checkout(amount):\n    """Ask price.total for the final amount."""\n    return price.total(amount)\n\ndef preview(amount):\n    return price.total(amount)\n')
    return graph.finish()


def select_node(snapshot, selector):
    by_id = [n for n in snapshot['nodes'] if n['id'] == selector]
    candidates = by_id or [n for n in snapshot['nodes'] if n['qualname'] == selector]
    if not candidates:
        candidates = [n for n in snapshot['nodes'] if n['name'] == selector]
    if len(candidates) != 1:
        raise GraphError('node not found' if not candidates else 'ambiguous selector; use a node ID or a unique qualified name')
    return candidates[0]


def matching_edges(snapshot, edge_kind='calls'):
    if edge_kind not in EDGE_KINDS | {'all'}:
        raise GraphError('invalid edge kind')
    return [e for e in snapshot['edges'] if edge_kind == 'all' or e['kind'] == edge_kind]


def query(snapshot, text, limit=30):
    if not _positive(limit, 100) or not isinstance(text, str) or len(text) > 1000:
        raise GraphError('invalid search query or limit')
    terms = text.casefold().split()
    def score(node):
        hay = ' '.join([node['name'], node['qualname'], node['file'], node['docstring']]).casefold()
        return sum(4 if t in node['name'].casefold() else 1 for t in terms) if all(t in hay for t in terms) else -1
    nodes = [n for n in snapshot['nodes'] if score(n) >= 0]
    nodes.sort(key=lambda n: (-score(n), n['file'], n['line'], n['id']))
    return {'nodes': nodes[:limit], 'total': len(nodes), 'truncated': len(nodes) > limit}


def context(snapshot, selector, edge_kind='calls', limit=100):
    if not _positive(limit, 1000):
        raise GraphError('invalid context result limit')
    node = select_node(snapshot, selector)
    selected = [e for e in matching_edges(snapshot, edge_kind) if node['id'] in {e['source'], e['target']}]
    edges = selected[:limit]
    ids = {node['id']} | {e[k] for e in edges for k in ('source', 'target')}
    return {'node': node, 'nodes': [n for n in snapshot['nodes'] if n['id'] in ids], 'edges': edges,
            'edge_kind': edge_kind, 'truncated': len(selected) > limit}


def impact(snapshot, selector, hops=3, edge_kind='calls'):
    if not _positive(hops, 10):
        raise GraphError('hops must be between 1 and 10')
    start = select_node(snapshot, selector)
    incoming = {}
    for e in matching_edges(snapshot, edge_kind):
        incoming.setdefault(e['target'], []).append(e)
    queue, distance, edges = deque([start['id']]), {start['id']: 0}, []
    while queue:
        current = queue.popleft()
        if distance[current] >= hops:
            continue
        for e in incoming.get(current, []):
            edges.append(e)
            if e['source'] not in distance:
                distance[e['source']] = distance[current] + 1
                queue.append(e['source'])
    return {'start': start['id'], 'edge_kind': edge_kind, 'hops': hops,
            'nodes': [dict(n, distance=distance[n['id']]) for n in snapshot['nodes'] if n['id'] in distance], 'edges': edges,
            'notice': 'Reverse static relationships only; not proof that a change causes runtime impact.'}


def trace(snapshot, source, target, edge_kind='calls'):
    start, end = select_node(snapshot, source), select_node(snapshot, target)
    outgoing = {}
    for e in matching_edges(snapshot, edge_kind):
        outgoing.setdefault(e['source'], []).append(e)
    queue, previous = deque([start['id']]), {start['id']: None}
    while queue and end['id'] not in previous:
        current = queue.popleft()
        for e in outgoing.get(current, []):
            if e['target'] not in previous:
                previous[e['target']] = e
                queue.append(e['target'])
    path, edges = [], []
    if end['id'] in previous:
        current = end['id']
        path.append(current)
        while previous[current] is not None:
            e = previous[current]
            edges.append(e)
            current = e['source']
            path.append(current)
        path.reverse()
        edges.reverse()
    by_id = {n['id']: n for n in snapshot['nodes']}
    return {'found': bool(path), 'edge_kind': edge_kind, 'nodes': [by_id[i] for i in path], 'edges': edges,
            'notice': 'Shortest directed path by edge count in this snapshot; not runtime or causal proof.'}
