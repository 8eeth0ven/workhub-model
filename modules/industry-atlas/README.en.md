[简体中文](README.md) | [English](README.en.md)

# Industry atlas

Keep entities, roles, origins and relationships across compute, automotive, energy and other industries in one place, with sources, dates and change history for each claim, then ask concrete questions about the gaps.

Industries come from imported data, and an entity may span several industries. The compact bilingual interface shares Workhub's ten palettes, with Codex Light as default. Search, industry selection, Entities / Relations and expandable settings leave the content in view.

## Start

Requires Python 3.10+ and the standard library only. Run from the installed module directory:

```sh
python3 bin/build_data.py
```

Without data, the page explicitly says no industry facts have been imported. To see a **fully fictional** offline demonstration:

```sh
python3 bin/build_data.py --demo
```

Prepare data using the [format guide](docs/guide.en.md), then import and build:

```sh
python3 bin/import_data.py --input facts.json --output data/atlas.json
python3 bin/build_data.py --input data/atlas.json
```

Open `site/index.html`. From the module repository, connect to Workhub with:

```sh
python3 manage.py connect industry-atlas --installed ../my-industry-atlas --workhub ../workhub
```

Connecting registers the site. Workhub versions with manual admission still require the user to add it to the workspace. Installing or connecting does not read other projects, chats or subscription content, collect facts, or call a model.

## Inspect the evidence

- **Entities:** begin with names, types and one-line roles, then open structured attributes. Headquarters, registration, design, manufacturing and raw-material origins are separate. Missing origins are not inferred from headquarters.
- **Claims:** every attribute and relationship records status, observation date, validity and source references. Source publication and access dates remain distinct; unknown dates stay unknown.
- **Relations:** progressively inspect one hop around the selected entity, capped at 24 nodes and 36 edges. Select a node for its attributes and changes, or an edge/list entry for the original claim evidence; expand the list to inspect the rest. The graph omits claims marked superseded by a change record; historical relations remain in the list.
- **Changes:** retain old and new claims and connect them with a change record. Conflicting claims without a change connection coexist rather than being silently resolved.
- **Questions:** six rule-based dimensions provide questions and verification actions for scope, definitions, source independence, alternatives, consequences and time. They are not model judgments or a claim of complete industry coverage.

Disclosed, marked multi-source, inferred and hypothesis claims remain distinct. Multi-source status only requires at least two recorded source groups; independence and truth still need examination of the original materials. A relation does not automatically establish exclusive supply, causality or investment value.

## Update and use a model

```sh
python3 bin/import_data.py --input update.json --output data/atlas.json --merge
python3 bin/build_data.py --input data/atlas.json
```

The first import may omit `--merge`; use `--merge` to update existing data, because omitting it replaces the entire snapshot. Keep stable IDs when merging. Correct an attribute with a new claim and an explicit change connection, preserving the old claim. Give the [research prompt](prompts/industry-research.en.md) to your chosen CLI or API, then review its evidence before importing. This module stores no API key, calls no model automatically, and does not mark anyone as having understood the material.

Keep real datasets and generated pages local. Before public distribution, check names, paths, personal information, credentials and local data. Source packages contain only the empty state, fictional examples and reusable implementation.
