#!/usr/bin/env python3
"""Validate and append evidenced industry claims without guessing truth."""
from __future__ import annotations
from collections import deque
from contextlib import contextmanager
from datetime import date
import copy
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 4 * 1024 * 1024
LIMITS = {'entities': 2000, 'relations': 5000, 'sources': 1000, 'changes': 10000}
STATUSES = {'disclosed', 'verified', 'inferred', 'hypothesis'}
CLAIM_KEYS = {'id', 'field', 'value', 'source_ids', 'status', 'valid_from', 'valid_to', 'observed_at', 'note'}


class AtlasError(ValueError):
    pass


def empty_atlas():
    return {'schema_version': 1, 'module_id': 'industry-atlas', 'demo': False,
            'entities': [], 'relations': [], 'sources': [], 'changes': []}


def obj(value, keys, label, optional=()):
    if not isinstance(value, dict) or set(value) - set(keys) or set(keys) - set(optional) - set(value):
        raise AtlasError('invalid fields in ' + label)


def text(value, label, maximum=200, empty=False, multiline=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(ord(c) < 32 and not (multiline and c in '\n\r\t') for c in value)):
        raise AtlasError('invalid text in ' + label)
    return value


def ident(value, label='id'):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', value) is None:
        raise AtlasError('invalid identifier in ' + label)
    return value


def slug(value, label):
    if not isinstance(value, str) or re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}', value) is None:
        raise AtlasError('invalid field or kind in ' + label)
    return value


