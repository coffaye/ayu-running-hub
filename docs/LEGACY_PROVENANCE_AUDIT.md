# Legacy report provenance audit

This is a read-only audit of the current public manifest at
`coffaye/running_page@master` as inspected for Phase 6C-1. Existing manifest
entries were not edited.

| runId | localDate | observed provenance | classification | action |
| --- | --- | --- | --- | --- |
| `1767134280000` | `2025-12-31` | engine `0.4.0`, prompt `ayu-daily-v7`, renderer `ayu-html-canvas-v3`, Hub commit `4e505e9d7f41f8e9f68bd9ac6a3cf50f7db06734`; no Skill lock fields | `LEGACY_AMBIGUOUS` | retain; do not infer COROS/Skill source; do not regenerate |
| `1787870493000` | `2026-08-28` | Hub production cutover `d81de79cea33e1f13d80ca521be85ed33d0d6630`; pre-6C manifest shape | `LEGACY_PRE_6C` | retain; future entries receive the new fields |

The first row is intentionally not backfilled from the current Stable lock:
the engine commit belongs to rollback-era history, and the manifest does not
prove which Skill snapshot produced it. Historical HTML, PNG and manifest
entries remain untouched. The audit is descriptive only and does not assert a
COROS source for a report whose public record lacks that provenance.
