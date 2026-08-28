# running_page integration contract

This document defines the next-phase boundary. It is intentionally limited to
the data and file contract; it does not implement Workers, Actions, triggers,
or UI changes.

## Inputs

The `running_page` adapter accepts either:

- an `activities.json` export containing the selected numeric `run_id`, or
- a SQLite database with the public `activities` table shape.

When both are supplied, matching facts are checked and mismatches fail rather
than being silently merged. FIT messages may be supplied through the separate
FIT adapter for richer, explicitly observed metrics.

## Outputs

The engine returns a validated `StructuredReport` plus deterministic HTML. The
HTML contains the `下载 PNG` control; browser JavaScript draws a fixed-width,
content-growing canvas and downloads the PNG. The HTML footer is retained, but
the PNG exporter intentionally omits footer text and places its final rule
after the last real content.

The integration caller should store a report at a deterministic date/run path
and expose only the public run identity needed by the viewer. It should not
publish provider keys, raw responses, routes or internal IDs.

## Pinning and provenance

Pin a released Hub tag or exact commit. Set `AYU_ENGINE_COMMIT` in the caller's
runtime to that SHA. Do not import from a sibling repository or use a mutable
`main` checkout. The caller owns scheduling, authentication, storage and
publication; the Hub owns parsing, analysis boundaries, validation and render
semantics.

