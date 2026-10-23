# Ayu Running Hub

## Four-theme production update (2026-10-22)

The active production path is the Native Skill Agent (two HTML passes), not the
legacy deterministic StructuredReport renderer described in older sections below.
The generation page now offers `black-green` (default), `burgundy`, `blue` and
`violet`. `POST /api/generate` accepts `runId` and optional allowlisted `theme`;
the Worker forwards it through workflow_dispatch to `generate_report.py --theme`.
Existing callers without theme remain compatible. Opening the page alone never
dispatches: choose a theme and click **生成日报**.

The Native reference snapshot includes `references/themes.md`. One theme is
requested per report; the final artifact must have its matching body marker,
HTML palette and Canvas palette before atomic installation. A mismatched theme
fails closed and leaves the previous ready report available. No model/provider,
authentication, routing, target branch or publication API modernization is part
of this change. Same-run/same-theme requests deduplicate; another active theme
returns 409. Locks remain per-run, so different runs can still proceed in parallel.

The public report URL and manifest key remain one-per-run: a successful later
theme replaces the current presentation, while old reports are not bulk-rewritten.
The manifest records the selected theme. Local Codex Skill reports additionally
support weekly/monthly modes and theme-suffixed filenames.

The independent, deterministic report engine for Ayu Running. This repository
owns the report contract and the implementation that future automation can
call; the Codex plugin wrapper and the `running_page` UI remain separate
projects.

## Scope

```text
running_page JSON / SQLite / FIT
        -> source adapter
        -> DailyRunContext (schema 1.1)
        -> ReportAnalyzer (FixtureAnalyzer or explicit DeepSeekAnalyzer)
        -> StructuredReport
        -> deterministic HTML + browser Canvas PNG exporter
```

The Hub is deliberately independent of any sibling checkout. It includes
sanitized fixtures and does not require the source repository at runtime.
Missing values stay `null`; identifiers, routes, maps, credentials and raw
provider responses are not stored.

## Version identity

The authoritative runtime versions are defined in
[`engine/ayu_report_engine/version.py`](engine/ayu_report_engine/version.py).
The current snapshot is:

- Hub / engine: `0.4.2`
- Structured schema: `1.1`
- DeepSeek prompt: `ayu-daily-v7`
- Renderer: `ayu-html-canvas-v3.1`
- Skill contract: `1.1.0`; its pinned source and allowlisted files are recorded in
  [`engine/skill_contract/skill-lock.json`](engine/skill_contract/skill-lock.json).

The production engine lives in `ayu-running-hub/engine`. The separate
`ayu-running-reports/engine` is a standalone/reference implementation with its
own versions; it is not the current production runtime.

Every future caller should pin this repository to a tag or commit SHA and set
`AYU_ENGINE_COMMIT` to the pinned commit. Do not silently follow `main` in
production automation.

## Local development

The engine is a self-contained Python project:

```powershell
cd engine
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q .
```

The engine needs the IANA time zone database when converting COROS bundles with
`ZoneInfo("Asia/Shanghai")`. Its runtime `tzdata` dependency provides the standard
fallback on Windows and other systems without that database; `zoneinfo` still
prefers system data when available. No manual `tzdata` installation is required.

Fixture-only report generation never makes network calls. The explicit
DeepSeek smoke and benchmark commands require `--live` and a local
`DEEPSEEK_API_KEY`; they write only gitignored metadata and reports under
`engine/.benchmark/`.

```powershell
python -m ayu_report_engine.cli --help
python -m ayu_report_engine.smoke --help
python -m ayu_report_engine.benchmark --help
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for boundaries,
[docs/RUNNING_PAGE_INTEGRATION.md](docs/RUNNING_PAGE_INTEGRATION.md) for the
future integration contract, and [docs/MIGRATION.md](docs/MIGRATION.md) for
the repository split record.

## Production report boundary

`.github/workflows/generate-report.yml` accepts string `run_id`, a
Worker-generated `request_id`, and an optional allowlisted `theme`. It checks that the identity exists in
`coffaye/running_page@master`, fetches training facts from the signed Phase 6
COROS Daily Bundle endpoint, analyzes with the configured DeepSeek variables,
and publishes only the requested report plus its manifest entry to
`coffaye/running_page@master`. The workflow uses per-run concurrency and an
atomic HTML/manifest transaction.

The production sequence is fail-closed:

```text
running_page identity guard
        -> signed COROS Daily Bundle
        -> sanitized Native input
        -> two-pass Native Skill Agent (draft + review)
        -> self-contained safety / theme validation
        -> approved HTML + browser Canvas PNG export
        -> conflict-safe running_page publication
```

The `phase6-report-preview.yml` workflow remains a manual-only,
non-publication diagnostic and is not part of the production path.

`worker/` is the separately deployable Cloudflare Worker, retained under the
historical `ayu-running-hub-staging` name. It is protected by Worker-level
HTTP Basic Auth, performs a master run lookup, and uses a SQLite-backed
Durable Object lock before dispatching the workflow. Configure
`REPORT_AUTH_USERNAME` as a normal Worker variable and `REPORT_AUTH_PASSWORD`
plus `HUB_ACTIONS_TOKEN` as Cloudflare Secrets; configure `DEEPSEEK_API_KEY`,
`RUNNING_PAGE_WRITE_TOKEN`, and `AYU_COLLECTOR_SHARED_SECRET` as GitHub Actions
Secrets. `PHASE6_COLLECTOR_URL` is a repository variable.

Each newly generated Manifest entry records both the compatibility field
`engineVersion` and the Hub identity field `hubVersion`, plus the current Hub
commit, schema, prompt, renderer, model and reasoning settings. Existing
entries remain readable during the production migration.

The [2026-10-23 mobile presentation release](docs/MOBILE_PRESENTATION_20261023.md) keeps the approved violet outlines, orange ticket and interaction, removes duplicate top metadata in all themes, and adopts paginated 2160 × 3840px (9:16) PNG summaries. Local Skill templates and production Native references are released separately; existing reports remain available until explicitly regenerated.
