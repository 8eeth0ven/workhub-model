#!/usr/bin/env python3
"""Index one explicitly selected local Python project without executing it."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from graph_core import ROOT, GraphError, atomic_json, index_project


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT / 'data' / 'latest.json')
    p.add_argument('--max-files', type=int, default=500)
    p.add_argument('--max-bytes', type=int, default=10 * 1024 * 1024)
    args = p.parse_args()
    try:
        snapshot = index_project(args.project, args.max_files, args.max_bytes)
        atomic_json(args.output, snapshot)
        print(json.dumps({'module_id': 'coding-graph', 'files': len(snapshot['files']), 'nodes': len(snapshot['nodes']),
                          'edges': len(snapshot['edges']), 'unresolved': len(snapshot['unresolved']), 'partial': snapshot['codebase']['partial']}, ensure_ascii=False))
        return 0
    except (GraphError, OSError) as exc:
        print('Index failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