def day(value, label, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
        raise AtlasError('date must be YYYY-MM-DD in ' + label)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise AtlasError('invalid calendar date in ' + label) from None
    return value


def public_url(value):
    text(value, 'source URL', 2048)
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None or '\\' in value or any(ord(c) < 33 for c in value):
            raise ValueError()
        p.port
        host = p.hostname.casefold().rstrip('.')
        if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.localhost', '.internal', '.invalid', '.test')):
            raise ValueError()
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and not ip.is_global:
            raise ValueError()
        if ip is None:
            ascii_host = host.encode('idna').decode('ascii')
            labels = ascii_host.split('.')
            if (len(ascii_host) > 253 or len(labels) < 2
                    or ascii_host.endswith(('.local', '.localhost', '.internal', '.invalid', '.test'))
                    or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)
                    or re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', labels[-1])):
                raise ValueError()
        if any(re.search(r'(?i)(?:^|[_-])(?:api[_-]?key|key|token|access[_-]token|auth[_-]token|authorization|password|pwd|secret|signature)(?:$|[_-])', k) for k, _ in [*parse_qsl(p.query), *parse_qsl(p.fragment)]):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise AtlasError('source URL must be public HTTPS without credentials') from None
    return value


def property_value(value, depth=0):
    if depth > 6:
        raise AtlasError('claim value exceeds nesting limit')
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return text(value, 'claim value', 4096, multiline=True)
    if isinstance(value, int):
        if abs(value) > 9007199254740991:
            raise AtlasError('large integer claim values must use explicit text')
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AtlasError('claim value must be finite')
        return value
    if isinstance(value, list) and len(value) <= 100:
        return [property_value(v, depth + 1) for v in value]
    if isinstance(value, dict) and len(value) <= 100:
        return {text(k, 'claim value key', 100): property_value(v, depth + 1) for k, v in value.items()}
    raise AtlasError('unsupported or oversized claim value')


def same_json(left, right):
    """Keep Boolean, numeric and container types distinct during idempotent merges."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json(v, right[k]) for k, v in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right


def unique_rows(rows, label):
    if not isinstance(rows, list):
        raise AtlasError(label + ' must be an array')
    output, seen = [], {}
    for row in rows:
        if not isinstance(row, dict):
            raise AtlasError('invalid row in ' + label)
        key = ident(row.get('id'), label)
        if key in seen:
            if not same_json(seen[key], row):
                raise AtlasError('conflicting duplicate id in ' + label)
            continue
        seen[key] = row
        output.append(row)
    return output


def _validate_atlas(raw, references=True):
    obj(raw, {'schema_version', 'module_id', 'demo', *LIMITS}, 'atlas', optional={'demo'})
    if type(raw['schema_version']) is not int or raw['schema_version'] != 1 or raw['module_id'] != 'industry-atlas' or not isinstance(raw.get('demo', False), bool):
        raise AtlasError('unsupported atlas identity')
    result = empty_atlas()
    result['demo'] = raw.get('demo', False)
    for key, maximum in LIMITS.items():
        if not isinstance(raw[key], list) or len(raw[key]) > maximum:
            raise AtlasError('invalid collection size in ' + key)
    source_map = {}
    for source in unique_rows(raw['sources'], 'sources'):
        obj(source, {'id', 'title', 'url', 'kind', 'published_at', 'accessed_at', 'independence_group'}, 'source')
        ident(source['id']);text(source['title'], 'source title', 300)
        if source['kind'] not in {'primary', 'secondary'}:
            raise AtlasError('source kind must be primary or secondary')
        public_url(source['url']);day(source['published_at'], 'source publication', True);day(source['accessed_at'], 'source access')
        if source['published_at'] is not None and source['published_at'] > source['accessed_at']:
            raise AtlasError('source publication cannot follow access date')
        text(source['independence_group'], 'source independence group', 200)
        source_map[source['id']] = copy.deepcopy(source)
    result['sources'] = list(source_map.values())
    claim_map, claim_count = {}, 0

    def claim(raw_claim, owner, relation_kind=None):
        nonlocal claim_count
        obj(raw_claim, CLAIM_KEYS, 'claim')
        ident(raw_claim['id']);slug(raw_claim['field'], 'claim field')
        if relation_kind is not None and raw_claim['field'] != 'relationship':
            raise AtlasError('relation claims must use relationship field')
        if relation_kind is None and raw_claim['field'] == 'relationship':
            raise AtlasError('relationship field is reserved for relation claims')
        value = property_value(raw_claim['value'])
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 4096:
            raise AtlasError('claim value exceeds 4KiB')
        refs = raw_claim['source_ids']
        if not isinstance(refs, list) or len(refs) > 20 or len(refs) != len(set(refs)):
            raise AtlasError('invalid or duplicate claim source ids')
        for ref in refs:
            ident(ref, 'source reference')
        status = raw_claim['status']
        if status not in STATUSES:
            raise AtlasError('invalid claim evidence status')
        if value is not None and not refs and status != 'hypothesis':
            raise AtlasError('nonempty claims require a source or hypothesis status')
        day(raw_claim['valid_from'], 'valid_from', True);day(raw_claim['valid_to'], 'valid_to', True)
        if raw_claim['valid_from'] is not None and raw_claim['valid_to'] is not None and raw_claim['valid_from'] > raw_claim['valid_to']:
            raise AtlasError('valid_to cannot precede valid_from')
        day(raw_claim['observed_at'], 'claim observation');text(raw_claim['note'], 'claim note', 2000, empty=True, multiline=True)
        if references:
            if any(ref not in source_map for ref in refs):
                raise AtlasError('claim has a missing source reference')
            groups = {' '.join(source_map[ref]['independence_group'].split()).casefold() for ref in refs}
            if status == 'verified' and len(groups) < 2:
                raise AtlasError('verified requires two independent source groups')
        previous = claim_map.get(raw_claim['id'])
        signature = (owner, relation_kind, raw_claim)
        if previous is not None and (previous[:2] != signature[:2] or not same_json(previous[2], signature[2])):
            raise AtlasError('claim ids must be globally unambiguous')
        if previous is None:
            claim_count += 1
            if claim_count > 10000:
                raise AtlasError('atlas exceeds claim limit')
            claim_map[raw_claim['id']] = signature
        return copy.deepcopy(raw_claim)

    entity_ids = set()
    for entity in unique_rows(raw['entities'], 'entities'):
        obj(entity, {'id', 'name', 'kind', 'industries', 'aliases', 'claims'}, 'entity')
        ident(entity['id']);text(entity['name'], 'entity name', 200);slug(entity['kind'], 'entity kind')
        for key, maximum in [('industries', 30), ('aliases', 30)]:
            values = entity[key]
            if not isinstance(values, list) or len(values) > maximum or len(values) != len(set(values)):
                raise AtlasError('invalid entity ' + key)
            for value in values:
                text(value, 'entity ' + key, 200)
        if not entity['industries']:
            raise AtlasError('entity requires at least one industry')
        if not isinstance(entity['claims'], list) or len(entity['claims']) > 500:
            raise AtlasError('invalid entity claims')
        entity_ids.add(entity['id'])
        cleaned = copy.deepcopy(entity)
        cleaned['claims'] = [claim(c, entity['id']) for c in unique_rows(entity['claims'], 'entity claims')]
        result['entities'].append(cleaned)
    relation_ids = set()
    for relation in unique_rows(raw['relations'], 'relations'):
        obj(relation, {'id', 'source', 'target', 'kind', 'claim'}, 'relation')
        ident(relation['id']);ident(relation['source']);ident(relation['target']);slug(relation['kind'], 'relation kind')
        if references and (relation['source'] not in entity_ids or relation['target'] not in entity_ids):
            raise AtlasError('relation endpoint is missing')
        relation_ids.add(relation['id'])
        cleaned = copy.deepcopy(relation)
        if relation['claim'].get('id') in claim_map:
            raise AtlasError('a claim id cannot be shared by different relations')
        cleaned['claim'] = claim(relation['claim'], relation['source'], relation['kind'])
        result['relations'].append(cleaned)
    links, degrees, touched = {}, {}, set()
    for change in unique_rows(raw['changes'], 'changes'):
        obj(change, {'id', 'entity_id', 'field', 'previous_claim_id', 'new_claim_id', 'observed_at', 'note'}, 'change')
        for key in ('id', 'entity_id', 'previous_claim_id', 'new_claim_id'):
            ident(change[key], 'change reference')
        slug(change['field'], 'change field');day(change['observed_at'], 'change observation');text(change['note'], 'change note', 2000, empty=True, multiline=True)
        before, after = change['previous_claim_id'], change['new_claim_id']
        if before == after:
            raise AtlasError('a change must reference two different claims')
        if references:
            if change['entity_id'] not in entity_ids or before not in claim_map or after not in claim_map:
                raise AtlasError('change reference is missing')
            old_owner, old_kind, old = claim_map[before]
            new_owner, new_kind, new = claim_map[after]
            if old_owner != change['entity_id'] or new_owner != change['entity_id'] or old['field'] != change['field'] or new['field'] != change['field'] or old_kind != new_kind:
                raise AtlasError('change cannot cross entity, field or relationship kind')
            if change['observed_at'] < max(old['observed_at'], new['observed_at']):
                raise AtlasError('change observation precedes its claim observations')
        links.setdefault(before, []).append(after)
        degrees[after] = degrees.get(after, 0) + 1
        degrees.setdefault(before, 0)
        touched.update((before, after))
        result['changes'].append(copy.deepcopy(change))
    queue, visited = deque(k for k in touched if degrees.get(k, 0) == 0), 0
    while queue:
        key = queue.popleft();visited += 1
        for target in links.get(key, []):
            degrees[target] -= 1
            if degrees[target] == 0:
                queue.append(target)
    if visited != len(touched):
        raise AtlasError('change ledger contains a cycle')
    return result


def validate_atlas(raw, references=True):
    try:
        return _validate_atlas(raw, references)
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise AtlasError('invalid atlas field types or nesting') from None


def merge_atlases(previous, incoming):
    previous = validate_atlas(previous)
    incoming = validate_atlas(incoming, references=False)
    if previous['demo'] != incoming['demo']:
        raise AtlasError('demo and live data cannot be merged')
    result = copy.deepcopy(previous)
    for key in ('sources', 'relations', 'changes'):
        rows = {r['id']: r for r in result[key]}
        for row in incoming[key]:
            if row['id'] in rows:
                if not same_json(rows[row['id']], row):
                    raise AtlasError('conflicting duplicate id in merged ' + key)
            else:
                result[key].append(row);rows[row['id']] = row
    entities = {e['id']: e for e in result['entities']}
    for entity in incoming['entities']:
        if entity['id'] not in entities:
            result['entities'].append(entity);entities[entity['id']] = entity
            continue
        existing = entities[entity['id']]
        if existing['name'] != entity['name'] or existing['kind'] != entity['kind']:
            raise AtlasError('existing entity identity cannot be silently changed')
        for key in ('industries', 'aliases'):
            existing[key] = list(dict.fromkeys([*existing[key], *entity[key]]))
        claims = {c['id']: c for c in existing['claims']}
        for c in entity['claims']:
            if c['id'] in claims:
                if not same_json(claims[c['id']], c):
                    raise AtlasError('existing claim cannot be overwritten')
            else:
                existing['claims'].append(c);claims[c['id']] = c
    return validate_atlas(result)


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_BYTES:
        raise AtlasError('input must be one regular JSON file no larger than 4MiB')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise AtlasError('JSON input exceeds 4MiB')
    def no_duplicate_keys(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise AtlasError('duplicate JSON object keys are not allowed')
            output[key] = value
        return output
    try:
        return json.loads(raw, object_pairs_hook=no_duplicate_keys, parse_constant=lambda _: (_ for _ in ()).throw(AtlasError('nonfinite JSON is not allowed')))
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise AtlasError('invalid JSON input') from None


def atomic_json(path, data):
    path = Path(path)
    encoded = (json.dumps(validate_atlas(data), ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    if path.suffix != '.json' or len(encoded) > MAX_BYTES:
        raise AtlasError('saved atlas must be a .json file no larger than 4MiB')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise AtlasError('output location cannot be symbolic')
    fd, temporary = tempfile.mkstemp(prefix='.atlas-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(encoded);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def output_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise AtlasError('output location cannot be symbolic')
    lock = path.parent / '.industry-atlas.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise AtlasError('import is locked; verify the previous process before removing a stale lock') from None
    try:
        os.write(fd, str(os.getpid()).encode());yield
    finally:
        os.close(fd);lock.unlink(missing_ok=True)
