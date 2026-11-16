#!/usr/bin/env python3
"""Collect official compute catalogs and headlines with explicit provenance."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import socket
import tempfile
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
MAX_BYTES = 4 * 1024 * 1024
STAGES = {'chips', 'memory', 'servers-network', 'cloud', 'datacenters', 'power-cooling', 'demand'}
SOURCES = [
    {'id': 'runpod-secure', 'name': 'Runpod · Secure Cloud', 'url': 'https://api.runpod.io/graphql', 'kind': 'runpod', 'cloud': 'secure'},
    {'id': 'runpod-community', 'name': 'Runpod · Community Cloud', 'url': 'https://api.runpod.io/graphql', 'kind': 'runpod', 'cloud': 'community'},
    {'id': 'nvidia', 'name': 'NVIDIA Newsroom', 'url': 'https://nvidianews.nvidia.com/cats/press_release.xml', 'kind': 'rss'},
    {'id': 'amd', 'name': 'AMD Investor Relations', 'url': 'https://ir.amd.com/news-events/press-releases/rss', 'kind': 'rss'},
]
CATALOG_QUERY = '''query { gpuTypes { id displayName memoryInGb lowestPrice(input: { gpuCount: 1, secureCloud: CLOUD }) { uninterruptablePrice } } }'''
COMPUTE_TERMS = re.compile(r'\b(?:AI|GPU|accelerator|accelerators|data\s*center|datacenter|EPYC|Instinct|Blackwell|Rubin|Hopper|NVLink|inference|training|compute|rack|server|servers|HBM)\b|算力|人工智能|数据中心', re.I)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, OverflowError):
        return None


def text(value, limit=600) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ''


def public_url(value) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return ''
    value = text(value, 4096)
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or any(ord(c) < 32 for c in value)):
            return ''
        parts.port
        return value
    except ValueError:
        return ''


def canonical_url(value) -> str:
    value = public_url(value)
    if not value:
        return ''
    parts = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.casefold().startswith('utm_') and k.casefold() not in {'fbclid', 'gclid', 'mc_cid', 'mc_eid'}]
    return urlunsplit(('https', parts.netloc.casefold(), parts.path or '/', urlencode(sorted(query)), ''))


def title_key(value: str) -> str:
    # Preserve numbers and word boundaries; similar tokens do not prove identity.
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value).casefold()).strip()


def stable_id(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def finite_number(value, minimum=0, maximum=1e9):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and minimum <= value <= maximum)


def clean_item(raw: dict, now: datetime | None = None) -> dict | None:
    if not isinstance(raw, dict) or raw.get('kind') not in {'signal', 'offer', 'filing'} or raw.get('stage') not in STAGES:
        return None
    title, url = text(raw.get('title')), public_url(raw.get('url'))
    observed = parse_time(raw.get('observed_at'))
    published = parse_time(raw.get('published_at'))
    if not title or not url or observed is None or (now and observed > now + timedelta(minutes=5)):
        return None
    if published and now and published > now + timedelta(minutes=5):
        return None
    quote = None
    if raw['kind'] == 'offer':
        q = raw.get('quote')
        if not isinstance(q, dict) or not text(q.get('gpu')) or not finite_number(q.get('price'), 0.000001):
            return None
        if not isinstance(q.get('gpu_count'), int) or isinstance(q['gpu_count'], bool) or not 1 <= q['gpu_count'] <= 1024:
            return None
        if q.get('currency') not in {'USD', 'CNY', 'EUR', 'GBP', 'JPY'} or q.get('unit') not in {'GPU-hour', 'server-hour', 'GPU-month', 'server-month'}:
            return None
        vram = q.get('vram_gb')
        if vram is not None and not finite_number(vram, 0.001, 100000):
            return None
        if q.get('price_basis') not in {'catalog_starting', 'manual', 'fictional'}:
            return None
        quote = {'gpu': text(q['gpu'], 120), 'gpu_count': q['gpu_count'], 'vram_gb': vram,
                 'region': text(q.get('region'), 100) or 'unknown', 'currency': q['currency'],
                 'unit': q['unit'], 'price': q['price'], 'billing': text(q.get('billing'), 100) or 'unknown',
                 'availability': text(q.get('availability'), 100) or 'unknown',
                 'cloud': text(q.get('cloud'), 40) or 'unknown', 'price_basis': q['price_basis']}
    sources = []
    for source in raw.get('sources', [])[:16] if isinstance(raw.get('sources'), list) else []:
        if isinstance(source, dict) and public_url(source.get('url')):
            sources.append({'name': text(source.get('name'), 120), 'url': public_url(source['url'])})
    if not sources:
        sources = [{'name': text(raw.get('provider'), 120), 'url': url}]
    item = {'id': text(raw.get('id'), 120), 'kind': raw['kind'], 'title': title, 'url': url,
            'stage': raw['stage'], 'provider': text(raw.get('provider'), 120),
            'published_at': iso(published) if published else None, 'observed_at': iso(observed),
            'summary': text(raw.get('summary'), 1000), 'sources': sources, 'quote': quote,
            'source_id': text(raw.get('source_id'), 80), 'offer_id': text(raw.get('offer_id'), 160),
            'provenance': raw.get('provenance') if raw.get('provenance') in {'official_catalog', 'official_rss', 'manual', 'fictional'} else 'manual',
            'stale': raw.get('stale') is True}
    if not item['id']:
        item['id'] = stable_id(identity(item))
    return item


def identity(item: dict):
    if item['kind'] == 'offer':
        q = item['quote']
        # Keep conflicting prices and every pricing/configuration dimension.
        return ('offer', item['provider'].casefold(), item['offer_id'] or canonical_url(item['url']),
                q['gpu'].casefold(), q['gpu_count'], q['vram_gb'], q['region'].casefold(),
                q['currency'], q['unit'], q['billing'].casefold(), q['cloud'], q['price_basis'], q['price'])
    day = (item.get('published_at') or item['observed_at'])[:10]
    return (item['kind'], item['stage'], day, canonical_url(item['url']))


def deduplicate(items: list[dict]) -> list[dict]:
    result, by_url, by_title = [], {}, {}
    for raw in items:
        item = clean_item(raw)
        if item is None:
            continue
        key = identity(item)
        day = (item.get('published_at') or item['observed_at'])[:10]
        headline = (item['kind'], item['stage'], day, title_key(item['title'])) if item['kind'] != 'offer' else None
        index = by_url.get(key)
        if index is None and headline is not None:
            index = by_title.get(headline)
        if index is None:
            index = len(result)
            result.append(item)
        else:
            existing = result[index]
            refs = {(s['name'], s['url']) for s in existing['sources']}
            for source in item['sources']:
                if (source['name'], source['url']) not in refs and len(existing['sources']) < 16:
                    existing['sources'].append(source)
                    refs.add((source['name'], source['url']))
            # A successful fresh observation may replace stale content, never the reverse.
            if (existing['stale'] and not item['stale']) or item['observed_at'] > existing['observed_at']:
                refs = existing['sources']
                result[index] = item
                result[index]['sources'] = refs
        by_url[key] = index
        if headline is not None:
            by_title[headline] = index
    return result


def clean_snapshot(raw: dict) -> dict:
    if (not isinstance(raw, dict) or raw.get('schema_version') != 1 or raw.get('module_id') != 'compute-search'
            or raw.get('mode') not in {'live', 'demo'} or not parse_time(raw.get('generated_at'))):
        raise ValueError('unsupported snapshot')
    if not isinstance(raw.get('items'), list) or len(raw['items']) > 5000 or not isinstance(raw.get('sources'), list):
        raise ValueError('invalid snapshot collections')
    sources = []
    for source in raw['sources'][:100]:
        if not isinstance(source, dict) or source.get('status') not in {'ok', 'empty', 'error'}:
            raise ValueError('invalid source health')
        checked = parse_time(source.get('checked_at'))
        if not checked or not public_url(source.get('url')):
            raise ValueError('invalid source metadata')
        sources.append({'id': text(source.get('id'), 80), 'name': text(source.get('name'), 160),
                        'url': public_url(source['url']), 'status': source['status'], 'checked_at': iso(checked),
                        'detail': text(source.get('detail'), 240)})
    if any(clean_item(item) is None for item in raw['items']):
        raise ValueError('snapshot contains invalid items')
    return {'schema_version': 1, 'module_id': 'compute-search', 'mode': raw['mode'],
            'generated_at': iso(parse_time(raw['generated_at'])), 'sources': sources,
            'items': deduplicate(raw['items']), 'reused_latest': raw.get('reused_latest') is True,
            'last_attempt_at': iso(parse_time(raw['last_attempt_at'])) if parse_time(raw.get('last_attempt_at')) else None}


def read_json(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('missing, symbolic or oversized JSON')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.compute-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_config(path: Path | None) -> dict:
    config = {'window_days': 30, 'timeout_seconds': 20, 'workers': 4, 'proxy': '', 'max_items_per_source': 50,
              'enabled_sources': [s['id'] for s in SOURCES], 'stale_retention_hours': 72}
    if path:
        supplied = read_json(path)
        if not isinstance(supplied, dict) or set(supplied) - set(config):
            raise ValueError('unknown configuration fields')
        config.update(supplied)
    for key, lo, hi in [('window_days', 1, 90), ('timeout_seconds', 1, 60), ('workers', 1, 4), ('max_items_per_source', 1, 100), ('stale_retention_hours', 1, 720)]:
        value = config[key]
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            raise ValueError('invalid configuration: ' + key)
    selected = config['enabled_sources']
    known = {s['id'] for s in SOURCES}
    if not isinstance(selected, list) or not selected or any(not isinstance(s, str) or s not in known for s in selected) or len(selected) != len(set(selected)):
        raise ValueError('enabled_sources must be unique known source IDs')
    proxy = config['proxy']
    if not isinstance(proxy, str):
        raise ValueError('proxy must be a string')
    if proxy:
        parsed = urlsplit(proxy)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            raise ValueError('proxy must be an HTTP(S) origin without credentials')
        parsed.port
    return config


class FetchFailure(Exception):
    pass


def read_response(source: dict, config: dict) -> bytes:
    proxy = config['proxy']
    opener = build_opener(ProxyHandler({'http': proxy, 'https': proxy} if proxy else {}))
    payload = None
    if source['kind'] == 'runpod':
        query = CATALOG_QUERY.replace('CLOUD', 'true' if source['cloud'] == 'secure' else 'false')
        payload = json.dumps({'query': query}).encode()
    request = Request(source['url'], data=payload, headers={
        'User-Agent': 'WorkhubComputeSearch/0.1 (official catalog and RSS reader)',
        'Content-Type': 'application/json', 'Accept': 'application/json, application/rss+xml, application/xml'})
    deadline = time.monotonic() + config['timeout_seconds']
    try:
        with opener.open(request, timeout=config['timeout_seconds']) as response:
            if response.status != 200:
                raise FetchFailure('http_status_' + str(response.status))
            length = response.headers.get('Content-Length', '')
            if length.isdigit() and int(length) > MAX_BYTES:
                raise FetchFailure('response_too_large')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchFailure('source_deadline')
                # read1 returns after one underlying read; periodic small chunks cannot
                # extend this source indefinitely. Also bound the socket's next wait.
                try:
                    response.fp.raw._sock.settimeout(remaining)
                except AttributeError:
                    pass
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchFailure('response_too_large')
            return b''.join(chunks)
    except HTTPError as exc:
        raise FetchFailure('http_status_' + str(exc.code)) from None
    except (URLError, TimeoutError, socket.timeout, HTTPException, OSError):
        raise FetchFailure('network_failure') from None


def parse_runpod(raw: bytes, source: dict, now: datetime) -> list[dict]:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get('errors') or not isinstance(payload.get('data'), dict) or not isinstance(payload['data'].get('gpuTypes'), list):
        raise ValueError('invalid Runpod catalog response')
    result = []
    for gpu in payload['data']['gpuTypes'][:200]:
        # The official catalog includes an explicit unknown/0-GB sentinel with
        # no price. It is not a quote and does not invalidate the other rows.
        if (isinstance(gpu, dict) and gpu.get('id') == 'unknown' and gpu.get('memoryInGb') == 0
                and (gpu.get('lowestPrice') or {}).get('uninterruptablePrice') is None):
            continue
        if (not isinstance(gpu, dict) or not text(gpu.get('id')) or not text(gpu.get('displayName'))
                or not finite_number(gpu.get('memoryInGb'), 0.001, 100000)
                or (gpu.get('lowestPrice') is not None and not isinstance(gpu.get('lowestPrice'), dict))):
            raise ValueError('invalid catalog row')
        price = gpu.get('lowestPrice')
        price = price.get('uninterruptablePrice') if isinstance(price, dict) else None
        if price is None:
            continue
        if not finite_number(price, 0.000001):
            raise ValueError('invalid catalog price')
        model = text(gpu.get('displayName'), 120)
        vram = gpu.get('memoryInGb')
        if not model or not finite_number(vram, 0.001, 100000):
            continue
        offer_id = text(gpu.get('id'), 160) + ':' + source['cloud'] + ':gpu-count-1'
        item = {'kind': 'offer', 'title': 'Runpod · ' + model, 'url': 'https://www.runpod.io/pricing',
                'stage': 'cloud', 'provider': 'Runpod', 'source_id': source['id'], 'offer_id': offer_id,
                'published_at': None, 'observed_at': iso(now), 'summary': '', 'provenance': 'official_catalog',
                'sources': [{'name': source['name'], 'url': 'https://www.runpod.io/pricing'}],
                'quote': {'gpu': model, 'gpu_count': 1, 'vram_gb': vram, 'region': 'unknown', 'currency': 'USD',
                          'unit': 'GPU-hour', 'price': price, 'billing': 'on-demand', 'availability': 'unknown',
                          'cloud': source['cloud'], 'price_basis': 'catalog_starting'}}
        cleaned = clean_item(item, now)
        if cleaned:
            result.append(cleaned)
    return result


def stage_for(title: str) -> str:
    value = title.casefold()
    for stage, pattern in [('power-cooling', r'liquid cooling|power supply|power grid|cooling|电力|液冷'),
                           ('memory', r'\bhbm\b|\bdram\b|memory|存储|内存'),
                           ('datacenters', r'data\s*cent(?:er|re)|datacent(?:er|re)|数据中心'),
                           ('servers-network', r'\bepyc\b|nvlink|networking|\bserver|服务器|互联'),
                           ('cloud', r'cloud|云服务|租赁'),
                           ('demand', r'capital expenditure|\bcapex\b|revenue|financial result|财报|营收')]:
        if re.search(pattern, value):
            return stage
    return 'chips'


def parse_rss(raw: bytes, source: dict, now: datetime, config: dict) -> list[dict]:
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('unsafe XML declarations')
    root = ET.fromstring(raw)
    if root.tag not in {'rss', '{http://www.w3.org/2005/Atom}feed', 'feed', '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF'}:
        raise ValueError('unsupported feed format')
    nodes = root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
    result = []
    for node in nodes[:500]:
        title = html.unescape(node.findtext('title') or node.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
        if not title or not COMPUTE_TERMS.search(title):
            continue
        link = node.findtext('link') or ''
        if not link:
            element = node.find('{http://www.w3.org/2005/Atom}link')
            link = element.get('href', '') if element is not None else ''
        value = node.findtext('pubDate') or node.findtext('{http://www.w3.org/2005/Atom}published') or node.findtext('{http://www.w3.org/2005/Atom}updated') or ''
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            date = parse_time(value)
        if not date or not date.tzinfo:
            continue
        try:
            date = date.astimezone(UTC)
        except (ValueError, OverflowError):
            continue
        if date > now or date < now - timedelta(days=config['window_days']):
            continue
        item = {'kind': 'signal', 'title': title, 'url': link, 'stage': stage_for(title),
                'provider': source['name'], 'source_id': source['id'], 'published_at': iso(date),
                'observed_at': iso(now), 'summary': '', 'provenance': 'official_rss',
                'sources': [{'name': source['name'], 'url': link}], 'quote': None}
        cleaned = clean_item(item, now)
        if cleaned:
            result.append(cleaned)
        if len(result) >= config['max_items_per_source']:
            break
    return result


def collect_source(source: dict, config: dict, now: datetime):
    status = {'id': source['id'], 'name': source['name'], 'url': source['url'],
              'checked_at': iso(now), 'status': 'error', 'detail': ''}
    try:
        body = read_response(source, config)
        items = parse_runpod(body, source, now) if source['kind'] == 'runpod' else parse_rss(body, source, now, config)
        items = items[:config['max_items_per_source']]
        status.update(status='ok' if items else 'empty', detail='accepted_items:' + str(len(items)))
        return items, status
    except FetchFailure as exc:
        status['detail'] = str(exc)
    except (ValueError, UnicodeError, ET.ParseError, TypeError, KeyError, AttributeError):
        status['detail'] = 'invalid_source_payload'
    return [], status


def demo_snapshot(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    base = {'kind': 'offer', 'title': 'Fictional GPU X · demo', 'url': 'https://example.com/fictional-compute',
            'stage': 'cloud', 'provider': 'Fictional Cloud', 'source_id': 'fictional', 'offer_id': 'fictional-gpu-x-us',
            'published_at': None, 'observed_at': iso(now), 'summary': '', 'provenance': 'fictional',
            'sources': [{'name': 'Fictional Cloud', 'url': 'https://example.com/fictional-compute'}],
            'quote': {'gpu': 'Fictional GPU X', 'gpu_count': 1, 'vram_gb': 48, 'region': 'demo-us', 'currency': 'USD',
                      'unit': 'GPU-hour', 'price': 1.2, 'billing': 'on-demand', 'availability': 'unknown',
                      'cloud': 'secure', 'price_basis': 'fictional'}}
    other = json.loads(json.dumps(base))
    other['offer_id'] = 'fictional-gpu-x-eu'
    other['quote'].update(region='demo-eu', price=1.4)
    signal = {'kind': 'signal', 'title': '虚构演示：某算力项目披露扩容计划，交付时间仍待验证',
              'url': 'https://example.com/fictional-capex', 'stage': 'demand', 'provider': 'Fictional IR',
              'source_id': 'fictional', 'published_at': iso(now - timedelta(days=1)), 'observed_at': iso(now),
              'summary': '', 'provenance': 'fictional', 'sources': [{'name': 'Fictional IR', 'url': 'https://example.com/fictional-capex'}], 'quote': None}
    return clean_snapshot({'schema_version': 1, 'module_id': 'compute-search', 'mode': 'demo', 'generated_at': iso(now),
                           'sources': [{'id': 'fictional', 'name': 'Fictional demo', 'url': 'https://example.com/',
                                        'status': 'ok', 'checked_at': iso(now), 'detail': 'fictional examples; not market observations'}],
                           'items': [base, base, other, signal]})


def write_collection(data_dir: Path, snapshot: dict, stale_retention_hours: int = 72) -> tuple[dict, bool]:
    data_dir.mkdir(parents=True, exist_ok=True)
    if data_dir.is_symlink():
        raise ValueError('data directory cannot be symbolic')
    mode_path, latest_path = data_dir / '.collection-mode.json', data_dir / 'latest.json'
    if mode_path.exists():
        mode = read_json(mode_path)
        if not isinstance(mode, dict) or mode.get('module_id') != 'compute-search' or mode.get('mode') != snapshot['mode']:
            raise ValueError('demo/live or module mismatch; use a separate data directory')
    previous = None
    prior_attempt = data_dir / 'last-run.json'
    if prior_attempt.exists():
        attempt = clean_snapshot(read_json(prior_attempt))
        if attempt['mode'] != snapshot['mode']:
            raise ValueError('last-run demo/live mismatch; use a separate data directory')
    if latest_path.exists():
        previous = clean_snapshot(read_json(latest_path))
        if previous['mode'] != snapshot['mode']:
            raise ValueError('demo/live mismatch; use a separate data directory')
    atomic_json(mode_path, {'module_id': 'compute-search', 'mode': snapshot['mode']})
    usable = any(s['status'] in {'ok', 'empty'} for s in snapshot['sources'])
    atomic_json(data_dir / 'last-run.json', snapshot)
    if not usable:
        return snapshot, False
    if previous:
        failed = {s['id'] for s in snapshot['sources'] if s['status'] == 'error'}
        for item in previous['items']:
            cutoff = parse_time(snapshot['generated_at']) - timedelta(hours=stale_retention_hours)
            if item['source_id'] in failed and parse_time(item['observed_at']) >= cutoff:
                old = dict(item)
                old['stale'] = True
                snapshot['items'].append(old)
        snapshot['items'] = deduplicate(snapshot['items'])
    atomic_json(latest_path, snapshot)
    return snapshot, True


@contextmanager
def collection_lock(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    if data_dir.is_symlink():
        raise ValueError('data directory cannot be symbolic')
    lock = data_dir / '.collect.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('collection already running or stale .collect.lock; verify no collector is active before removing it') from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--demo', action='store_true', help='write clearly fictional offline examples to a separate data directory')
    args = parser.parse_args()
    try:
        with collection_lock(args.data_dir):
            now = datetime.now(UTC)
            if args.demo:
                snapshot = demo_snapshot(now)
            else:
                config = load_config(args.config)
                selected = [s for s in SOURCES if s['id'] in config['enabled_sources']]
                with ThreadPoolExecutor(max_workers=config['workers']) as executor:
                    results = list(executor.map(lambda source: collect_source(source, config, now), selected))
                snapshot = clean_snapshot({'schema_version': 1, 'module_id': 'compute-search', 'mode': 'live',
                                           'generated_at': iso(now), 'items': [i for items, _ in results for i in items],
                                           'sources': [status for _, status in results]})
            snapshot, usable = write_collection(args.data_dir, snapshot, 72 if args.demo else config['stale_retention_hours'])
        print(json.dumps({'module_id': 'compute-search', 'mode': snapshot['mode'], 'item_count': len(snapshot['items']),
                          'source_status': {s['id']: s['status'] for s in snapshot['sources']},
                          'latest_updated': usable, 'all_failed': not usable}, ensure_ascii=False))
        return 0 if usable else 2
    except (ValueError, OSError, UnicodeError) as exc:
        print('Collection failed: ' + str(exc), file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
