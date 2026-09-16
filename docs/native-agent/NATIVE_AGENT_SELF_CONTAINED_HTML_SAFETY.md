# Native Agent Self-Contained HTML Safety Audit

## Scope

Branch: native-agent-html-safety

Base: 6bfe5cfedb5e946395da344e083cff50ab31fb42

This change adds a deterministic, fail-closed safety boundary for the Native
Agent final HTML. It does not change the Native Skill snapshot, model settings,
input adapter semantics, self-review flow, Worker, workflow, manifest contract,
renderer, running_page, or Production reports.

## Validation order

The final artifact path is:

Pass 2 raw -> envelope normalization -> strict HTML -> self-contained safety -> visible language -> PNG -> final artifact

The safety validator rejects without rewriting HTML. It checks resource
attributes, URL schemes, embedded browsing contexts, forms, navigation,
CSS imports and remote URLs, inline network/navigation APIs, dynamic resource
creation, and a 100,000-character artifact ceiling. Failure metadata contains
only safe category, tag/attribute/API category, and count.

Inline Canvas/PNG code remains allowed.

## Verification

- Native-agent safety/envelope tests: 74 passed
- Hub full pytest: 204 passed, 47 subtests passed
- compileall: PASS
- Workflow YAML parse: PASS (4 files)
- Engine JSON parse: PASS
- Native Skill snapshot: PASS
- git diff --check: PASS
- Tracked-file secret scan: PASS
- Production-entry staging E2E: PASS with self-contained validation and
  browser PNG download in an isolated target
- Unrelated repositories and Production paths: unchanged

## Live evidence

The frozen configuration was used for three independent Native Agent attempts:
deepseek-flash, reasoning high, max output 65536, timeout 300s, with the
sanitized 2026-09-13 input (29 laps, report-date load 187/148/1.26,
Optimized, recovery null).

- Load-Safety-1: blocked during Pass 1 by a completed provider response that
  was not acceptable HTML (malformed_response).
- Load-Safety-2: envelope, self-contained, language, and PNG checks PASS; load
  facts and Golden content PASS.
- Load-Safety-3: envelope, self-contained, language, and PNG checks PASS; load
  facts and Golden content PASS.

The live gate is therefore 2/3, not 3/3. The failed run is retained as a
failure record; no prompt tuning or result substitution was performed.

## Production safety

No merge to main, no Production deployment, no Worker Canary, no running_page
write, no manifest write, and no Production report regeneration were performed.
