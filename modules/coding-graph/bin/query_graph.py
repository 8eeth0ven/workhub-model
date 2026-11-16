#!/usr/bin/env python3
"""Query a local graph snapshot; results include static source evidence."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from graph_core import ROOT, GraphError, context, impact, query, read_json, trace, validate_snapshot


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=ROOT / 'data' / 'latest.json')
    sub = p.add_subparsers(dest='command', required=True)
    search = sub.add_parser('query')
    search.add_argument('text')
    search.add_argument('--limit', type=int, default=30)
    for name in ('context', 'impact', 'trace'):
        s = sub.add_parser(name)
        s.add_argument('source')
        if name == 'trace':
            s.add_argument('target')
        if name == 'impact':
            s.add_argument('--hops', type=int, default=3)
        s.add_argument('--edge-kind', choices=('calls', 'imports', 'contains', 'all'), default='calls')
    args = p.parse_args()
    try:
        data = validate_snapshot(read_json(args.input))
        if args.command == 'query':
            result = query(data, args.text, args.limit)
        elif args.command == 'context':
            result = context(data, args.source, args.edge_kind)
        elif args.command == 'impact':
            result = impact(data, args.source, args.hops, args.edge_kind)
        else:
            result = trace(data, args.source, args.target, args.edge_kind)
        result.update(module_id='coding-graph', generated_at=data['generated_at'], fingerprint=data['codebase']['fingerprint'])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (GraphError, OSError) as exc:
        print('Query failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
