[简体中文](collector.md) | [English](collector.en.md)

# AI product collection and incremental briefs

The collector reads public headlines, links, sources and timestamps, not full articles. It uses the Python 3.10+ standard library and needs no model key. It does not create or modify schedules.

```sh
# Fictional offline data stays separate.
python3 bin/collect.py --demo --data-dir demo/data
python3 bin/build_data.py --data-dir demo/data

# Live collection uses a different directory.
cp config.example.json config.json
python3 bin/collect.py --config config.json
python3 bin/build_data.py
```

The defaults are the module's `data/` and `site/` directories. Pass the same `--data-dir` to collector and builder when customizing it. Real configuration, reports, logs and generated pages are local runtime material, excluded from source and ZIP publication.

## Twenty-five inputs

There are 23 Google News query groups: seven domestic-product/model groups, seven international-product groups, two hardware/robotics groups and seven AI-personality statement groups. TechCrunch AI RSS and filtered Baidu trends bring the total to 25. Statement queries group the person, AI context and speaking terms separately to reduce unrelated generic statements; keyword relevance is still heuristic.

RSS items must have a timezone-aware publication date in the exact previous 48 hours. Unknown, future and out-of-window dates are rejected separately. Each source accepts at most 25 items. Baidu trends lack a trustworthy publication date, so they use `published_at: null`, `observed_at` and `time_basis: observed`.

Latin keywords use boundaries, preventing `AI` from matching inside `said` or `training`. Risk/positive colors flag headline keywords rather than establish facts or a complete sentiment assessment.

## Network and health

Direct access is the default; ambient proxy variables are ignored. Configure a private `proxy` or pass `--proxy` explicitly. Baidu remains direct. Proxy failure does not silently switch routes unless `proxy_fallback_direct: true` is explicitly configured.

Settings include `window_days`, `timezone`, `workers`, `timeout_seconds`, `retries`, `proxy`, `proxy_fallback_direct` and `max_items_per_source`. Optional `enabled_sources` selects known IDs: `google-01` through `google-23`, `techcrunch-ai`, and `baidu`.

```sh
python3 bin/collect.py --source techcrunch-ai --source baidu --timeout 5 --retries 0
```

Default concurrency is four, limited to eight. Each request defaults to 15 seconds and one retry; zero to two retries are configurable. Reading enforces the remaining total budget and a body-size limit. Truncated or malformed HTTP responses remain per-source errors rather than terminating the whole batch.

- `ok`: the request and parsing succeeded and accepted headlines.
- `empty`: parsing succeeded but there were no entries, no eligible matches or only duplicates; a reason is recorded.
- `error`: network, HTTP, parsing, protocol or response-limit failure. Only a controlled error category is retained.

Complete/partial/unavailable describes the selected inputs for this run, not complete news coverage. All-source failure exits with code 2; at least one parsable input or an offline demo exits with code 0.

## Compare runs within the same day

Every run has its own `run_id`. Each usable report embeds its own `delta`, bound to that run; historical dates must not receive an unrelated global delta.

| File | Meaning |
| --- | --- |
| `latest.json`, `最新日报.md` | Latest usable snapshot |
| `previous.json` | The preceding usable snapshot; failed attempts do not advance it |
| `last-run.json` | Most recent attempt, including all-source failure |
| `delta.json`, `增量简报.md` | The corresponding attempt's incremental summary |
| `YYYY-MM-DD.json`, `YYYY-MM-DD.md` | Latest usable report for the date, overwritten by later successful runs that day |
| `seen-index.json` | Observed-content index, bounded to 14 days and 10,000 entries |
| `.collection-state.json` | Atomically committed usable report, previous report and index, from which flat views can recover |

Content IDs belong to canonical URLs with tracking parameters removed. Normalized-headline aliases suppress repeated headlines at different sources without asserting that distinct URLs prove the same real-world event. A changed title or keyword label at the same URL is `changed`; source attribution, section, order and observation time alone are not.

With a usable recent baseline, `delta` contains `new_ids`, `changed_ids`, `unchanged_ids` and counts. With no valid baseline in the comparison window, current items are `baseline`, not claims of newly discovered events. `baseline_reason` is missing, expired, future or available. A usable snapshot older than 14 days or dated in the future is not a valid comparison baseline.

The seen index retains at most 14 days, 10,000 URL identities and eight hashed aliases per identity. This prevents a source returning after a partial run from unnecessarily resurfacing known headlines as new. Missing coverage never produces a removed-event claim. An invalid index explicitly falls back to the preceding usable snapshot. Fingerprint changes require source verification before being described as substantive developments.

All-source failure sets `comparison_skipped: true` and leaves the successful baseline, previous report and seen history unadvanced. Retained material must not be presented as current news. The successful checkpoint commits atomically; JSON and Markdown mirrors recover on the next run after an interrupted write, preventing an index from silently advancing ahead of its usable report. Each output file is limited to 24 MiB.

## Directory isolation

Mode markers, reports and deltas carry `module_id: ai-opinion` and `is_demo`. Demo/live mixing is refused in both directions, as is automotive-module data. A legacy Markdown-only directory, unknown identity or corrupted state requires review or a new directory; migration is not guessed. `.collect.lock` rejects concurrent collectors. Remove a stale lock only after confirming no collector remains active.

The collector does not send data to an LLM. Optional briefs use the user's chosen agent and the included prompt. Scheduling is an explicit separate action, not a guarantee of availability or quality.
