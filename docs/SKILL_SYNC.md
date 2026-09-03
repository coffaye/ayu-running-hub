# Skill versioning and controlled sync

Phase 6C-1 keeps report production on an explicit, reviewable Skill snapshot.
The Hub never reads `ayu-running-reports/main`, follows `latest`, or pulls a
moving branch during report generation. The checked-in
[`engine/skill_contract/skill-lock.json`](../engine/skill_contract/skill-lock.json)
is the production source of truth.

## Stable, Candidate and the lock

Stable is the lock committed on the Hub production branch. It records the
Skill repository, a full source commit SHA, and the Git blob SHA plus source
and vendored path for every allowlisted production file. The independent
`contractVersion` (`1.0.0` in this foundation) is separate from engine,
schema, prompt and renderer versions.

Candidate is a temporary workspace created only by the manual
`Skill sync preview` workflow. It is never pushed to the Hub, never published
to `running_page`, and never changes historical reports. A candidate can be
promoted only by a separate, deliberate change after the checks below pass;
Phase 6C-1 does not promote the current upstream tip.

## Sync and impact categories

Run the sync tool with a full commit SHA and a checked-out source repository:

```text
python scripts/sync_skill_contract.py \
  --source-root ../ayu-running-reports-repo \
  --source-commit <full-40-character-sha>
```

Add `--dry-run` to generate a machine-readable plan without writing files.
The tool validates the commit, reads only the allowlist, compares the current
lock, reports changed and unknown paths, and atomically updates only allowlisted
vendored files and the lock. README, Actions, `.mcp.json`, tests, temporary
files, user automation and any other non-allowlisted path cannot be synced.

The plan emits these categories:

- `METHODOLOGY`: review Skill contract and prompt versions.
- `VOICE`: review Skill contract and prompt versions.
- `DATA_CONTRACT`: review bundle, engine, schema, grounding and prompt
  contracts; no blanket version bump is automatic.
- `DESIGN_SYSTEM`: review Skill contract and renderer versions.
- `PNG`: review Skill contract and renderer versions.
- `UNKNOWN`: stop for manual review; the path is reported but not synced.

The allowlist covers `SKILL.md`, report modes, ShadowRunner methodology and
voice, upstream connection/privacy guidance, the design system and PNG export
references currently used by the Hub production contract.

## Preview, comparison and promotion gate

The manual workflow checks out the exact requested Skill commit, copies the
Hub into a temporary Candidate workspace, runs the controlled sync there, and
executes Stable and Candidate tests. It generates offline review artifacts
from the same sanitized COROS Daily Bundle, including:

- StructuredReport and semantic validation;
- verdict, completion, evidence, bottleneck, ShadowRunner and tomorrow
  schedule comparison;
- Stable/Candidate HTML and Canvas PNG artifacts;
- a machine-readable sync plan and comparison result.

The fixed regression registry has entries for structured aerobic, interval,
long run, no-plan free activity and incomplete/historical activity. Missing
real sanitized fixtures stay explicitly missing; facts are not invented to
make a category appear covered. Human review of the uploaded HTML and PNG is
required before any future promotion. Text need not be byte-identical, but a
semantic or visual difference must be understood and attributable to the
candidate Skill change.

## Provenance and historical reports

New production manifest entries separately carry `dataSource`,
`skillContractVersion`, `skillSourceCommit` and `collectorContractVersion`, in
addition to engine, schema, prompt and renderer identity. The frontend ignores
unknown metadata and preserves these known optional fields.

Existing manifest entries are immutable. They are classified as legacy when
their Skill provenance is absent or ambiguous; no COROS source is guessed and
no historical report is regenerated. In particular, run `1767134280000`
(2025-12-31) remains a legacy/ambiguous entry associated with rollback-era
engine commit `4e505e9d7f41f8e9f68bd9ac6a3cf50f7db06734`.

## Rollback and production safety

Promotion does not regenerate history. Rollback is an ordinary Git revert of
the Hub lock/contract change, followed by the normal existing production
checks. There is no scheduled auto-pull, auto-merge or auto-deploy. The
existing `generate-report.yml` path remains unchanged apart from adding
deterministic provenance to future manifest entries; the sync workflow has
read-only repository permissions and no `running_page`, Pages or production
publication step.
