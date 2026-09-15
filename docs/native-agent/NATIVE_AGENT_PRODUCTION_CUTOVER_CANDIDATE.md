# Ayu Running — Native Agent Runtime Production Cutover Candidate

Local-only closeout for the `native-agent-production-cutover` branch. This is a candidate integration, not a production migration.

## A. Baseline

- Hub base: `origin/main` = `71f59e75dea40fca37eb177c04e2a8e0b27d9b5a`.
- Cutover branch was created from that exact remote base.
- The validated prototype branch was not merged. Its self-review closeout was already committed separately as `f92cb80` before this branch was created.
- `running_page` baseline remained `master` = `53e4dd4bc3cff2ccfb8e73b7deac6563016d4833`.

## B. Reviewed diff

The candidate changes are limited to the Native runtime boundary, its frozen Skill snapshot, local tests/fixture, manifest provenance, workflow defaults, and this audit record. The old `prompt.py`, `report.py`, `display.py`, `render.py`, and `StructuredReport` implementation remain in the repository for rollback, but the production `generate_report.py` path no longer invokes them.

No Worker, COROS Broker, OAuth, public Page source, public manifest, production HTML, renderer redesign, PNG redesign, secret, cache, local machine path, or temporary artifact was added to the commit.

## C. Frozen Native Skill snapshot

The seven required Native Skill files are vendored under `engine/native_skill/`. The verified ordered snapshot fingerprint is:

`7c23f7c28643bc0d62d84afb2a8a782fb966879e8e8f30658a4944bd57ee2708`

`provenance.json` records the runtime version `native-agent-runtime-v1`, source label, and each normalized file SHA-256. The production loader reads only this vendored chain and fails closed on any missing or changed file.

## D. Model and production defaults

- Requested model: `deepseek-flash`.
- Reasoning effort: `high`.
- Maximum output: `65536` tokens.
- Request timeout: `300` seconds; workflow job timeout: 25 minutes.
- Local E2E provider response model: `deepseek-flash` for both calls.
- No API key, authorization header, response body, or hidden reasoning is persisted in the candidate or this report.

## E. Input boundary

The adapter passes activity summary, all 29 laps, today schedule, report-date load, recovery state, tomorrow schedule, and data-quality/unavailable facts. For the frozen 2026-09-13 harness input it passed:

- Short-term load `187`, long-term load `148`, ratio `1.26`, status `Optimized`.
- `recovery = null` because no historical report-date recovery snapshot was proven.
- Planned load `297 TL` remains inside the schedule context and is not used as actual recent load.

Private identity/provider metadata is removed before model input. A load date mismatch and an unsafe recovery date are fail-closed.

## F. Runtime behavior

The production path is now:

`COROS Daily Bundle → Native input adapter → Native Skill Pass 1 → generic Pass 2 self-review → strict final HTML → existing atomic install`

Pass 1 and Pass 2 are independent calls using the same Skill snapshot and sanitized input. Only raw Pass 2 can be installed. Provider errors, incomplete output, non-strict HTML, unsafe visible implementation language, missing PNG export, or any other runtime failure aborts the generation without falling back to the old renderer.

## G. Manifest contract

The public manifest remains `schemaVersion: 1` with the existing `runId`, `localDate`, `url`, `generatedAt`, and `reports` structure. The native entry adds:

- `generationMode: native-skill-agent`
- `nativeRuntimeVersion: native-agent-runtime-v1`
- `nativeSkillSource` and `nativeSkillSnapshotSha256`
- `model`, `reasoningEffort`, `engineCommit`, `dataSource`, and `collectorContractVersion`

The local E2E manifest entry used the exact report URL `reports/daily/2026-09-13/1789255559000.html` and engine commit `14d359db755057aa3445f774aa1cbea882f83826`.

## H. Local production-entry harness

The actual `scripts/generate_report.py` production entry was invoked with the 9/13 bundle and captured Native overlay, a temporary running_page identity source, and a temporary output checkout. It installed only:

`public/reports/daily/2026-09-13/1789255559000.html`

and the corresponding temporary manifest entry. The formal `running_page-git` checkout and its public manifest were not written.

## I. Harness result

The two live calls completed successfully:

| Stage | Provider model | Output chars | Input tokens | Output tokens | Reasoning tokens | Duration |
|---|---|---:|---:|---:|---:|---:|
| Pass 1 | `deepseek-flash` | 20,298 | 13,986 | 27,744 | 19,482 | 110,921 ms |
| Pass 2 | `deepseek-flash` | 20,576 | 22,455 | 32,289 | 23,784 | 124,670 ms |

The freeze E2E calls were requested at `2026-09-15T02:59:36.537631+00:00` and `2026-09-15T03:01:27.459488+00:00`; the temporary manifest was generated at `2026-09-15T03:03:32Z`. The final HTML was 20,576 characters. It began with `<!DOCTYPE html>`, ended with `</html>`, contained the required `下载 PNG` button and browser-side Canvas export, and used Pass 2 as the installed artifact.

## J. Acceptance checks

The local production entry passed the unchanged 9/13 Golden checks:

- main 20 km pace band distinguished from the 21 km/finish acceleration;
- rear-half heart-rate cost increase;
- pace and power direction not reversed;
- 20–21.1 km finish acceleration and 3 × 200 with the third repetition fastest;
- no broad-stability/detail contradiction;
- 187 / 148 / 1.26 / Optimized load facts;
- recovery remains unknown;
- planned `297 TL` remains distinct from actual load;
- no forbidden visible implementation vocabulary;
- strict complete HTML and PNG export contract.

## K. Automated verification

- Hub full pytest: `143 passed, 47 subtests passed`.
- Hub `compileall`: PASS.
- Workflow YAML parse: PASS.
- Vendored Skill hash validation: PASS.
- Staged `git diff --check`: PASS.
- running_page production Vite build to a temporary output directory: PASS.
- running_page manifest/path Node tests: `4 passed`.
- Secret scan over new runtime, fixture, Skill snapshot, workflow, and script: no credential material found; workflow secret references are declarations only.

## L. Rollback and failure safety

The legacy renderer remains available in the tree. The new install transaction replaces exactly the report and manifest, and the existing rollback test plus the Native atomic-install test pass. A failure before or during Pass 2 leaves the target report unchanged; no Draft is used as a fallback.

## M. Deployment safety and gate

- No merge to `main`.
- No push of the prototype or cutover branch.
- No workflow dispatch, Pages deployment, Worker change, running_page source change, public manifest write, or Production report regeneration.
- `ayu-running-reports` was not modified.
- Hub commit: `14d359db755057aa3445f774aa1cbea882f83826`.

**NATIVE AGENT PRODUCTION CUTOVER CANDIDATE READY**

This gate authorizes no automatic migration or deployment; the next phase must explicitly review and approve a production cutover.

## N. SHA reconciliation and final freeze

`14d359db755057aa3445f774aa1cbea882f83826` is one commit after
`9279c85675691f8b8431791d0576be9fdd7236e9`. The only delta is this audit
document; runtime, `generate_report.py`, workflow, vendored Skill snapshot,
adapter, and manifest logic are unchanged. Therefore the original E2E remained
code-applicable, and the freeze E2E was additionally rerun with
`AYU_ENGINE_COMMIT` equal to the actual current HEAD. Its temporary manifest
also records the full current HEAD SHA and passed the same Golden checks.
