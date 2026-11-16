[简体中文](README.md) | [English](README.en.md)

# Code & graph learning

Research advanced AI-native engineering by combining public project updates, advanced primary resources and local code relationships, then test which methods fit your work.

Codex Light is the default, with compact bilingual controls and shared palettes. Frontier updates are the default view, alongside code search, relationships and resources. The 17 advanced official resources cover agents, long-task context, tools/runtime, evaluations, training feedback, code graphs, GraphRAG and temporal memory. Beginner syntax courses are not default content. Duplicate normalized URLs merge; links do not install tools.

## Start

Requires Python 3.10+ and the standard library only. Generate clearly fictional offline material from the installed module directory:

```sh
python3 bin/build_data.py --demo
```

Replace the placeholder with your project root. Indexing reads bounded Python files within that selected root without executing project code:

```sh
python3 bin/index_code.py --project /path/to/your-project
python3 bin/build_data.py
```

Open `site/index.html`, or run from the module repository:

```sh
python3 manage.py connect coding-graph --installed ../my-coding-graph --workhub ../workhub
```

Connecting only registers the site. Workhub versions with manual admission still require the user to add it to the workspace. Installation does not index or create a schedule.

## Frontier updates and evidence

```sh
python3 bin/collect_updates.py
python3 bin/build_data.py
```

Read one page of at most six releases from each of seven fixed official GitHub repositories, then filter by publication time within 90 days. This bounded sample does not promise every release in that window or the strictly newest six. Preserve publication and collection times, source links and prerelease labels. Missing snapshots explicitly show not collected. `--proxy` is optional; collection does not use environment proxies or require a key. This is not web-wide search, and no release does not establish no project activity. Complete failure retains the previous snapshot and its observation time, with separate source health.

Do not rank capability by recency or stars. Each advanced resource has a project experiment and a counter-question; preserve task, model, environment, budget and evaluation definitions. Explain foundational concepts only when needed for a concrete implementation.

## Search code and practice graphs

The CLI provides `query`, `context`, `impact` and `trace`. The page searches symbols and resources, displays selected-node relationships, follows directed shortest paths and inspects reverse impact. Calls are the default relation kind; paths across all relations are not execution traces. See the [guide and limits](docs/guide.en.md) for arguments.

Version one parses Python only. Its bounded static approximation leaves dynamic calls, ambiguity, shadowing and unsupported constructs unresolved. Missing edges do not establish missing runtime calls, and static matches do not prove execution. File hashes and indexing times identify the snapshot; re-index after source changes.

[GitNexus](https://github.com/abhigyanpatwari/GitNexus) inspired the search, context, impact and path workflow. This is an independent Python AST implementation; it does not bundle GitNexus, its MCP, semantic vector retrieval, Cypher engine or multi-language parsers. The referenced repository currently lists PolyForm Noncommercial 1.0.0; read its license before using its software. No GitNexus source is copied here.

## Learn and keep data local

Each resource has one exercise and a self-check. Give the [learning prompt](prompts/code-learning.en.md) to your chosen CLI/API for source-linked explanations and explicit unknowns; this module does not call a model automatically. Users mark their own Workhub learning cards as understood; searching or playback does not establish learning.

Real indexes, project names, graphs and generated pages stay local and are excluded from source packages. The indexer bounds files, bytes, nodes and edges, skips private/runtime directories and symlinks, and reports limits or file failures. Do not publish a real code index in place of source.
