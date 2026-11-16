[简体中文](guide.md) | [English](guide.en.md)

# Guide and limits

Index a small project or an explicitly selected directory, verify one known function, then use the graph to expand your reading. This module searches static code relationships and a learning catalog, not the entire computer or chat history.

```sh
python3 bin/query_graph.py --input data/latest.json query "parse"
python3 bin/query_graph.py --input data/latest.json context UNIQUE_SYMBOL
python3 bin/query_graph.py --input data/latest.json impact UNIQUE_SYMBOL --hops 2
python3 bin/query_graph.py --input data/latest.json trace FROM_SYMBOL TO_SYMBOL
```

Selectors are node IDs or unique qualified names; ambiguous names fail explicitly. `--edge-kind calls|imports|contains|all` defaults to calls and applies to context, impact and trace.

| Relation | Meaning | Limit |
| --- | --- | --- |
| contains | Syntactic containment | Does not establish a call |
| imports | Static imports between indexed modules | Does not prove execution |
| calls | Conservatively matched call-expression targets | Does not establish runtime behavior |

Trace performs directed, unweighted BFS and returns one path with the fewest edges. Impact follows reverse edges with a hop limit. Both cover only resolved edges. No path means none was found in the selected graph. Visual truncation and index coverage are separate limits.

The catalog contains 17 advanced AI-native engineering resources with original experiments and self-checks. Beginner programming tutorials are not default content. A separate collector reads one page of at most six releases from each of seven official repositories, then filters to 90 days. It does not promise the full window or the strictly newest six, and preserves prerelease, empty, failure and retained-data states. It does not cover every paper, commit or industry event. GraphRAG, temporal graphs and MCP are research material, not fully implemented systems here.

Official GitNexus references: [README](https://github.com/abhigyanpatwari/GitNexus), [MCP tools](https://github.com/abhigyanpatwari/GitNexus/blob/main/docs/mcp-reference.md), [architecture](https://github.com/abhigyanpatwari/GitNexus/blob/main/ARCHITECTURE.md), [license](https://github.com/abhigyanpatwari/GitNexus/blob/main/LICENSE). This version borrows workflow ideas only; it does not install, copy or claim the same coverage as GitNexus.
