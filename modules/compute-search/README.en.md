[简体中文](README.md) | [English](README.en.md)

# Compute value-chain research

Keep the value chain, GPU catalog rates and official updates in a compact page. Understand the businesses before choosing an investment route.

The default is **Codex light**, using Workhub typography and colors. Search, stage filtering and language selection share one toolbar. Each research card keeps a business model, indicators, one question and original material links.

## Use

Python 3.10 or newer is required. The module uses the standard library and needs no model key. Run inside the installed module:

```sh
# Fictional offline demo: no network or collection snapshot writes.
python3 bin/build_data.py --demo
```

Open `site/index.html`. Run real collection explicitly:

```sh
cp config.example.json config.json
python3 bin/collect.py --config config.json
python3 bin/build_data.py --input data/latest.json
```

The proxy is empty by default; edit `config.json` for your network. Collection accepts `--data-dir`; building accepts `--input` and `--output`. Pass the matching snapshot path when using a custom data directory. Collection with `--demo` requires a separate data directory. Demo and real data cannot mix.

## Three views

| View | Content |
| --- | --- |
| Value chain | Chips, memory, servers and networks, cloud, facilities, power and cooling, and end demand; seven cards and a glossary |
| GPU rates | Runpod Secure and Community catalog starting rates, with configuration, billing, sources and observation time |
| Updates | Official NVIDIA and AMD announcements, with publication dates and source health |

The research cards link to fourteen official material entry points. These links support active financial-report reading; they do not mean those companies' reports have been automatically collected. The current announcement feeds do not cover every stage. Coverage is not exhaustive across platforms or Chinese and US listed companies.

## Merge duplicates, retain differences

News sources are merged using canonical URLs or conservative same-title rules. Quotes remain distinct by provider, resource identity, GPU model, memory, GPU count, region, currency, unit and billing. Different terms remain separate. Similar material can still need manual review; deduplication is not event verification.

A catalog starting rate is not available inventory, a realized transaction price or an investment return. Undisclosed Runpod region and availability remain unknown. The module does not infer utilization or market supply and demand from price alone. See [research guidance](docs/research.en.md).

## Updates and failures

Four default endpoints cover two Runpod catalogs plus NVIDIA and AMD RSS. News uses a thirty-day window with up to fifty items per source. Collection has bounded concurrency and isolates source failures. `data/last-run.json` records the attempt; `data/latest.json` holds the usable snapshot.

When a source fails, its existing entries observed within the previous seventy-two hours may be retained and marked stale without refreshing their observation time. The retention window is configurable. If all sources fail, the previous usable snapshot is retained and collection exits with code `2`. A first failed attempt may leave no snapshot. Do not present missing or older material as a fresh result.

## Research with a CLI or API of your choice

The [research brief prompt](prompts/research-brief.en.md) requires sources, dates, boundaries between facts and inferences, counterexamples and next checks. Use your configured Codex, Z Code, Claude Code or API tool. The module itself calls no model, manages no model key and produces no buy or sell scores.

## Connect to Workhub

Build the page first. From the module repository, adjust your installed paths:

```sh
python3 manage.py connect compute-search \
  --installed ../workhub-local/compute-search --workhub ../workhub
```

Connection registers the project and site only. With manual admission in newer Workhub, choose the directory in Add project and add it to the workspace yourself. Following the portal's palette is an explicit option; the site also works independently.

Installation does not collect data, execute module code or create schedules. The public package includes source, sanitized examples, bilingual documentation and derived prompts only. Real quote snapshots, generated pages, personal configuration, logs, chats and tests are excluded.
