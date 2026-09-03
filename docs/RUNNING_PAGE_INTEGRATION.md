# running_page integration contract

This document defines the data and file contract used by the production report
path. The Worker, Action, trigger and UI implementations live in their owning
repositories; this document records the boundary they must preserve.

## Inputs

The `running_page` adapter accepts either:

- an `activities.json` export containing the selected numeric `run_id`, or
- a SQLite database with the public `activities` table shape.

When both are supplied, matching facts are checked and mismatches fail rather
than being silently merged. FIT messages may be supplied through the separate
FIT adapter for richer, explicitly observed metrics.

The production `generate-report.yml` workflow uses `running_page` only for an
identity existence guard. Training facts are fetched from the signed Phase 6
COROS Daily Bundle endpoint and converted with `context_from_coros_bundle`.

## Outputs

The engine returns a validated `StructuredReport` plus deterministic HTML. The
HTML contains the `下载 PNG` control; browser JavaScript draws a fixed-width,
content-growing canvas and downloads the PNG. The HTML footer is retained, but
the PNG exporter intentionally omits footer text and places its final rule
after the last real content.

The production Action stores a report at a deterministic date/run path and updates
the Manifest atomically. New entries include `hubVersion` (with the legacy
`engineVersion` compatibility field), `engineCommit`, schema/prompt/renderer
versions, model and reasoning effort. The viewer receives only the public run
identity; provider keys, raw responses, routes and internal IDs are never
published.

## Pinning and provenance

Pin a released Hub tag or exact commit. Set `AYU_ENGINE_COMMIT` in the Action
runtime to that SHA. The production identity source and publication target are
`coffaye/running_page@master`. The Worker owns HTTP Basic Auth, run lookup and
idempotency; the Hub owns COROS bundle parsing, analysis boundaries, validation
and render semantics; `running_page` owns the public Manifest, HTML files and
viewer UI.
