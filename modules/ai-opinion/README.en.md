[简体中文](README.md) | [English](README.en.md)

# AI product opinion monitoring

Bring domestic and international AI products, models, hardware, public statements and related trends into a local dashboard. Read new and changed material first on each run.

The module reuses Workhub’s **Codex Light**, with Codex Dark and the other palettes available. Typography, compact layout and interactions match the automotive module. Install the modules independently and keep their reports separate.

## Use

Python 3.10 or newer is required. Collection and dashboard building use the standard library and need no model API key.

```sh
# Offline fictional demo in a separate directory.
python3 bin/collect.py --demo --data-dir demo/data
python3 bin/build_data.py --data-dir demo/data
```

Open `site/index.html`. Use a separate directory for live collection:

```sh
cp config.example.json config.json
python3 bin/collect.py --config config.json
python3 bin/build_data.py
```

The example proxy is empty; configure your own if required. Both commands accept `--data-dir`, and the builder accepts `--output-dir`. Demo and live data cannot share a directory; existing material of unknown provenance is not overwritten automatically.

## Read

| Section | Scope |
| --- | --- |
| Negative signals | Headline keywords about leaks, outages, lawsuits or layoffs; verify original sources |
| Domestic AI | Chinese products, models, platforms and agents |
| International AI | International products, models, coding tools and industry reports |
| AI hardware | Glasses, hardware, toys, robotics and embodied AI |
| Public statements | AI-related public remarks, talks and reported views |
| AI trends | AI-related items filtered from Baidu trends |

There are 25 collection inputs: 23 Google News RSS query groups, TechCrunch AI and Baidu trends. Articles use an exact 48-hour window; trends without reliable publication dates use observation timestamps. The dashboard covers the last 14 calendar days with date, source, risk and keyword filters.

## Avoid repeating every four hours

Date-named reports can update during the day while retaining the previous usable snapshot and current delta. Check `last-run.json` before reading `latest.json`, `previous.json` and `delta.json`. The first run explicitly has no comparison baseline. A fully failed run does not advance the successful baseline.

New and changed labels describe structured data comparisons, not model-confirmed event changes. Failed sources, query order and coverage changes do not establish that a news event disappeared. Keyword labels are verification leads, and no match does not prove an absence of negative events.

See [collection details](docs/collector.en.md) for state files, delta rules and options. Switch between incremental highlights and the full report; historical dates use their own comparison baseline.

## Prompt and schedule card

- [Per-run brief prompt](prompts/daily-brief.en.md): negative signals, domestic AI, international AI, hardware, public statements and trends; prioritize new and changed items, then build the dashboard.
- [Four-hour schedule card](prompts/automation-card.en.md): portable title, Cron and prompt reference for your automation tool.

These are sanitized derivatives of the user-supplied workflow, without device paths, automation identities or historical sessions. Installation does not create a schedule. `0 */4 * * *` is an optional arrangement; explicitly select the timezone.

## Connect to Workhub

From the module repository, adjust the paths to your installation:

```sh
python3 manage.py connect ai-opinion \
  --installed ../workhub-local/ai-opinion --workhub ../workhub
```

Build the dashboard first. Connecting registers a project and website only. Workhub versions with manual admission require you to select that directory in Add project and admit it. Following the portal palette is also an explicit option.

Only source, example settings, bilingual guides and sanitized prompts are distributed. Real reports, logs, private configuration, sessions, incremental state, generated dashboards and test files are excluded. This module does not migrate or modify the original three-stream desktop dashboard or automations.
