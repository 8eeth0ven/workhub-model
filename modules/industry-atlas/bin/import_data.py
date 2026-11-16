#!/usr/bin/env python3
"""Import one selected industry JSON document, optionally appending claims."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from atlas_core import AtlasError, atomic_json, merge_atlases, output_lock, read_json, validate_atlas


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--merge', action='store_true')
    args = p.parse_args()
    try:
        with output_lock(args.output):
            incoming = read_json(args.input)
            if args.merge and (args.output.exists() or args.output.is_symlink()):
                data = merge_atlases(read_json(args.output), incoming)
            else:
                data = validate_atlas(incoming)
            atomic_json(args.output, data)
        print(json.dumps({'module_id': 'industry-atlas', 'demo': data['demo'], 'entities': len(data['entities']),
                          'relations': len(data['relations']), 'sources': len(data['sources']), 'changes': len(data['changes']), 'merged': args.merge}))
        return 0
    except (AtlasError, OSError, UnicodeError) as exc:
        print('Import failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
