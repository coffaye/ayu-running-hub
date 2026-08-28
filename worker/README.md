# Ayu Running Hub staging Worker

This is the non-production Cloudflare Worker boundary for report generation.
The intended name is `ayu-running-hub-staging`; it must remain protected by
Cloudflare Access and must not be configured as the production `running_page`
entry point during Phase 4.

## Boundary

- `GET /generate?run_id=<id>` only renders the status page.
- The page then calls same-origin `POST /api/generate` with exactly
  `{ "runId": "..." }`.
- The Worker verifies the Cloudflare Access JWT (issuer, audience, signature,
  expiry), confirms the run exists in `coffaye/running_page/master`, acquires a
  per-run SQLite-backed Durable Object lock, and dispatches the Hub workflow.
- `GET /api/status/<run_id>` normalizes GitHub workflow state and never exposes
  the provider payload or tokens.

`HUB_ACTIONS_TOKEN` is a Cloudflare Secret limited to the Hub repository's
Actions permission. The Worker never receives `DEEPSEEK_API_KEY` or the token
used by Hub Actions to write `running_page`.

## Local checks

```powershell
pnpm install
pnpm test
pnpm typecheck
```

Use `.dev.vars` for local secrets. The checked-in example is intentionally
empty. A real Access issuer, audience and JWKS URL are required; with any of
those missing the Worker fails closed with `Access configuration required`.

