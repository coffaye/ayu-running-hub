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

## Phase 6 COROS credential broker

`wrangler.phase6.jsonc` defines the isolated `ayu-running-hub-phase6` Worker
environment. It adds the singleton `COROS_CREDENTIAL_BROKER` Durable Object,
which stores only AES-256-GCM ciphertext in SQLite. The application-level key
is the Worker Secret `COROS_CREDENTIAL_KEK`; it must be a random 32-byte
base64url value and is never written to Durable Object storage or GitHub.

The broker owns the COROS OAuth refresh lifecycle and performs MCP
`initialize`, `tools/list`, and fixed read-only calls internally. It never
returns an access token or Authorization header. The internal collector route
is `POST /internal/coros/probe`; it requires the separate
`AYU_COLLECTOR_SHARED_SECRET` HMAC contract. The staging-only bootstrap route
is `POST /internal/coros/bootstrap`; it requires `COROS_BOOTSTRAP_SECRET`,
accepts the token set only in the JSON body, rejects overwrite unless the
explicit `reauthorize` flag is set, and returns metadata only. Removing the
bootstrap secret makes the route return 404.

Request signatures cover timestamp, request ID, run ID, method, path, and the
SHA-256 body hash. The broker rejects stale timestamps and replays. A COROS
`invalid_grant` becomes `COROS_REAUTH_REQUIRED`; the old refresh token is not
retried.

Refresh serialization and the full-token-set commit make concurrent refreshes
single-flight and durable. A process crash between the provider accepting a
rotating refresh token and the SQLite commit cannot be made mathematically
exactly-once; the broker fails closed and requires a fresh browser-authorized
grant if the persisted token becomes unusable.

### Phase 6 staging operations

Create secrets only in the isolated Worker environment:

```powershell
pnpm exec wrangler secret put COROS_CREDENTIAL_KEK --config wrangler.phase6.jsonc
pnpm exec wrangler secret put AYU_COLLECTOR_SHARED_SECRET --config wrangler.phase6.jsonc
pnpm exec wrangler secret put COROS_BOOTSTRAP_SECRET --config wrangler.phase6.jsonc
pnpm run deploy:phase6
```

Bootstrap from the dedicated COROS token cache without putting a token in a
command-line argument, URL, shell history, or output:

```powershell
.\scripts\bootstrap-coros.ps1 `
  -WorkerUrl "https://ayu-running-hub-phase6.<account>.workers.dev" `
  -TokenCachePath "<dedicated-cache>\cn\token.json"
```

After a successful first bootstrap, remove `COROS_BOOTSTRAP_SECRET` from the
Phase 6 Worker. The manual-only diagnostic workflow is
`.github/workflows/phase6-coros-diagnostic.yml`; it receives only the HMAC
collector secret and never receives a COROS OAuth token.

If the broker reports `COROS_REAUTH_REQUIRED`, keep existing reports intact,
create a new dedicated browser-authorized COROS grant, temporarily configure
the bootstrap secret, rerun the bootstrap script with `-Reauthorize`, verify a
diagnostic probe, and remove the bootstrap secret again. A COROS account-side
authorization revoke is separate from local cache deletion; the public client
used by the official gateway helper cannot programmatically revoke through the
provider endpoint.
