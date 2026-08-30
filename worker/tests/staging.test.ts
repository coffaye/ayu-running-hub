import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  acquireLock,
  buildDispatchPayload,
  isActiveLock,
  isAllowedReportPath,
  normalizeRunId,
  normalizeWorkflowState,
  parseDispatchResponse,
  redactSecrets,
  runExistsInActivities,
  type LockRecord,
} from '../src/core.ts';
import {
  collectorSigningPayload,
  parseBasicCredentials,
  signCollectorPayload,
  timingSafeEqual,
  verifyBasicCredentials,
} from '../src/auth.ts';
import app, { createApp, validateGenerateBody } from '../src/index.ts';
import { renderGeneratePage } from '../src/pages.ts';
import { GithubClient } from '../src/github.ts';

test('run identity is string-only and lookup is based on master activity data', () => {
  assert.equal(normalizeRunId('00123'), '00123');
  assert.throws(() => normalizeRunId(123));
  assert.throws(() => normalizeRunId('0'));
  assert.equal(runExistsInActivities([{ run_id: 123 }, { run_id: '456' }], '123'), true);
  assert.equal(runExistsInActivities([{ run_id: '456' }], '123'), false);
});

test('worker input accepts only runId and rejects browser-controlled routing fields', () => {
  assert.equal(validateGenerateBody({ runId: '123' }), '123');
  assert.throws(() => validateGenerateBody({ runId: 123 }));
  assert.throws(() => validateGenerateBody({ runId: '123', branch: 'master' }));
});

test('dispatch payload and return_run_details parser preserve request identity', () => {
  assert.deepEqual(buildDispatchPayload('123', 'request-1'), {
    ref: 'main',
    inputs: { run_id: '123', request_id: 'request-1' },
    return_run_details: true,
  });
  assert.deepEqual(
    parseDispatchResponse({ workflow_run: { id: 7, run_url: 'https://ci/run/7', html_url: 'https://github/run/7' } }),
    { workflowRunId: 7, runUrl: 'https://ci/run/7', htmlUrl: 'https://github/run/7' }
  );
  assert.throws(() => parseDispatchResponse({ id: 7 }));
});

