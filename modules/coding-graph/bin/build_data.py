#!/usr/bin/env python3
"""Render a bounded code graph and curated learning catalog as an offline page."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from graph_core import ROOT, GraphError, MAX_SNAPSHOT, demo_snapshot, read_json, validate_snapshot
from collect_updates import FrontierError, demo_frontier, empty_frontier, load_frontier, validate_frontier


def unindexed_snapshot():
    return {'schema_version': 1, 'module_id': 'coding-graph', 'mode': 'live',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'codebase': {'label': 'No project indexed', 'file_count': 0,
                         'fingerprint': hashlib.sha256(b'[]').hexdigest(), 'partial': False,
                         'indexed': False, 'warnings': ['No project has been indexed.']},
            'files': [], 'nodes': [], 'edges': [], 'unresolved': []}


def script_json(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            .replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def _validate_catalog(value):
    if not isinstance(value, dict) or not isinstance(value.get('topics'), list) or not isinstance(value.get('resources'), list):
        raise GraphError('invalid learning catalog')
    if len(value['topics']) > 50 or len(value['resources']) > 200:
        raise GraphError('learning catalog exceeds limits')
    def bilingual(item):
        return isinstance(item, dict) and all(isinstance(item.get(k), str) and 0 < len(item[k]) <= 2000 for k in ('zh-CN', 'en'))
    topics, ids, urls = set(), set(), set()
    for t in value['topics']:
        if not isinstance(t, dict) or not isinstance(t.get('id'), str) or not re.fullmatch('[a-z0-9-]+', t['id']) or t['id'] in topics or t.get('track') not in {'coding', 'graph'} or not bilingual(t.get('name')):
            raise GraphError('invalid or duplicate learning topic')
        topics.add(t['id'])
    resources = []
    for r in value['resources']:
        if not isinstance(r, dict) or not isinstance(r.get('id'), str) or r['id'] in ids or r.get('topic') not in topics or r.get('level') not in {'beginner', 'intermediate', 'advanced'}:
            raise GraphError('invalid learning resource')
        if any(not bilingual(r.get(k)) for k in ('title', 'summary', 'practice', 'self_check')):
            raise GraphError('learning resources require bilingual fields')
        try:
            u = urlsplit(r['url'])
            if u.scheme != 'https' or not u.hostname or u.username or u.password or any(ord(c) < 32 for c in r['url']):
                raise ValueError()
            u.port
        except (KeyError, TypeError, ValueError):
            raise GraphError('resource links require public HTTPS URLs') from None
        ids.add(r['id'])
        canonical = (u.hostname.casefold(), u.path.rstrip('/'), u.query)
        if canonical not in urls:
            resources.append(r)
            urls.add(canonical)
    return dict(value, resources=resources)


def validate_catalog(value):
    try:
        return _validate_catalog(value)
    except (TypeError, KeyError, AttributeError, OverflowError):
        raise GraphError('invalid catalog field types') from None


def render(snapshot, catalog, template, css, theme, frontier=None):
    replacements = {'__DATA_JSON__': script_json(validate_snapshot(snapshot)), '__CATALOG_JSON__': script_json(validate_catalog(catalog)),
                    '__FRONTIER_JSON__': script_json(validate_frontier(frontier if frontier is not None else empty_frontier())),
                    '__WORKHUB_DESIGN_CSS__': css, '__WORKHUB_THEME_JS__': theme}
    for marker in replacements:
        if template.count(marker) != 1:
            raise GraphError('template requires each marker exactly once')
    # One substitution pass: marker-looking data must remain data.
    return re.sub('|'.join(map(re.escape, replacements)), lambda m: replacements[m.group(0)], template)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=None)
    p.add_argument('--output', type=Path, default=ROOT / 'site' / 'index.html')
    p.add_argument('--demo', action='store_true')
    p.add_argument('--frontier', type=Path, default=None, help='explicit release snapshot; defaults only to this module data/frontier.json')
    args = p.parse_args()
    try:
        if args.demo and args.input:
            raise GraphError('--demo and --input are mutually exclusive')
        graph_path = args.input or ROOT / 'data' / 'latest.json'
        snapshot = (demo_snapshot() if args.demo else
                    unindexed_snapshot() if args.input is None and not graph_path.exists() and not graph_path.is_symlink() else
                    validate_snapshot(read_json(graph_path)))
        frontier = (demo_frontier() if args.demo and args.frontier is None else
                    load_frontier(args.frontier or ROOT / 'data' / 'frontier.json', explicit=args.frontier is not None))
        catalog = read_json(ROOT / 'catalog.json', 1024 * 1024)
        assets = []
        for name in ('site.template.html', 'site/design-system.css', 'site/embedded-theme.js'):
            path = ROOT / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                raise GraphError('missing or oversized source asset')
            assets.append(path.read_text(encoding='utf-8'))
        page = render(snapshot, catalog, *assets, frontier=frontier)
        # Write the HTML atomically without creating runtime data in the source tree.
        import os, tempfile
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink() or args.output.parent.is_symlink():
            raise GraphError('output cannot be symbolic')
        fd, temporary = tempfile.mkstemp(prefix='.graph-site-', dir=args.output.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(page)
            os.replace(temporary, args.output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(json.dumps({'module_id': 'coding-graph', 'mode': snapshot['mode'], 'nodes': len(snapshot['nodes']), 'edges': len(snapshot['edges']), 'resources': len(validate_catalog(catalog)['resources']), 'frontier_items': len(frontier['items']), 'frontier_collected': frontier['collected'], 'frontier_demo': frontier['demo']}))
        return 0
    except (GraphError, FrontierError, OSError, UnicodeError) as exc:
        print('Build failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
