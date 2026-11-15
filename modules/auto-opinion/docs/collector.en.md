[简体中文](collector.md) | [English](collector.en.md)

# Collection and daily reports

The collector reads public headlines, source links and necessary metadata. It does not download full news articles or require an LLM key. Run it with Python 3.10 or newer; neither curl nor third-party packages are required.

From the module directory:

```sh
python3 bin/collect.py --demo --data-dir /path/to/demo-data
python3 bin/collect.py --data-dir /path/to/auto-opinion-data
```

The first command generates a clearly fictional example without network access. The second contacts public sources. Without `--data-dir`, runtime data goes into the module's `data/` directory, which is excluded from published source.

Demo and live collection must use separate data directories. Existing snapshots and a directory mode marker are checked before collection, and both directions of mixing are rejected. A demo cannot overwrite live reports, and live collection cannot retain fictional records as historical evidence. A directory holding only legacy Markdown reports with an unknown mode is also rejected. The commands above deliberately use different `--data-dir` values. If the default `data/` already holds a demo, choose a new directory for live collection and pass the same new directory to the dashboard builder.

## Sources and networking

The default selection contains 13 sources: ten Google News RSS queries (three Li Auto, four domestic manufacturers and three international automotive queries), Electrek, Carscoops and automotive-related Baidu trending topics. Availability depends on those services and the user's network; a listed source is not guaranteed to respond on every run.

Connections are direct by default. Ambient proxy environment variables are deliberately ignored. Set an explicit HTTP(S) `proxy` in a private configuration file or use `--proxy` for international sources. Baidu always connects directly. A failed proxy does not silently fall back to a direct connection; enable `proxy_fallback_direct: true` explicitly if wanted. Do not publish private configuration files or actual proxy addresses.

Copy `config.example.json` to a private location outside the publication directory, edit it, then run:

```sh
python3 bin/collect.py --config /path/to/private-config.json --data-dir /path/to/auto-opinion-data
```

Configuration controls the freshness window, report timezone, concurrency, request timeout, retry count and per-source item limit. Optional `enabled_sources` selects source IDs: `google-01` through `google-10`, `electrek`, `carscoops`, and `baidu`. For a bounded diagnostic, use `--source electrek --source baidu --timeout 5 --retries 0`. Concurrency defaults to four and is capped at eight. Transient network/timeouts, empty responses and selected temporary HTTP errors get one retry by default. Response sizes are bounded, and one source failure does not cancel the others.

## Dates, deduplication and risk clues

RSS items need a parseable publication timestamp with a timezone. The default freshness window is the exact preceding 72 hours in UTC. Missing, future and older dates are counted separately and rejected; a failed date parse is never treated as a current article. Baidu trending topics lack a reliable publication time, so their `published_at` is `null`; `observed_at` and `time_basis: observed` explain when they were seen instead.

Normalized identical titles are deduplicated deterministically across sources. This does not claim to merge every differently worded report about the same event. Headline keywords mark high-risk, medium-risk, positive or neutral clues. English matches respect word boundaries, so `firewall` does not match `fire`. Tags are unverified clues rather than factual findings, legal conclusions or comprehensive sentiment analysis. A missing negative match still requires manual review of source coverage and the Li Auto section.

## Output and failures

JSON uses `schema_version: 1` and includes `generated_at`, `report_date`, `window_days`, `is_demo`, `coverage`, `items` and `sources`.

| Source state | Meaning |
| --- | --- |
| `ok` | Request and parsing succeeded and eligible new titles were retained. |
| `empty` | Request and parsing succeeded, but there were no entries, no eligible recent entries or only duplicates; a reason is retained. |
| `error` | Networking, HTTP, parsing or response limits failed. `error_code` and `attempts` retain categories without raw remote error text. |

Coverage is `complete` when all selected sources could be parsed, `partial` when some failed, and `unavailable` when all failed. Complete request coverage is not a claim that all relevant news was collected.

- `YYYY-MM-DD.json` and `YYYY-MM-DD.md` retain a daily snapshot. The report date defaults to `Asia/Shanghai`.
- `latest.json` and `最新日报.md` hold the most recent run with at least one parseable source.
- `last-run.json` describes every attempt, including a total failure. The dashboard must read it as well so old content is not presented as fresh.

A total failure preserves an existing latest snapshot and existing same-day files. `last-run.json` records `unavailable`, `reused_latest` and the previous snapshot time. A first run that fails does not invent successful latest data; a failure-only dated report may be written when no daily snapshot exists. The collector exits with code 2 for total failure, or 0 when a source could be parsed or an offline demo was generated.

Files are individually replaced atomically, and `.collect.lock` prevents concurrent collectors writing the same directory. After a forced termination, remove a stale lock only after checking that no collector is active. The collector does not install or modify scheduled jobs and does not delete report history automatically. The dashboard separately selects its documented 14-calendar-day window.
