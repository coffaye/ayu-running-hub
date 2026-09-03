# Ayu Running Hub

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

- Hub / engine: `0.2.0`
- Structured schema: `1.1`
- DeepSeek prompt: `ayu-daily-v5`
- Renderer: `ayu-html-canvas-v1`

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

`.github/workflows/generate-report.yml` accepts only string `run_id` and a
Worker-generated `request_id`. It checks that the identity exists in
`coffaye/running_page@master`, fetches training facts from the signed Phase 6
COROS Daily Bundle endpoint, analyzes with the configured DeepSeek variables,
and publishes only the requested report plus its manifest entry to
`coffaye/running_page@master`. The workflow uses per-run concurrency and an
atomic HTML/manifest transaction.

The production sequence is fail-closed:

```text
running_page identity guard
        -> signed COROS Daily Bundle
        -> DailyRunContext
        -> explicit DeepSeekAnalyzer
        -> validated StructuredReport
        -> deterministic HTML + browser Canvas PNG export
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
