[简体中文](README.md) · [English](README.en.md)

# Workhub Model

Three independent modules turn public news or pricing records into local dashboards. Pick a module below for an offline demo or live collection.

![Three installable dashboards for automotive news, AI product changes and the compute value chain](docs/images/module-workflow.svg)

| Module | What you can read |
| --- | --- |
| [Automotive news](modules/auto-opinion/README.en.md) | Carmaker headlines, a Li Auto section and automotive trends |
| [AI product news](modules/ai-opinion/README.en.md) | Reports added or changed since the previous successful collection |
| [Compute value chain](modules/compute-search/README.en.md) | GPU catalog rates, vendor announcements and seven industry segments |

Use Python 3.10 or later. From the repository root, install to a new folder, or download a standalone ZIP from [Releases](https://github.com/8eeth0ven/workhub-model/releases).

```sh
python3 manage.py list
python3 manage.py install ai-opinion --output ../workhub-local/ai-opinion
```

Installation copies the module files. You start collection and configure any schedule yourself. Reports and configuration stay local. Open the generated dashboard directly or connect it to Workhub. [Module integration and packaging](docs/modules.en.md)
