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

## Phase 4 staging boundary

`.github/workflows/generate-report.yml` accepts only string `run_id` and a
Worker-generated `request_id`. It reads activity data from
`coffaye/running_page@master`, analyzes with the configured DeepSeek variables,
and writes only `coffaye/running_page@ayu-report-e2e` report files. The
workflow uses per-run concurrency and an atomic HTML/manifest transaction.

`worker/` is the separately deployable `ayu-running-hub-staging` Cloudflare
Worker. It is Access-protected, validates the Access JWT itself, performs a
master run lookup, and uses a SQLite-backed Durable Object lock before
dispatching the workflow. Configure `HUB_ACTIONS_TOKEN` as a Cloudflare Secret;
configure `DEEPSEEK_API_KEY` and `RUNNING_PAGE_WRITE_TOKEN` as GitHub Actions
Secrets. No production Pages or `running_page/master` write is part of staging.
