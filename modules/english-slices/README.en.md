[简体中文](README.md) | [English](README.en.md)

# English in slices

Browse words and everyday phrases in continuous slices, then listen to what you need.

Codex Light is the default, with bilingual UI and Workhub palettes. Voice, speed, slice size, language and colors sit in expandable Settings; storage and speech limits are in folded notes. Choose 8, 16 or 32 entries per slice; every slice remains visible in a continuous vertical page. Click words or examples, or play a whole slice with pause, resume and stop. Filtering, switching views or hiding the page cancels playback. Listening never marks understanding; you select “Seen” yourself.

The initial material contains **48 words, 24 everyday phrases and 8 scenes**, written for this module. It is not membership content from another application.

## Run

Use Python 3.10+ and a modern browser. No model key or third-party Python package is required. From the installed module:

```sh
python3 bin/serve.py --port 8831
```

Open `http://127.0.0.1:8831/`. The server binds to loopback only. Imports and Seen marks are saved in the module’s `data/library.json`; use `--data-dir` for your own location. Export backups through the page. Cross-device synchronization is not provided; transfer your phone export to the computer running the module first.

Keep the service running, then connect from the module repository:

```sh
python3 manage.py connect english-slices \
  --installed ../workhub-local/english-slices --workhub ../workhub \
  --site-url http://127.0.0.1:8831/
```

For a different portal origin, add `--parent-origin`, for example `--parent-origin http://127.0.0.1:8797`, when starting the service. Connecting only registers an existing service; it does not start one or create a schedule. Workhub versions with manual admission require you to admit the module directory through Add project.

## Import your material

CSV, TSV, JSON and TXT are supported, up to 2 MiB and 10,000 entries per import. Common English and Chinese headers are recognized; see the [import guide](docs/import.en.md). Identical entries merge, while different meanings, examples and scenes remain separate.

The [official iOS version history for 不背单词](https://apps.apple.com/cn/app/id698570469) has mentioned PDF export. The actual menu and export scope still need confirmation in the phone client. This module does not access accounts or membership interfaces and has no built-in PDF/OCR parser. Convert your own PDF into a supported table and check its text before importing. A membership list has not been migrated until an actual export is supplied and verified.

## Voices and static preview

Playback uses the browser Web Speech API and system English voices. The list updates as voices load. Missing voices, unsupported speech and playback failures are reported. Some voices require a network, so offline speech cannot be guaranteed on every device. Check system voices and volume; the browser may require an explicit click.

For a static example:

```sh
python3 bin/build_data.py --demo
```

The resulting `site/index.html` can be viewed without a service. **Static-mode imports and Seen marks live only in the current browser origin.** Changing ports or browsers, or clearing storage, can remove them. They are not writes to the local data file. Use service mode for file persistence.

## Published contents

Installation only copies source. It does not collect material or access phone accounts. Personal word lists, progress, generated pages, logs and tests are excluded. The HTTP service rejects external Host headers and cross-site writes and is not exposed to the LAN. Adapter availability does not establish that every browser or system voice has been tested.
