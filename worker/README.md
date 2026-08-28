# Ayu Running Hub staging Worker

This is the non-production Cloudflare Worker boundary for report generation.
The intended name is `ayu-running-hub-staging`; it uses Worker-level HTTP Basic
Auth and must not be configured as the production `running_page` entry point
during Phase 4.

## Boundary

- `GET /generate?run_id=<id>` only renders the status page.
- The page then calls same-origin `POST /api/generate` with exactly
  `{ "runId": "..." }`.
- The Worker verifies HTTP Basic Auth, confirms the run exists in
  `coffaye/running_page/master`, acquires a per-run SQLite-backed Durable Object
  lock, and dispatches the Hub workflow.
- `GET /api/status/<run_id>` normalizes GitHub workflow state and never exposes
  the provider payload or tokens.

`REPORT_AUTH_USERNAME` defaults to `ayu` as a normal Worker variable.
`REPORT_AUTH_PASSWORD` and `HUB_ACTIONS_TOKEN` are Cloudflare Secrets limited to
this staging boundary. The Worker never receives `DEEPSEEK_API_KEY` or the token
used by Hub Actions to write `running_page`.

## Local checks

```powershell
pnpm install
pnpm test
pnpm typecheck
```

Use `.dev.vars` for local secrets. The checked-in example is intentionally
empty. Without `REPORT_AUTH_PASSWORD`, every protected route fails closed with
HTTP 401 and `WWW-Authenticate: Basic realm="Ayu Running"`.
