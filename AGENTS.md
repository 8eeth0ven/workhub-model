# Workhub Model contributor rules

- Keep modules independent of the user's local project directories and automation identities.
- Publish runtime source, portable configuration examples, bilingual documentation and clearly fictional demos only.
- Exclude real reports, logs, session history, credentials, generated dashboards and test-only files. Keep development tests outside this release tree.
- Register module commands and an explicit export file list in module.json; installing a module must not execute it or create a schedule.
- Preserve source health, timestamps and uncertainty. A missing source is not evidence that no negative news exists.
- Reuse Workhub's shared design system and keep project content readable in a compact layout.
- Run python3 scripts/audit_release.py and inspect the exact Git and ZIP contents before publishing.
