# Ayu Running — Native Agent HTML Envelope Hardening

Local hardening on `native-agent-envelope-hardening`, based on the frozen
candidate `f086337d4bdffa84bd5cf336f48a7b0de46ed2b2`. Production `main` remains
on its rollback baseline; this document authorizes no deployment or migration.

## Root cause

The Native Agent Pass 2 transport contract rejected otherwise complete HTML when
the model surrounded it with a short preface, Markdown fence, or postscript.
The failure was at the raw-output envelope boundary, not in the Skill, input
adapter, model settings, or report semantics.

## Change

`normalize_html_envelope()` now runs between raw Pass 2 output and the existing
strict HTML validator. It slices exactly one `<html ...>` root through its one
`</html>` close, optionally starting at a preceding `<!DOCTYPE html>`, and
leaves the selected HTML bytes unchanged. Missing, out-of-order, duplicate, or
multiple document envelopes fail closed.

Only safe envelope metadata is exposed: strict/normalized status, removed
prefix/suffix character counts, and root/close counts. Wrapper text and raw
model output are never placed in logs or metadata. Language scanning runs before
PNG validation; `safeVisibleLanguage` and `pngExport` remain unknown until their
checks actually run.

## Frozen runtime and input

- Model: `deepseek-flash`
- Reasoning: `high`
- Maximum output: `65536`
- Request timeout: `300s`
- Native Skill snapshot: `7c23f7c28643bc0d62d84afb2a8a782fb966879e8e8f30658a4944bd57ee2708`
- Input: the existing sanitized 2026-09-13 / `1789255559000` bundle with 29 laps
- Report-date load: 187 / 148 / 1.26 / Optimized
- Recovery: unknown; no current recovery was promoted
- Planned load: 297 TL, kept separate from recent load
- Model calls: exactly two per run; Pass 2 remains the only final source

## Verification

Unit coverage includes strict documents, prose/fence wrappers, byte
preservation, ambiguity rejection, safe metadata, forbidden visible language,
PNG requirements, Pass 2-only final selection, and the two-call contract.

Hub full pytest: `159 passed, 47 subtests passed`.

Three independent live runs with the frozen model/input completed successfully:

| Run | Final chars | Raw strict | Normalized | Prefix / suffix | HTML | Language | PNG | Golden |
| --- | ---: | --- | --- | ---: | --- | --- | --- | --- |
| Live-1 | 23,437 | yes | no | 0 / 0 | pass | pass | pass | pass |
| Live-2 | 21,210 | yes | no | 0 / 0 | pass | pass | pass | pass |
| Live-3 | 24,909 | no | yes | 106 / 4 | pass | pass | pass | pass |

The three final HTML files and safe run metadata are retained in the ignored
local `prototype/native_skill_parity/output/envelope-hardening/` staging
directory. Browser downloads for all three live reports succeeded.

The real `scripts/generate_report.py` production entry was also run against a
local staging target. It installed only the expected report and manifest paths;
the manifest engine commit matched the actual current HEAD, the Skill snapshot
matched, Golden checks passed, and the same HTML downloaded as PNG in a browser.
The formal `running_page-git` checkout and public manifest were not written.

## Safety and gate

- No Native Skill, prompt, self-review, adapter, Worker, workflow, frontend, or
  Production report was changed.
- No merge to `main`, Production deploy, Worker Canary, Pages write, manifest
  write, or report regeneration was performed.
- `running_page` and `ayu-running-reports` remain outside this change.

**NATIVE AGENT HTML ENVELOPE HARDENING READY**
