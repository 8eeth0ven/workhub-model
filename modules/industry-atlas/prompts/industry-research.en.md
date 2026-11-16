[简体中文](industry-research.md) | [English](industry-research.en.md)

# Industry research and evidence prompt

Give this to your chosen CLI or LLM API. The module does not execute it automatically or implicitly read local projects, chats, subscription material or credentials.

```text
Act as my industry research partner. Question: <specific question>. Industry: <compute/automotive/energy/other>. Scope: <entities, models, geography and period>.

Define the question boundary and completion criteria. Use accessible public primary evidence where needed; do not fill gaps with assumptions. Prioritize auditable key attributes over an apparently complete large graph.

Output JSON using industry-atlas docs/guide.en.md: schema_version=1 and module_id=industry-atlas. Real material uses demo=false. Keep fictional teaching examples separately with demo=true; never mix them into real records.

Give each entity a stable ID, name, kind, industries and aliases. Explain its role, principle, uses and constraints. Separate headquarters, registration, design, manufacturing and raw-material origins. Bind each location to its company/plant/product/material/period; do not substitute headquarters for origin. Use null for unknowns and state the evidence needed.

Each attribute or relation is a claim with stable ID, field, value, source_ids, status, valid_from, valid_to, observed_at and note. Use YYYY-MM-DD dates and null for unknown bounds. Observation dates are not event dates. Preserve units, definitions and applicable periods for prices, capacities and lead times.

Use only disclosed/verified/inferred/hypothesis statuses. Disclosure is not truth. Explain inference premises and steps; give a test for hypotheses. verified requires at least two genuinely independent source groups, without splitting reposts into separate groups. Group count is a structural threshold, not software proof of facts.

For each source retain stable ID, title, original HTTPS URL, primary/secondary kind, publication date (null if unknown), access date and independence_group. Trace reposts to the original publisher and identify shared upstream material. If only an abstract or paywall excerpt is accessible, state that limit instead of pretending to read the full text.

Relations use source→target, an explicit kind and an embedded field=relationship claim, with evidence for product, period and scope. Do not turn cooperation disclosure into exclusive supply, certain causality or investment value. Look for substitutes and potentially disconfirming evidence.

For existing records, read only the files I explicitly provide. Preserve IDs and prior claims. Correct with new claims and changes connections rather than overwriting history. Retain conflicting claims without a supersession connection and explain them. Do not read other files, chats or keys without authorization.

Provide six Socratic question dimensions, each with an actionable verification step: goals/scope, definitions, evidence independence, alternatives/counterexamples, cost/lead-time/margin/cash consequences, and temporal/missing boundaries. State what the evidence cannot answer. Do not invent scores or claim human checks were completed.

Deliver valid JSON, a short sources/gaps note and six question dimensions. Check references, ID closure, dates and change links before providing import commands. Do not place orders, run collectors, install tools, submit or publish my local data automatically.
```
