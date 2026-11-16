#!/usr/bin/env python3
"""Read bounded, public GitHub releases without keys or code installation."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
REPOS = ('abhigyanpatwari/GitNexus', 'OpenHands/OpenHands', 'SWE-agent/mini-swe-agent',
         'microsoft/graphrag', 'langchain-ai/deepagents',
         'modelcontextprotocol/modelcontextprotocol', 'HKUDS/LightRAG')
MAX_BYTES = 2 * 1024 * 1024
WINDOW_DAYS = 90
PER_REPO = 6
REQUEST_LIMIT = 6
TIMEOUT = 15

class FrontierError(ValueError):
    pass

def iso(value):
    return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')

def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None

def short(value, limit=300):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise FrontierError('invalid text field')
    return value.strip()[:limit]

def release_url(value, repo, demo=False):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value) or "\\" in value:
        raise FrontierError('invalid release URL')
    try:
        p = urlsplit(value)
        decoded = unquote(p.path).replace("\\", "/")
        if any(part in {'.', '..'} for part in decoded.split('/')):
            raise FrontierError('release URL cannot contain dot segments')
        if p.scheme != 'https' or p.username or p.password or p.query or p.fragment or p.port not in (None, 443):
            raise FrontierError('invalid release URL')
        prefix = '/' + repo + '/releases/tag/'
        if p.hostname == 'github.com' and p.path.casefold().startswith(prefix.casefold()) and len(p.path) > len(prefix):
            return urlunsplit(('https', 'github.com', '/' + repo.casefold() + '/releases/tag/' + p.path[len(prefix):], '', ''))
        if demo and p.hostname == 'example.com':
            return urlunsplit(('https', 'example.com', p.path, '', ''))
        raise FrontierError('release URL must match its repository')
    except (ValueError, TypeError):
        raise FrontierError('invalid release URL') from None

def empty_frontier():
    return {'schema_version': 1, 'module_id': 'coding-graph', 'generated_at': None, 'items': [], 'sources': [],
            'reused_latest': False, 'last_attempt_at': None, 'collected': False, 'demo': False,
            'window_days': WINDOW_DAYS, 'per_repo_limit': PER_REPO}

def _validate_frontier(raw):
    if (not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw.get('schema_version') != 1 or raw.get('module_id') != 'coding-graph'
            or not isinstance(raw.get('items'), list) or not isinstance(raw.get('sources'), list)
            or len(raw['items']) > 100 or len(raw['sources']) > 20):
        raise FrontierError('invalid frontier snapshot')
    for flag in ('collected', 'demo', 'reused_latest'):
        if flag in raw and not isinstance(raw[flag], bool):
            raise FrontierError('invalid snapshot flag')
    generated = parse_time(raw.get('generated_at'))
    if raw.get('generated_at') is not None and generated is None:
        raise FrontierError('invalid collection date')
    demo = raw.get('demo') is True
    allowed = set(REPOS) | ({'fictional/demo-agent'} if demo else set())
    result = empty_frontier()
    result.update(generated_at=iso(generated) if generated else None, demo=demo,
                  reused_latest=raw.get('reused_latest') is True, collected=raw.get('collected', generated is not None) is True)
    if result['collected'] and generated is None:
        raise FrontierError('collected snapshot requires a date')
    attempt = parse_time(raw.get('last_attempt_at'))
    if raw.get('last_attempt_at') is not None and attempt is None:
        raise FrontierError('invalid attempt date')
    result['last_attempt_at'] = iso(attempt) if attempt else None
    seen_ids, seen_urls = set(), set()
    for item in raw['items']:
        if not isinstance(item, dict) or item.get('repo') not in allowed or not isinstance(item.get('prerelease'), bool):
            raise FrontierError('invalid release item')
        identifier, title = short(item.get('id'), 200), short(item.get('title'))
        if not identifier or not title:
            raise FrontierError('release identity is missing')
        published, observed = parse_time(item.get('published_at')), parse_time(item.get('observed_at'))
        if not published or not observed or published - observed > timedelta(minutes=5):
            raise FrontierError('invalid release dates')
        if generated and (observed - generated > timedelta(minutes=5) or generated - published > timedelta(days=WINDOW_DAYS)):
            raise FrontierError('release does not match the collection window')
        url = release_url(item.get('url'), item['repo'], demo)
        key, url_key = (item['repo'].casefold(), identifier), (item['repo'].casefold(), url)
        if key in seen_ids or url_key in seen_urls:
            continue
        seen_ids.add(key); seen_urls.add(url_key)
        result['items'].append({'id': identifier, 'repo': item['repo'], 'title': title, 'url': url,
                                'published_at': iso(published), 'observed_at': iso(observed),
                                'prerelease': item['prerelease']})
    source_ids = set()
    for source in raw['sources']:
        if (not isinstance(source, dict) or source.get('repo') not in allowed
                or source.get('status') not in {'ok', 'empty', 'error'}):
            raise FrontierError('invalid source health')
        identifier = short(source.get('id'), 160)
        checked = parse_time(source.get('checked_at'))
        expected = ('https://example.com/fictional-releases' if demo and source['repo'] == 'fictional/demo-agent'
                    else 'https://api.github.com/repos/' + source['repo'] + '/releases')
        if identifier != source['repo'] or identifier in source_ids or not checked or source.get('url') != expected:
            raise FrontierError('invalid source metadata')
        if generated and checked - generated > timedelta(minutes=5):
            raise FrontierError('source check does not match the collection date')
        source_ids.add(identifier)
        result['sources'].append({'id': identifier, 'repo': source['repo'], 'url': source['url'],
                                  'status': source['status'], 'checked_at': iso(checked),
                                  'detail': short(source.get('detail', ''), 200)})
    if result['items'] and (generated is None or not result['collected']):
        raise FrontierError('release items require a collection date')
    result['items'].sort(key=lambda item: (item['published_at'], item['repo'], item['id']), reverse=True)
    return result

def validate_frontier(raw):
    try:
        return _validate_frontier(raw)
    except FrontierError:
        raise
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise FrontierError('invalid frontier field types') from None

def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise FrontierError('missing, symbolic or oversized snapshot')
    try:
        return json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(FrontierError('nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise FrontierError('invalid snapshot JSON') from None

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise FrontierError('data location cannot be symbolic')
    fd, temporary = tempfile.mkstemp(prefix='.frontier-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def source_url(repo):
    return 'https://api.github.com/repos/' + repo + '/releases'

def validate_proxy(value):
    if not value:
        return ''
    try:
        p = urlsplit(value)
        if (p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password
                or p.path not in {'', '/'} or p.query or p.fragment or any(ord(c) < 33 for c in value)):
            raise FrontierError('proxy must be an HTTP(S) origin without credentials')
        p.port
        return value
    except ValueError:
        raise FrontierError('invalid proxy') from None

def read_response(url, proxy='', timeout=TIMEOUT):
    opener = build_opener(ProxyHandler({'http': proxy, 'https': proxy} if proxy else {}))
    request = Request(url + '?per_page=' + str(REQUEST_LIMIT), headers={'User-Agent': 'WorkhubCodingGraph/0.1',
                      'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise FrontierError('http_' + str(response.status))
            length = response.headers.get('Content-Length', '')
            if length.isdigit() and int(length) > MAX_BYTES:
                raise FrontierError('response_too_large')
            parts, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FrontierError('source_deadline')
                try:
                    response.fp.raw._sock.settimeout(remaining)
                except AttributeError:
                    pass
                part = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not part:
                    break
                parts.append(part); size += len(part)
                if size > MAX_BYTES:
                    raise FrontierError('response_too_large')
            if length.isdigit() and size != int(length):
                raise FrontierError('incomplete_response')
            return b''.join(parts)
    except HTTPError as exc:
        limited = exc.code == 429 or exc.code == 403 and exc.headers.get('X-RateLimit-Remaining') == '0'
        raise FrontierError('rate_limited' if limited else 'http_' + str(exc.code)) from None
    except (URLError, TimeoutError, socket.timeout, HTTPException, OSError):
        raise FrontierError('network_failure') from None

def parse_releases(body, repo, observed):
    try:
        values = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(FrontierError('nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise FrontierError('invalid_source_payload') from None
    if not isinstance(values, list):
        raise FrontierError('invalid_source_payload')
    items = []
    for value in values[:REQUEST_LIMIT]:
        if not isinstance(value, dict):
            raise FrontierError('invalid_source_payload')
        if value.get('draft') is True:
            continue
        published = parse_time(value.get('published_at'))
        if published is None or published - observed > timedelta(minutes=5):
            raise FrontierError('invalid_source_payload')
        if observed - published > timedelta(days=WINDOW_DAYS):
            continue
        release_id = value.get('id')
        if not isinstance(release_id, int) or isinstance(release_id, bool) or release_id <= 0:
            raise FrontierError('invalid_source_payload')
        title = value.get('name') or value.get('tag_name')
        if not isinstance(value.get('prerelease'), bool):
            raise FrontierError('invalid_source_payload')
        items.append({'id': repo + '#' + str(release_id), 'repo': repo, 'title': short(title),
                      'url': release_url(value.get('html_url'), repo), 'published_at': iso(published),
                      'observed_at': iso(observed), 'prerelease': value['prerelease']})
    raw = empty_frontier()
    raw.update(generated_at=iso(observed), collected=True, items=items)
    return validate_frontier(raw)['items'][:PER_REPO]

def collect_source(repo, proxy, observed):
    source = {'id': repo, 'repo': repo, 'url': source_url(repo), 'status': 'error',
              'checked_at': iso(observed), 'detail': ''}
    try:
        items = parse_releases(read_response(source['url'], proxy), repo, observed)
        source.update(status='ok' if items else 'empty', detail='accepted_items:' + str(len(items)))
        return items, source
    except FrontierError as exc:
        source['detail'] = str(exc)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        source['detail'] = 'invalid_source_payload'
    return [], source

def write_collection(data_dir, snapshot):
    snapshot = validate_frontier(snapshot)
    data_dir.mkdir(parents=True, exist_ok=True)
    if data_dir.is_symlink():
        raise FrontierError('data directory cannot be symbolic')
    current = data_dir / 'frontier.json'
    if current.exists() or current.is_symlink():
        previous = validate_frontier(read_json(current))
        if previous['demo'] != snapshot['demo']:
            raise FrontierError('demo/live snapshots require separate data directories')
    usable = any(source['status'] in {'ok', 'empty'} for source in snapshot['sources'])
    snapshot['collected'] = usable
    atomic_json(data_dir / 'frontier-last-run.json', snapshot)
    if usable:
        atomic_json(current, snapshot)
    return usable

def load_frontier(path, explicit=False):
    if path.exists() or path.is_symlink():
        result = validate_frontier(read_json(path))
    elif explicit:
        raise FrontierError('selected frontier snapshot does not exist')
    else:
        result = empty_frontier()
    attempt_path = path.parent / 'frontier-last-run.json'
    if attempt_path.exists() or attempt_path.is_symlink():
        attempt = validate_frontier(read_json(attempt_path))
        if result['generated_at'] is not None and result['demo'] != attempt['demo']:
            raise FrontierError('demo/live snapshots require separate data directories')
        old_time, new_time = parse_time(result['generated_at']), parse_time(attempt['generated_at'])
        failed = attempt['sources'] and all(source['status'] == 'error' for source in attempt['sources'])
        if new_time and (old_time is None or new_time >= old_time) and failed:
            if result['generated_at'] is None:
                result['demo'] = attempt['demo']
            result['sources'] = attempt['sources']
            result['last_attempt_at'] = attempt['generated_at']
            result['reused_latest'] = result['collected']
    return result

def demo_frontier(now=None):
    now = now or datetime.now(UTC)
    result = empty_frontier()
    result.update(generated_at=iso(now), collected=True, demo=True,
        items=[{'id': 'fictional/demo-agent#1', 'repo': 'fictional/demo-agent', 'title': 'Fictional agent release example',
                'url': 'https://example.com/fictional-agent-release', 'published_at': iso(now-timedelta(days=1)),
                'observed_at': iso(now), 'prerelease': True}],
        sources=[{'id': 'fictional/demo-agent', 'repo': 'fictional/demo-agent', 'url': 'https://example.com/fictional-releases',
                  'status': 'ok', 'checked_at': iso(now), 'detail': 'fictional_demo'}])
    return validate_frontier(result)

@contextmanager
def collection_lock(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    if data_dir.is_symlink():
        raise FrontierError('data directory cannot be symbolic')
    path = data_dir / '.frontier.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise FrontierError('collection is already locked; check any previous process before removing a stale lock') from None
    try:
        os.write(fd, str(os.getpid()).encode()); yield
    finally:
        os.close(fd); path.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', default='')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    try:
        proxy = validate_proxy(args.proxy)
        with collection_lock(args.data_dir):
            now = datetime.now(UTC)
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(lambda repo: collect_source(repo, proxy, now), REPOS))
            snapshot = empty_frontier()
            snapshot.update(generated_at=iso(now), collected=True, items=[item for items, _ in results for item in items],
                            sources=[source for _, source in results])
            updated = write_collection(args.data_dir, snapshot)
        print(json.dumps({'module_id': 'coding-graph', 'items': len(snapshot['items']), 'sources': {s['repo']: s['status'] for s in snapshot['sources']},
                          'latest_updated': updated, 'window_days': WINDOW_DAYS, 'per_repo_limit': PER_REPO}))
        return 0 if updated else 2
    except (FrontierError, OSError, UnicodeError) as exc:
        print('Frontier collection failed: ' + str(exc), file=__import__('sys').stderr)
        return 1
if __name__ == '__main__':
    raise SystemExit(main())