test('GitHub REST dispatch and status requests include the stable User-Agent', async () => {
  const requests: Array<{ url: string; headers: Headers }> = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    requests.push({ url, headers: new Headers(init?.headers) });
    if (url.includes('/dispatches')) {
      return new Response(
        JSON.stringify({
          workflow_run: {
            id: 7,
            run_url: 'https://ci/run/7',
            html_url: 'https://github/run/7',
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    return new Response(JSON.stringify({ status: 'completed', conclusion: 'success', html_url: 'https://github/run/7' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as typeof fetch;

  const client = new GithubClient({
    token: 'test-token',
    repository: 'coffaye/ayu-running-hub',
    workflow: 'generate-report.yml',
    sourceRepository: 'coffaye/running_page',
    fetcher,
  });
  await client.dispatch('123', 'request-1');
  await client.getWorkflowRun(7);

  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.headers.get('user-agent'), 'ayu-running-hub-worker');
    assert.equal(request.headers.get('authorization'), 'Bearer test-token');
    assert.equal(request.headers.get('x-github-api-version'), '2022-11-28');
  }
});

test('live report lookup returns only the allowlisted production report URL', async () => {
  const client = new GithubClient({
    token: 'test-token',
    repository: 'coffaye/ayu-running-hub',
    workflow: 'generate-report.yml',
    sourceRepository: 'coffaye/running_page',
    fetcher: (async () => new Response(JSON.stringify({
      reports: {
        '123': {
          runId: '123',
          url: 'reports/daily/2026-08-28/123.html',
        },
      },
    }), { status: 200, headers: { 'content-type': 'application/json' } })) as typeof fetch,
  });
  assert.equal(
    await client.getLiveReportUrl('123'),
    'https://coffaye.github.io/running_page/reports/daily/2026-08-28/123.html',
  );
});

test('per-run lock deduplicates same run, permits different runs, and expires', () => {
  const first = acquireLock(null, '123', 'a', 1000);
  const duplicate = acquireLock(first.record, '123', 'b', 2000);
  assert.equal(first.created, true);
  assert.equal(duplicate.created, false);
  assert.equal(duplicate.record.requestId, 'a');
  assert.equal(acquireLock(null, '456', 'c', 2000).created, true);
  assert.equal(isActiveLock(first.record, 1000 + 30 * 60 * 1000 + 1), false);
  assert.equal(acquireLock(first.record, '123', 'd', 1000 + 30 * 60 * 1000 + 1).created, true);
});

test('workflow status, path allowlist and secret redaction are explicit', () => {
  assert.equal(normalizeWorkflowState('queued', null), 'queued');
  assert.equal(normalizeWorkflowState('in_progress', null), 'running');
  assert.equal(normalizeWorkflowState('completed', 'success'), 'success');
  assert.equal(normalizeWorkflowState('completed', 'failure'), 'failure');
  assert.equal(isAllowedReportPath('public/reports/manifest.json', '123', '2026-08-26'), true);
  assert.equal(isAllowedReportPath('public/reports/daily/2026-08-26/123.html', '123', '2026-08-26'), true);
  assert.equal(isAllowedReportPath('src/main.tsx', '123', '2026-08-26'), false);
  const key = 'DEEPSEEK_API_KEY';
  const hubToken = 'HUB_ACTIONS_TOKEN';
  const safe = redactSecrets(`Bearer abc ${key}=secret ${hubToken}=token`);
  assert.equal(safe.includes('secret'), false);
  assert.equal(safe.includes('token'), false);
});

const authEnv = {
  REPORT_GENERATION_LOCK: {} as never,
  HUB_ACTIONS_TOKEN: 'unused-test-token',
  REPORT_AUTH_USERNAME: 'ayu',
  REPORT_AUTH_PASSWORD: 'test-password',
};
const basicConfig = { username: 'ayu', password: 'test-password' };

const basic = (username: string, password: string): string =>
  `Basic ${Buffer.from(`${username}:${password}`, 'utf8').toString('base64')}`;

test('Basic Auth parses credentials and compares digests without early-exit strings', async () => {
  assert.deepEqual(parseBasicCredentials(basic('ayu', 'test-password')), {
    username: 'ayu',
    password: 'test-password',
  });
  assert.equal(parseBasicCredentials(null), null);
  assert.equal(parseBasicCredentials('Bearer token'), null);
  assert.equal(parseBasicCredentials('Basic ???'), null);
  assert.equal(await verifyBasicCredentials(basic('ayu', 'test-password'), basicConfig), true);
  assert.equal(await verifyBasicCredentials(basic('wrong', 'test-password'), basicConfig), false);
  assert.equal(await verifyBasicCredentials(basic('ayu', 'wrong'), basicConfig), false);
  assert.equal(await verifyBasicCredentials(null, basicConfig), false);
  assert.equal(await timingSafeEqual('same', 'same'), true);
  assert.equal(await timingSafeEqual('same', 'different'), false);
});

test('same-run reserved race waits for the first dispatch and returns one workflow ID', async () => {
  let record: LockRecord | null = null;
  let dispatchCalls = 0;
  let markDispatchStarted!: () => void;
  let releaseDispatch!: () => void;
  const dispatchStarted = new Promise<void>((resolve) => {
    markDispatchStarted = resolve;
  });
  const stub = {
    async fetch(request: Request): Promise<Response> {
      const url = new URL(request.url);
      if (url.pathname === '/acquire') {
        const current = record as Parameters<typeof acquireLock>[0];
        const result = acquireLock(current, url.searchParams.get('run_id') ?? '', url.searchParams.get('request_id') ?? '');
        if (result.created) record = result.record;
        return Response.json(result);
      }
      if (url.pathname === '/status') return Response.json({ record });
      if (url.pathname === '/workflow' || url.pathname === '/release') {
        if (!record) return Response.json({ record: null }, { status: 404 });
        const body = (await request.json()) as Record<string, unknown>;
        record = {
          ...record,
          ...(typeof body.workflowRunId === 'number' ? { workflowRunId: body.workflowRunId } : {}),
          ...(typeof body.workflowUrl === 'string' ? { workflowUrl: body.workflowUrl } : {}),
          ...(typeof body.state === 'string' ? { state: body.state as LockRecord['state'] } : {}),
        };
        return Response.json({ record });
      }
      return new Response('Not found', { status: 404 });
    },
  };
  const fakeClient = {
    runExists: async () => true,
    dispatch: async () => {
      dispatchCalls += 1;
      markDispatchStarted();
      return new Promise<{ workflowRunId: number; runUrl: string; htmlUrl: string }>((resolve) => {
        releaseDispatch = () => resolve({ workflowRunId: 77, runUrl: 'https://ci/run/77', htmlUrl: 'https://github/run/77' });
      });
    },
    getWorkflowRun: async () => ({ status: 'queued', conclusion: null, htmlUrl: 'https://github/run/77' }),
  };
  const testApp = createApp({
    createGithubClient: () => fakeClient,
    sleep: async () => {
      releaseDispatch();
      await Promise.resolve();
    },
  });
  const env = {
    ...authEnv,
    REPORT_GENERATION_LOCK: {
      idFromName: () => ({}),
      get: () => stub,
    },
  };
  const request = () => new Request('https://staging.example/api/generate', {
    method: 'POST',
    headers: { authorization: basic('ayu', 'test-password'), 'content-type': 'application/json' },
    body: JSON.stringify({ runId: '123' }),
  });

  const responseA = testApp.fetch(request(), env);
  await dispatchStarted;
  const responseB = testApp.fetch(request(), env);
  const [a, b] = await Promise.all([responseA, responseB]);
  const valueA = await a.json() as Record<string, unknown>;
  const valueB = await b.json() as Record<string, unknown>;
  assert.equal(dispatchCalls, 1);
  assert.equal(valueA.requestId, valueB.requestId);
  assert.equal(valueA.workflowRunId, 77);
  assert.equal(valueB.workflowRunId, 77);
});

test('missing, malformed and incorrect Basic Auth uniformly return 401 with a challenge', async () => {
  for (const authorization of [undefined, 'Bearer token', 'Basic ???', basic('wrong', 'test-password'), basic('ayu', 'wrong')]) {
    const request = new Request('https://staging.example/generate?run_id=123', {
      headers: authorization ? { authorization } : undefined,
    });
    const response = await app.fetch(request, authEnv);
    assert.equal(response.status, 401);
    assert.equal(response.headers.get('www-authenticate'), 'Basic realm="Ayu Running"');
    assert.deepEqual(await response.json(), { error: 'Unauthorized' });
  }
});

test('all generation and status paths require Basic Auth, while a valid user reaches the page', async () => {
  for (const path of ['/generate?run_id=123', '/api/generate', '/api/status/123']) {
    const response = await app.fetch(new Request(`https://staging.example${path}`), authEnv);
    assert.equal(response.status, 401);
  }
  const response = await app.fetch(
    new Request('https://staging.example/generate?run_id=123', {
      headers: { authorization: basic('ayu', 'test-password') },
    }),
    authEnv
  );
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /run_id/);
  assert.doesNotMatch(html, /test-password/);
});

test('production workflow is pinned to master input and output with Pages verification', () => {
  const workflow = readFileSync(new URL('../../.github/workflows/generate-report.yml', import.meta.url), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /run_id:\s*\n\s+description:/);
  assert.match(workflow, /request_id:\s*\n\s+description:/);
  assert.match(workflow, /group: ayu-report-\$\{\{ inputs\.run_id \}\}/);
  assert.match(workflow, /ref: master/);
  assert.match(workflow, /scripts\/publish_report\.py/);
  assert.match(workflow, /ayu-report-publish/);
  assert.match(workflow, /--target-branch "\$RUNNING_PAGE_BRANCH"/);
  assert.match(workflow, /--max-attempts 5/);
  assert.match(workflow, /scripts\/deploy_pages\.py/);
  assert.match(workflow, /gh-pages\.yml/);
  assert.match(workflow, /RUNNING_PAGE_BRANCH: master/);
});

test('generate page has no GET side effect and reports production completion text', async () => {
  const response = renderGeneratePage('123');
  const html = await response.text();
  assert.equal(response.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.match(html, /POST/);
  assert.match(html, /正在提交/);
  assert.match(html, /日报已生成/);
  assert.doesNotMatch(html, /测试分支写入成功/);
  assert.match(html, /run_id/);
});

test('Phase 6 bootstrap is separate from Basic Auth and rejects overwrite by default', async () => {
  const forwardedBodies: string[] = [];
  const brokerStub = {
    fetch: async (request: Request) => {
      forwardedBodies.push(await request.text());
      return Response.json({ credentialGeneration: 1, authState: 'READY' });
    },
  };
  const testApp = createApp({ createCorosBrokerStub: () => brokerStub });
  const env = { ...authEnv, COROS_BOOTSTRAP_SECRET: 'bootstrap-secret' };
  const body = JSON.stringify({
    issuer: 'https://mcpcn.coros.com',
    mcpUrl: 'https://mcpcn.coros.com/mcp',
    clientId: 'client',
    accessToken: 'access',
    refreshToken: 'refresh',
    accessExpiresAt: 9999999999,
    scope: 'mcp.tools openid offline_access',
  });
  const denied = await testApp.fetch(new Request('https://staging.example/internal/coros/bootstrap', { method: 'POST', body } ), env);
  assert.equal(denied.status, 401);
  const accepted = await testApp.fetch(new Request('https://staging.example/internal/coros/bootstrap', {
    method: 'POST',
    headers: { 'x-coros-bootstrap-secret': 'bootstrap-secret', 'content-type': 'application/json' },
    body,
  }), env);
  assert.equal(accepted.status, 200);
  assert.equal(forwardedBodies.length, 1);
  assert.equal(forwardedBodies[0], body);
});

test('Phase 6 bootstrap enforces the body size limit even without Content-Length', async () => {
  let forwarded = false;
  const brokerStub = { fetch: async () => { forwarded = true; return Response.json({ ok: true }); } };
  const testApp = createApp({ createCorosBrokerStub: () => brokerStub });
  const env = { ...authEnv, COROS_BOOTSTRAP_SECRET: 'bootstrap-secret' };
  const oversized = JSON.stringify({ value: 'x'.repeat(64 * 1024) });
  const response = await testApp.fetch(new Request('https://staging.example/internal/coros/bootstrap', {
    method: 'POST',
    headers: { 'x-coros-bootstrap-secret': 'bootstrap-secret', 'transfer-encoding': 'chunked' },
    body: oversized,
  }), env);
  assert.equal(response.status, 400);
  assert.equal(forwarded, false);
});

test('Phase 6 collector HMAC rejects wrong/stale requests and forwards only signed run identity', async () => {
  let forwarded = 0;
  const brokerStub = { fetch: async () => { forwarded += 1; return Response.json({ ok: true }); } };
  const nowMs = 1_000_000;
  const secret = 'collector-secret';
  const testApp = createApp({ createCorosBrokerStub: () => brokerStub, now: () => nowMs });
  const env = { ...authEnv, AYU_COLLECTOR_SHARED_SECRET: secret };
  const timestamp = Math.floor(nowMs / 1000);
  const requestId = 'request-1';
  const runId = '1787870493000';
  const body = JSON.stringify({ requestId, runId });
  const payload = await collectorSigningPayload(timestamp, requestId, runId, 'POST', '/internal/coros/probe', body);
  const signature = await signCollectorPayload(secret, payload);
  const baseHeaders = {
    'content-type': 'application/json',
    'x-ayu-timestamp': String(timestamp),
    'x-ayu-request-id': requestId,
    'x-ayu-run-id': runId,
    'x-ayu-signature': signature,
  };
  const wrong = await testApp.fetch(new Request('https://staging.example/internal/coros/probe', { method: 'POST', headers: { ...baseHeaders, 'x-ayu-signature': '00' }, body }), env);
  assert.equal(wrong.status, 401);
  const stale = await testApp.fetch(new Request('https://staging.example/internal/coros/probe', { method: 'POST', headers: { ...baseHeaders, 'x-ayu-timestamp': '1' }, body }), env);
  assert.equal(stale.status, 401);
  const accepted = await testApp.fetch(new Request('https://staging.example/internal/coros/probe', { method: 'POST', headers: baseHeaders, body }), env);
  assert.equal(accepted.status, 200);
  assert.equal(forwarded, 1);
});
