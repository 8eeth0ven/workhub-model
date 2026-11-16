#!/usr/bin/env python3
"""Build an offline compute research page from explicitly bounded local JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

from collect import ROOT, MAX_BYTES, STAGES, clean_snapshot, demo_snapshot, parse_time, public_url, read_json, text


def script_json(value) -> str:
    # JSON strings can contain HTML closing-script text. Escape before embedding.
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            .replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def clean_research(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('stages'), list) or not isinstance(raw.get('glossary'), list):
        raise ValueError('invalid research catalog')
    def bilingual(value, limit=500):
        if not isinstance(value, dict) or any(not text(value.get(language)) for language in ('zh-CN', 'en')):
            raise ValueError('research fields require Chinese and English')
        return {language: text(value[language], limit) for language in ('zh-CN', 'en')}
    stages, seen = [], set()
    for stage in raw['stages']:
        if not isinstance(stage, dict) or stage.get('id') not in STAGES or stage['id'] in seen:
            raise ValueError('invalid or duplicate research stage')
        seen.add(stage['id'])
        links = []
        for link in stage.get('links', [])[:12]:
            if not isinstance(link, dict) or not public_url(link.get('url')):
                raise ValueError('invalid research reference')
            links.append({'name': text(link.get('name'), 100), 'url': public_url(link['url'])})
        if not isinstance(stage.get('indicators'), list) or len(stage['indicators']) > 8:
            raise ValueError('invalid research indicators')
        stages.append({'id': stage['id'], 'name': bilingual(stage.get('name'), 100),
                       'business': bilingual(stage.get('business')), 'indicators': [bilingual(i, 200) for i in stage['indicators']],
                       'question': bilingual(stage.get('question')), 'links': links})
    if seen != STAGES:
        raise ValueError('research catalog must contain all seven stages')
    glossary = []
    for word in raw['glossary'][:40]:
        if not isinstance(word, dict) or not text(word.get('term')):
            raise ValueError('invalid glossary')
        glossary.append({'term': text(word['term'], 80), **bilingual(word)})
    return {'stages': stages, 'glossary': glossary}


def load_snapshot(path: Path):
    snapshot = clean_snapshot(read_json(path))
    # Only the sibling last-run of the selected input may update health. Never scan
    # unrelated project folders, logs or historical sessions.
    attempt_path = path.parent / 'last-run.json'
    if attempt_path.exists() and attempt_path != path:
        attempt = clean_snapshot(read_json(attempt_path))
        if attempt['mode'] != snapshot['mode']:
            raise ValueError('last-run mode mismatch')
        newer = parse_time(attempt['generated_at']) > parse_time(snapshot['generated_at'])
        same_time_failure = (attempt['generated_at'] == snapshot['generated_at']
                             and bool(attempt['sources']) and all(s['status'] == 'error' for s in attempt['sources']))
        if newer or same_time_failure:
            snapshot['sources'] = attempt['sources']
            snapshot['last_attempt_at'] = attempt['generated_at']
            snapshot['reused_latest'] = True
            failed = {s['id'] for s in attempt['sources'] if s['status'] == 'error'}
            for item in snapshot['items']:
                if item['source_id'] in failed:
                    item['stale'] = True
    return snapshot


def build(snapshot, research, template, css, theme):
    replacements = {'__DATA_JSON__': script_json(snapshot), '__RESEARCH_JSON__': script_json(research),
                    '__WORKHUB_DESIGN_CSS__': css, '__WORKHUB_THEME_JS__': theme}
    for marker in replacements:
        if marker not in template:
            raise ValueError('missing template marker: ' + marker)
    # Substitute once: an untrusted headline containing a template marker must
    # remain literal data and must never be interpreted as another placeholder.
    pattern = '|'.join(re.escape(marker) for marker in replacements)
    return re.sub(pattern, lambda match: replacements[match.group(0)], template)


def atomic_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('output cannot be symbolic')
    descriptor, temporary = tempfile.mkstemp(prefix='.compute-site-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='a compute-search snapshot; defaults to data/latest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'site' / 'index.html')
    parser.add_argument('--demo', action='store_true', help='generate a clearly fictional demo without fetching or writing data')
    args = parser.parse_args()
    try:
        if args.demo and args.input:
            raise ValueError('--demo and --input are mutually exclusive')
        snapshot = demo_snapshot() if args.demo else load_snapshot(args.input or ROOT / 'data' / 'latest.json')
        research = clean_research(read_json(ROOT / 'research.json'))
        for relative in ('site.template.html', 'site/design-system.css', 'site/embedded-theme.js'):
            source = ROOT / relative
            if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BYTES:
                raise ValueError('missing or invalid source asset')
        page = build(snapshot, research, (ROOT / 'site.template.html').read_text(encoding='utf-8'),
                     (ROOT / 'site/design-system.css').read_text(encoding='utf-8'),
                     (ROOT / 'site/embedded-theme.js').read_text(encoding='utf-8'))
        atomic_text(args.output, page)
        print(json.dumps({'module_id': 'compute-search', 'mode': snapshot['mode'], 'item_count': len(snapshot['items']),
                          'stage_count': len(research['stages']), 'reused_latest': snapshot.get('reused_latest', False)}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print('Build failed: ' + str(exc), file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
