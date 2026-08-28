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
} from '../src/core.ts';
import {
  parseBasicCredentials,
  timingSafeEqual,
  verifyBasicCredentials,
} from '../src/auth.ts';
import app, { validateGenerateBody } from '../src/index.ts';
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

test('staging workflow is pinned to master input data and report-only output', () => {
  const workflow = readFileSync(new URL('../../.github/workflows/generate-report.yml', import.meta.url), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /run_id:\s*\n\s+description:/);
  assert.match(workflow, /request_id:\s*\n\s+description:/);
  assert.match(workflow, /group: ayu-report-\$\{\{ inputs\.run_id \}\}/);
  assert.match(workflow, /ref: master/);
  assert.match(workflow, /ref: ayu-report-e2e/);
  assert.match(workflow, /public\/reports\/manifest\.json\|public\/reports\/daily\/\*/);
  assert.doesNotMatch(workflow, /ref: master[\s\S]*git push origin HEAD:master/);
});

test('generate page has no GET side effect and reports staging completion text', async () => {
  const response = renderGeneratePage('123');
  const html = await response.text();
  assert.equal(response.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.match(html, /POST/);
  assert.match(html, /正在提交/);
  assert.match(html, /日报已生成 · 测试分支写入成功/);
  assert.match(html, /run_id/);
});
