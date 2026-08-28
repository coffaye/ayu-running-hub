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
import { validateAccessClaims } from '../src/auth.ts';
import app, { validateGenerateBody } from '../src/index.ts';
import { renderGeneratePage } from '../src/pages.ts';

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

test('Access claims require issuer, audience and a live expiry', () => {
  const config = { issuer: 'https://access.example', audience: 'ayu', jwksUrl: 'https://access.example/.well-known/jwks.json' };
  assert.equal(validateAccessClaims({ iss: config.issuer, aud: ['ayu'], exp: 200 }, config, 100).aud[0], 'ayu');
  assert.throws(() => validateAccessClaims({ iss: 'wrong', aud: 'ayu', exp: 200 }, config, 100));
  assert.throws(() => validateAccessClaims({ iss: config.issuer, aud: 'other', exp: 200 }, config, 100));
  assert.throws(() => validateAccessClaims({ iss: config.issuer, aud: 'ayu', exp: 100 }, config, 100));
});

test('unconfigured Access fails closed before any generation route can run', async () => {
  const response = await app.fetch(
    new Request('https://staging.example/generate?run_id=123'),
    {
      REPORT_GENERATION_LOCK: {} as never,
      HUB_ACTIONS_TOKEN: '',
      ACCESS_ISSUER: '',
      ACCESS_AUDIENCE: '',
      ACCESS_JWKS_URL: '',
    }
  );
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: 'Access configuration required' });
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
