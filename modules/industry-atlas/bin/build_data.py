#!/usr/bin/env python3
"""Build a local evidence atlas without calling models or collecting private files."""
from __future__ import annotations
import argparse
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from atlas_core import ROOT, AtlasError, empty_atlas, read_json, validate_atlas


def script_json(data):
    return (json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            .replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def loopback_origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username is not None or parsed.password is not None or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment or '\\' in value or any(ord(c) < 33 for c in value)):
            raise ValueError()
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        host = '[' + parsed.hostname + ']' if parsed.hostname == '::1' else parsed.hostname
        suffix = '' if port is None or (parsed.scheme, port) in {('http', 80), ('https', 443)} else ':' + str(port)
        return parsed.scheme + '://' + host + suffix
    except (TypeError, ValueError):
        raise AtlasError('parent origin must be a loopback HTTP(S) origin without credentials or path') from None


def render(data, template, css, theme, parent_origin=''):
    if parent_origin:
        origin = loopback_origin(parent_origin)
        root = re.search(r'<html\b[^>]*>', template, flags=re.I)
        if root is None or 'data-workhub-parent-origin' in root.group(0):
            raise AtlasError('template requires one unconfigured html root')
        template = template[:root.start()] + root.group(0).replace('>', ' data-workhub-parent-origin="' + html.escape(origin, quote=True) + '">', 1) + template[root.end():]
    replacements = {'__ATLAS_JSON__': script_json(validate_atlas(data)), '__WORKHUB_DESIGN_CSS__': css, '__WORKHUB_THEME_JS__': theme}
    for marker in replacements:
        if template.count(marker) != 1:
            raise AtlasError('template requires each marker exactly once')
    return re.sub('|'.join(map(re.escape, replacements)), lambda m: replacements[m.group(0)], template)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path, default=ROOT / 'site' / 'index.html')
    p.add_argument('--demo', action='store_true')
    p.add_argument('--parent-origin', default='', help='optional loopback Workhub origin for language messages')
    args = p.parse_args()
    try:
        if args.demo and args.input:
            raise AtlasError('--demo and --input are mutually exclusive')
        source = args.input or ROOT / 'data' / 'atlas.json'
        if args.demo:
            data = validate_atlas(read_json(ROOT / 'starter.json'))
            if data['demo'] is not True:
                raise AtlasError('starter must be explicitly marked as a fictional demo')
        elif args.input is None and not source.exists() and not source.is_symlink():
            data = empty_atlas()
        else:
            data = validate_atlas(read_json(source))
        assets = []
        for name in ('site.template.html', 'site/design-system.css', 'site/embedded-theme.js'):
            path = ROOT / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ASSET_BYTES:
                raise AtlasError('missing or oversized source asset')
            assets.append(path.read_text(encoding='utf-8'))
        page = render(data, *assets, parent_origin=args.parent_origin)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.suffix != '.html' or args.output.is_symlink() or args.output.parent.is_symlink():
            raise AtlasError('page output must be a regular .html location')
        fd, temporary = tempfile.mkstemp(prefix='.atlas-site-', dir=args.output.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(page)
            os.replace(temporary, args.output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(json.dumps({'module_id': 'industry-atlas', 'demo': data['demo'], 'entities': len(data['entities']), 'relations': len(data['relations']), 'sources': len(data['sources']), 'changes': len(data['changes'])}))
        return 0
    except (AtlasError, OSError, UnicodeError) as exc:
        print('Build failed: ' + str(exc), file=sys.stderr)
        return 1


MAX_ASSET_BYTES = 2 * 1024 * 1024
if __name__ == '__main__':
    raise SystemExit(main())
