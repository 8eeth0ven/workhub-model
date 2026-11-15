[简体中文](automation-card.md) | [English](automation-card.en.md)

# Four-hour schedule card

This is a configuration reference for the user's automation tool, not an installed schedule.

| Field | Suggested value |
| --- | --- |
| Title | AI product opinion monitor — every four hours |
| Cron | `0 */4 * * *` |
| Timezone | Explicitly select one, for example `Asia/Shanghai` |
| Working directory | Your actual installed `ai-opinion` module directory |
| Prompt | [Per-run brief](daily-brief.en.md) |
| Initial state | Test manually before enabling it yourself |

Fill device paths and notification destinations locally. This card is not evidence that a previous device's task was migrated. Original automation identities, run counts and claimed historical success rates are not included.

Verify live collection and building once before scheduling. Avoid overlapping runs against one data directory; the collector lock rejects concurrent writes. Actual execution depends on the automation tool, running device, selected timezone and network.

This card does not authorize an agent to create or change schedules, notification channels, system Cron or third-party account settings.
