[简体中文](README.md) | [English](README.en.md)

# Automotive opinion monitoring

Bring public automotive headlines, relevant trends and source health into a local dashboard that can connect to Workhub.

Workhub’s existing Codex Light is the default: white content, light gray surfaces and dark text, sharing Workhub’s compact layout and palette system. Existing saved color preferences are preserved.

## Use

```sh
# Offline fictional demo; no requests to news sources.
python3 bin/collect.py --demo --data-dir demo/data
python3 bin/build_data.py --data-dir demo/data
```

Open `site/index.html`. For live collection:

```sh
cp config.example.json config.json
python3 bin/collect.py --config config.json
python3 bin/build_data.py
```

Demo data uses `demo/data/`; live collection defaults to `data/`. Do not mix them in one directory. The example proxy is empty; configure your own if required. Both commands accept `--data-dir`; the builder also accepts `--output-dir`. Defaults are the module's `data/` and `site/` directories. Do not commit real configuration, reports, logs or generated dashboards.

## Read

| Section | Contents |
| --- | --- |
| Negative signals | High- and medium-risk title keywords that need source verification |
| Li Auto | Products, deliveries, sales and related discussion |
| Domestic manufacturers | Chinese manufacturers and industry news |
| International | International brands and EV news |
| Trends | Automotive topics filtered from Baidu trends |

The dashboard retains the last 14 calendar days and supports date, category and keyword filters. RSS articles use an exact time window. Trends without a reliable publication date are labeled as observed at collection time rather than presented as recently published articles.

`last-run.json` describes the latest attempt; `latest.json` holds the latest usable data. If every source fails, old data may remain available, with its timestamp and a failed-collection notice. No keyword match is not proof that no negative event exists, especially when coverage is incomplete.

## Brief prompt

Give your agent the [daily brief prompt](prompts/daily-brief.en.md). It requests negative signals first, then Li Auto, domestic/international news, trends and a local report link. Build the dashboard after the brief; report build failures separately. This prompt is a sanitized derivative of the user-supplied workflow, with device paths and automation identities removed.

The module does not create a schedule. Daily 09:00 is an optional arrangement that must be explicitly configured in your own automation tool.

See [collection details](docs/collector.en.md). The repository's [module format](https://github.com/8eeth0ven/workhub-model/blob/main/docs/modules.en.md) describes distribution boundaries; the standalone ZIP can be used without those repository documents.

For Workhub versions with manual admission, select this module directory in Add project after registering the site. Admission and following the portal palette are explicit user choices; registration alone does not enable either.
