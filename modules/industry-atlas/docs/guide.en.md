[简体中文](guide.md) | [English](guide.en.md)

# Data format and research workflow

Start with an answerable question, such as “What public evidence identifies manufacturing locations and substitute supply for this product class?” Select entities, add sourced attributes, then connect relationships. A large graph is useful only when its claims can be traced.

## Files and commands

Run from the installed module directory. `facts.json` is your reviewed input; `data/atlas.json` is local data; `site/index.html` is the generated page.

```sh
python3 bin/import_data.py --input facts.json --output data/atlas.json
python3 bin/build_data.py --input data/atlas.json
python3 bin/import_data.py --input update.json --output data/atlas.json --merge
python3 bin/build_data.py --input data/atlas.json
```

The first import may omit `--merge`; updating existing data requires it, because omitting it replaces the entire snapshot. With no explicit input and no default data, building produces an explicit empty state. Correct invalid explicit files rather than treating them as empty. `--demo` builds a clearly marked fictional demonstration. The page does not write data back; edit, import and rebuild the source JSON.

## Minimal data

Names, roles and the URL below are fictional; keep `demo: true` for this example.

```json
{
  "schema_version": 1,
  "module_id": "industry-atlas",
  "demo": true,
  "entities": [{
    "id": "sample-device",
    "name": "Fictional device A",
    "kind": "product",
    "industries": ["compute", "energy"],
    "aliases": [],
    "claims": [{
      "id": "sample-role-1",
      "field": "role",
      "value": "A fictional device used only to explain the format",
      "source_ids": ["sample-source"],
      "status": "disclosed",
      "valid_from": null,
      "valid_to": null,
      "observed_at": "2026-11-16",
      "note": "Fictional example, not an industry fact"
    }]
  }],
  "relations": [],
  "sources": [{
    "id": "sample-source",
    "title": "Fictional reference",
    "url": "https://example.com/industry-example",
    "kind": "primary",
    "published_at": null,
    "accessed_at": "2026-11-16",
    "independence_group": "sample-origin"
  }],
  "changes": []
}
```

Entity and claim IDs are stable and unique. Industries and kinds use extensible lowercase slugs. Common industries are `compute`, `automotive` and `energy`; an entity can span several. Aliases aid search without duplicating an entity.

## Attributes, time and status

Fields are extensible; unrecognized fields remain visible under their original names.

| Field | Meaning and scope |
| --- | --- |
| `role` / `principle` / `applications` | Role, operating principle and applications; define the object and scope |
| `headquarters_origin` | Headquarters location; does not fill other locations |
| `registered_origin` | Legal registration location |
| `design_origin` | Design location for a stated model or version |
| `manufacturing_origin` | Manufacturing location; distinguish company, plant, product and period |
| `raw_material_origin` | Material origin; state the material, stage and applicability |
| `specifications` / `capacity` / `lead_time` / `price` | Preserve units, definitions, dates and limits |
| `substitutes` | Substitute products or routes, with evidence and constraints |

Values may be JSON scalars, small arrays or objects, with at most six nesting levels and 4 KiB per value. Use `null` for unknowns. Missing does not automatically mean inapplicable; an evidenced inapplicability explanation may be recorded explicitly.

Dates use `YYYY-MM-DD` only. `observed_at` records when the material was observed. `valid_from` and `valid_to` describe the claim's applicability, with the end date inclusive; unknown bounds are `null`. Source publication and access dates remain separate. The page's latest recorded observation is the maximum recorded observation/access date, not a statement that every claim was refreshed together.

| Status | Meaning |
| --- | --- |
| `disclosed` | A source discloses it; this alone does not establish truth |
| `verified` | Marked multi-source; at least two distinct `independence_group` values are required, as a structural threshold only |
| `inferred` | Inference; document premises, reasoning and potential counterexamples |
| `hypothesis` | Hypothesis; record how to test it and keep it separate from facts |

Non-null values require source references except for hypotheses. Several reposts of one announcement share one origin; changing group labels does not create independence. Validation collapses whitespace and compares group labels without case distinctions, so those differences do not increase group counts. Groups are entered metadata, not software proof of independent evidence. `primary` denotes original material and `secondary` a retelling; original material can still be incomplete or wrong.

## Relationships and history

A relation has a stable ID, `source` and `target` entity IDs, an extensible `kind`, and an embedded full claim with `field: "relationship"`. Direction is source → target; the kind and claim define its meaning. “Uses” does not imply exclusive supply or causality. State the relevant product, period, stage and quantity definitions.

Correct a claim by adding a new claim ID and a change record:

```json
{
  "id": "change-1",
  "entity_id": "sample-device",
  "field": "manufacturing_origin",
  "previous_claim_id": "origin-old",
  "new_claim_id": "origin-new",
  "observed_at": "2026-11-16",
  "note": "New material changes the scope of the previous claim"
}
```

Both claims must exist and belong to the same entity and field. A relation claim belongs to its source entity; relation-history connections must also preserve the relationship kind. Merge does not silently rewrite a different record under the same ID; append a new ID. Claims without a change connection coexist and may conflict. The page places explicitly superseded claims in history; “not marked superseded” does not prove current truth or validity.

The graph expands one hop from the selected entity, up to 24 nodes and 36 edges. Orthogonal routes avoid unrelated node rectangles; if a clear route cannot be drawn, the page omits that line and says so while retaining list evidence. Relations can cross industries; the industry filter controls the entity list. Expand relation lists, claim groups and change records to inspect records beyond the initial batch.

## Six question dimensions

Select an attribute and expand Questions & verification. Rules inspect goals and object scope, distinct origin definitions, source groups and provenance, substitutes and counterexamples, cost/lead-time/margin/cash consequences, and publication/observation/validity/change boundaries. A missing manufacturing location asks for product- and period-specific plant evidence rather than substituting headquarters. Review model-prepared records against the originals before importing.

Input limits are 4 MiB, 2,000 entities, 5,000 relations, 1,000 sources, 10,000 claims and 10,000 changes. These are operating limits, not coverage goals. Missing records do not establish missing relations; recent material does not establish reliable conclusions.
