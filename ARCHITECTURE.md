# Architecture

## Responsibility split

The Hub is the source of truth for report computation and rendering. It has no
dependency on a particular caller, checkout location or web deployment:

| Layer | Responsibility | Deliberate boundary |
| --- | --- | --- |
| `ayu_report_engine.adapters` | Normalize `running_page` JSON/SQLite and FIT inputs | No UI or model calls |
| `DailyRunContext` | Typed, null-preserving facts and evidence | No conclusions |
| `ReportAnalyzer` | Analysis protocol | Provider is injectable |
| `FixtureAnalyzer` | Deterministic offline analyzer for tests | Never calls a network |
| `DeepSeekAnalyzer` | Explicit provider integration and semantic validation | Key/network only on explicit invocation |
| `StructuredReport` | Stable report contract, validation and identity | Renderer-agnostic |
| `render_html` | Ayu Running HTML and Canvas PNG export script | Browser performs PNG export |
| schemas/docs/tests | Contract, provenance and regression protection | No production secrets |

The future GitHub Actions/Cloudflare caller belongs outside this repository.
Likewise, the Codex plugin and the static `running_page` report viewer are
consumers, not dependencies of the Hub.

For Phase 4 staging, the caller is intentionally included as a separate
boundary under `.github/workflows/` and `worker/`: the workflow owns the
report-build transaction and staging-branch push, while the Worker owns HTTP
Basic Auth, run lookup, idempotency and status normalization. Neither
boundary is a production deployment or writes `running_page/master`.

## Data and privacy rules

Adapters may accept production files at runtime, but fixtures in this repo are
sanitized. Plan/activity/device IDs, coordinates, maps, exact route data, FIT
downloads and raw DeepSeek responses must not be rendered or committed.
Unknown is represented as `null`, not zero. Device-model fields remain device
metrics rather than medical or performance guarantees.

## Versioning

The four public identity values live in `engine/ayu_report_engine/version.py`.
Schema changes require updating both JSON schemas and tests. A caller pins a
Hub commit and injects `AYU_ENGINE_COMMIT`; generated reports then carry the
actual Hub provenance instead of a mutable branch name.
