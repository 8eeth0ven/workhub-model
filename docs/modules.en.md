[简体中文](modules.md) | [English](modules.en.md)

# Download and connect feature modules

With current Workhub, open **Modules** in the workspace sidebar and choose **Install & connect**. Workhub downloads a fixed release, checks its pinned digest, prepares the page and connects it, with progress and retry controls. English starts or reuses a verified local service. Personal data is preserved; installation does not collect news, create schedules or call a model.

The standalone CLI workflow below remains available and copies source only; its installation command does not run module code.

`workhub-model` contains independently downloadable Workhub feature modules. It is not a model-weight repository and does not replace Workhub. Download the repository, then install the module from that local checkout. Installation copies explicitly listed source files; it does not collect news, run scripts, create scheduled tasks or make network requests.

The distribution tool requires Python 3.10 or newer and uses only the standard library.

```sh
git clone https://github.com/8eeth0ven/workhub-model.git
cd workhub-model
python3 manage.py list
python3 manage.py install auto-opinion --output ../my-auto-opinion --dry-run
python3 manage.py install auto-opinion --output ../my-auto-opinion
```

The output directory must not exist, even if empty. `--dry-run` validates the module and lists its files without creating output. The installed `module-install.json` records the version and each source file's SHA-256. Keep generated reports, logs, personal configuration and collected data in the installed directory, outside the release repository.

From the installed directory, start with an explicitly fictional offline demonstration before configuring live collection:

```sh
cd ../my-auto-opinion
python3 bin/build_data.py --demo
```

Open the generated `site/index.html`. Installation does not start a server or collect news. See the module README for live collection, networking and data limitations.

## Connect to Workhub

Build the dashboard first, then explicitly select your local Workhub checkout. Replace `/path/to/workhub` with your own directory:

```sh
python3 manage.py connect auto-opinion \
  --installed ../my-auto-opinion --workhub /path/to/workhub --dry-run
python3 manage.py connect auto-opinion \
  --installed ../my-auto-opinion --workhub /path/to/workhub
```

Run these commands from the `workhub-model` checkout. `connect` invokes the selected local Workhub project installer to register the project and static site. It does not install global rules, start collection or servers, or create automations. It fails if `site/index.html` has not been built; registration alone does not prove that a website works.

## A ZIP for one module

```sh
python3 manage.py package auto-opinion --output ../auto-opinion-0.1.0.zip --dry-run
python3 manage.py package auto-opinion --output ../auto-opinion-0.1.0.zip
```

The ZIP has an `auto-opinion/` top-level directory and includes only source, documentation and sanitized prompts explicitly listed in `module.json`. Existing files are not overwritten. Output includes the ZIP's SHA-256. File ordering, timestamps and permissions are fixed so identical source produces a verifiable package. Neither installation nor packaging downloads or executes remote code.

## Add another module

Define a version, entrypoints and explicit `files` list in `modules/<module-id>/module.json`, then add the matching version to the root `catalog.json`. IDs use lowercase letters, digits and hyphens. File lists reject directory globs, absolute paths, `..`, backslashes, symlinks and special files. Tests, collected data, logs, credential configuration and generated `index.html` files are also rejected.

Review the actual files, configuration and images before release. The tool checks known personal paths, common tokens, private keys, credential-bearing URLs and local automation identifiers, but heuristics cannot identify every sensitive detail. Install a new version into a new directory and migrate personal configuration and data after review; this tool does not overwrite or automatically upgrade an existing installation.

## Server modules

For modules requiring backend persistence, explicitly start the local server using its README, then pass `--site-url http://127.0.0.1:8831/` to `connect`. This accepts loopback HTTP(S) URLs without credentials, queries or fragments. Connecting registers the site without starting it. Server modules require this option so static previews cannot be mistaken for writable backends.

## Module interfaces

Reuse shared design tokens and Codex Light. Prioritize content, common navigation and search; disclose secondary settings progressively instead of lining up controls and repeated notices. Organize content with typography, fine separators and a few light surfaces rather than a bordered card for every item. Expanded settings should push layout instead of covering text. Consolidate normal status while preserving failures, stale data, sources and evidence.
