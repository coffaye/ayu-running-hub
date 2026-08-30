import assert from 'node:assert/strict';
import test from 'node:test';
import { CorosCredentialBroker, COROS_REAUTH_REQUIRED, type SqlCursorLike, type SqlStorageLike } from '../src/coros.ts';

const key = (seed: number): string => Buffer.from(Uint8Array.from({ length: 32 }, (_, index) => (seed + index) % 256)).toString('base64url');

class FakeSql implements SqlStorageLike {
  credential: Record<string, unknown> | null = null;
  replays = new Map<string, number>();

  exec(query: string, ...bindings: unknown[]): SqlCursorLike {
    const normalized = query.trim().toUpperCase();
    if (normalized.startsWith('CREATE TABLE')) return { toArray: () => [] };
    if (normalized.startsWith('DELETE FROM COROS_REPLAYS')) {
      const now = Number(bindings[0]);
      for (const [requestId, expiresAt] of this.replays) if (expiresAt < now) this.replays.delete(requestId);
      return { toArray: () => [] };
    }
    if (normalized.startsWith('SELECT REQUEST_ID FROM COROS_REPLAYS')) {
      const requestId = String(bindings[0]);
      const now = Number(bindings[1]);
      return { toArray: () => this.replays.get(requestId)! >= now ? [{ request_id: requestId }] : [] };
    }
    if (normalized.startsWith('INSERT INTO COROS_REPLAYS')) {
      const requestId = String(bindings[0]);
      if (this.replays.has(requestId)) throw new Error('unique constraint');
      this.replays.set(requestId, Number(bindings[1]));
      return { toArray: () => [] };
    }
    if (normalized.startsWith('UPDATE COROS_CREDENTIALS')) {
      if (this.credential) {
        this.credential.auth_state = bindings[0];
        this.credential.last_error = bindings[1];
        this.credential.updated_at = bindings[2];
      }
      return { toArray: () => [] };
    }
    if (normalized.startsWith('INSERT INTO COROS_CREDENTIALS')) {
      this.credential = {
        id: 1,
        schema_version: bindings[0],
        issuer: bindings[1],
        mcp_url: bindings[2],
        client_id: bindings[3],
        access_token_encrypted: bindings[4],
        refresh_token_encrypted: bindings[5],
        access_expires_at: bindings[6],
        scope: bindings[7],
        updated_at: bindings[8],
        credential_generation: bindings[9],
        auth_state: bindings[10],
        last_error: bindings[11],
      };
      return { toArray: () => [] };
    }
    if (normalized.startsWith('SELECT ') && normalized.includes('FROM COROS_CREDENTIALS')) {
      return { toArray: () => this.credential ? [this.credential] : [] };
    }
    throw new Error(`unhandled SQL: ${query}`);
  }
}

const stateFor = (sql: FakeSql) => ({ storage: { sql } });

const bootstrapBody = (reauthorize = false) => ({
  issuer: 'https://mcpcn.coros.com',
  mcpUrl: 'https://mcpcn.coros.com/mcp',
  clientId: 'public-client',
  accessToken: 'access-0',
  refreshToken: 'refresh-0',
  accessExpiresAt: 900,
  scope: 'mcp.tools openid offline_access',
  ...(reauthorize ? { reauthorize: true } : {}),
});

test('credential bootstrap stores only AES-GCM ciphertext and increments generations', async () => {
  let now = 1000;
  const sql = new FakeSql();
  const broker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(1) }, { now: () => now });
  const first = await broker.bootstrap(bootstrapBody());
  assert.equal(first.credentialGeneration, 1);
  assert.equal(String(sql.credential?.access_token_encrypted).includes('access-0'), false);
  assert.equal(String(sql.credential?.refresh_token_encrypted).includes('refresh-0'), false);
  await assert.rejects(() => broker.bootstrap(bootstrapBody()), (error: Error) => error.message === 'COROS_BOOTSTRAP_ALREADY_INITIALIZED');
  now = 1001;
  const second = await broker.bootstrap({ ...bootstrapBody(true), accessToken: 'access-1', refreshToken: 'refresh-1' });
  assert.equal(second.credentialGeneration, 2);
});

test('ten concurrent callers perform one refresh and observe one new generation', async () => {
  let refreshCalls = 0;
  const sql = new FakeSql();
  const fetcher = (async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/oauth2/token')) {
      refreshCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 20));
      return Response.json({ access_token: 'access-1', refresh_token: 'refresh-1', expires_in: 3600 });
    }
    throw new Error('unexpected network call');
  }) as typeof fetch;
  const broker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(2) }, { fetcher, now: () => 1000 });
  await broker.bootstrap(bootstrapBody());
  const results = await Promise.all(Array.from({ length: 10 }, () => broker.getValidCredential()));
  assert.equal(refreshCalls, 1);
  assert.deepEqual(new Set(results.map((result) => result.generation)), new Set([2]));
  assert.deepEqual(new Set(results.map((result) => result.accessToken)), new Set(['access-1']));
});

test('wrong KEK and corrupted ciphertext fail closed', async () => {
  const sql = new FakeSql();
  const broker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(3) }, { now: () => 1000 });
  await broker.bootstrap(bootstrapBody());
  const wrongKeyBroker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(4) }, { now: () => 1000 });
  await assert.rejects(() => wrongKeyBroker.getValidCredential(), (error: Error) => error.message === 'COROS_CREDENTIAL_UNAVAILABLE');
  sql.credential!.access_token_encrypted = '{"v":1,"iv":"bad","ciphertext":"bad"}';
  await assert.rejects(() => broker.getValidCredential(), (error: Error) => error.message === 'COROS_CREDENTIAL_UNAVAILABLE');
});

test('invalid_grant transitions the broker to COROS_REAUTH_REQUIRED without retrying the old token', async () => {
  let calls = 0;
  const sql = new FakeSql();
  const fetcher = (async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/oauth2/token')) {
      calls += 1;
      return Response.json({ error: 'invalid_grant' }, { status: 400 });
    }
    throw new Error('unexpected network call');
  }) as typeof fetch;
  const broker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(5) }, { fetcher, now: () => 1000 });
  await broker.bootstrap(bootstrapBody());
  await assert.rejects(() => broker.getValidCredential(), (error: Error) => error.message === COROS_REAUTH_REQUIRED);
  assert.equal((await broker.metadata())?.authState, COROS_REAUTH_REQUIRED);
  await assert.rejects(() => broker.getValidCredential(), (error: Error) => error.message === COROS_REAUTH_REQUIRED);
  assert.equal(calls, 1);
});

test('probe uses real MCP-shaped JSON/SSE responses, fixed read-only tools, and replay protection', async () => {
  const sql = new FakeSql();
  const requests: string[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/oauth2/token')) return Response.json({ error: 'unexpected refresh' }, { status: 400 });
    const body = JSON.parse(String(init?.body)) as { method: string; params: { name?: string } };
    requests.push(body.method);
    if (body.method === 'initialize') {
      return new Response('data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      });
    }
    if (body.method === 'tools/list') {
      return Response.json({ jsonrpc: '2.0', id: 2, result: { tools: [
        { name: 'querySportRecords' }, { name: 'getActivityDetail' }, { name: 'queryActivityLapData' },
        { name: 'queryTrainingLoadAssessment' }, { name: 'queryRecoveryStatus' }, { name: 'queryTrainingSchedule' },
      ] } });
    }
    const text = body.params.name === 'querySportRecords'
      ? '{"records":[{"startTimestamp":"1787870493000","labelId":"12345","sportType":100}]}'
      : 'ok';
    return Response.json({ jsonrpc: '2.0', id: 3, result: { content: [{ type: 'text', text }], isError: false } });
  }) as typeof fetch;
  const broker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(6) }, { fetcher, now: () => 1000 });
  await broker.bootstrap({ ...bootstrapBody(), accessExpiresAt: 5000 });
  const summary = await broker.probe('1787870493000', 'request-1');
  assert.deepEqual(summary.categories, { activity: true, detail: true, laps: true, load: true, recovery: true, tomorrow: true, fitness: false });
  assert.equal(summary.toolCount, 6);
  assert.equal(requests.filter((method) => method === 'tools/call').length, 6);
  await assert.rejects(() => broker.probe('1787870493000', 'request-1'), (error: Error) => error.message === 'COROS_REQUEST_REPLAYED');
});

test('daily bundle normalizes detail, laps, dated load, plans, and excludes historical current recovery', async () => {
  const sql = new FakeSql();
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/oauth2/token')) return Response.json({ error: 'unexpected refresh' }, { status: 400 });
    const body = JSON.parse(String(init?.body)) as { method: string; params: { name?: string; arguments?: Record<string, unknown> } };
    if (body.method === 'initialize') return Response.json({ jsonrpc: '2.0', id: 1, result: {} });
    if (body.method === 'tools/list') return Response.json({ jsonrpc: '2.0', id: 2, result: { tools: [
      { name: 'querySportRecords' }, { name: 'getActivityDetail' }, { name: 'queryActivityLapData' },
      { name: 'queryTrainingLoadAssessment' }, { name: 'queryRecoveryStatus' }, { name: 'queryTrainingSchedule' },
      { name: 'queryFitnessAssessmentOverview' },
    ] } });
    const name = body.params.name;
    const args = body.params.arguments ?? {};
    let result: unknown;
    if (name === 'querySportRecords') result = { records: [{ startTimestamp: '1787870493000', labelId: 'hidden', sportType: 100, title: '稳态跑' }] };
    else if (name === 'getActivityDetail') result = { distance: 11.28, duration: 3600, movingPace: 342, averagePace: 345, averageHeartRate: 146, cadence: 178, strideLength: 1.02, power: 197, elevationGain: 55, calories: 760, trainingLoad: 118, aerobicTrainingEffect: 3.1, anaerobicTrainingEffect: 0.4, trainingFocus: '有氧耐力', performance: '良好', perceivedEffort: '中等' };
    else if (name === 'queryActivityLapData') result = { laps: [
      { lapIndex: 1, distance: 1, duration: 330, pace: 330, avgHr: 140, maxHr: 151, power: 190, cadence: 177 },
      { lapIndex: 2, distance: 1, duration: 345, pace: 345, avgHr: 146, maxHr: 158, power: 197, cadence: 178 },
    ] };
    else if (name === 'queryTrainingLoadAssessment') result = { records: [{ date: '2026-08-28', shortTermLoad: 410, longTermLoad: 520, ratio: 0.79, status: '平衡' } ] };
    else if (name === 'queryRecoveryStatus') result = { recoveryPercent: 74, estimatedFullRecoveryAt: '2026-08-31T02:00:00Z' };
    else if (name === 'queryTrainingSchedule' && args.startDate === '20260828') result = 'Training Schedule\n========================\n\n2026-08-28\n稳态跑\nDistance: 11.30 km\nEstimated Time: 1:00:00\nLoad: 120 TL';
    else if (name === 'queryTrainingSchedule') result = 'Training Schedule\n========================\n\n2026-08-29\n轻松跑\nDistance: 8.00 km\nEstimated Time: 45:00\nLoad: 70 TL';
    else if (name === 'queryFitnessAssessmentOverview') result = { runningFitness: 62.5 };
    else result = {};
    return Response.json({ jsonrpc: '2.0', id: 3, result: { content: [{ type: 'text', text: JSON.stringify(result) }], isError: false } });
  }) as typeof fetch;
  const broker = new CorosCredentialBroker(stateFor(sql), { COROS_CREDENTIAL_KEK: key(7) }, { fetcher, now: () => 1788000000 });
  await broker.bootstrap({ ...bootstrapBody(), accessExpiresAt: 9000000000 });
  const bundle = await broker.dailyBundle('1787870493000', 'bundle-1');
  assert.equal(bundle.schemaVersion, '1.0');
  assert.equal(bundle.reportDate, '2026-08-28');
  assert.equal(bundle.activity.distanceKm, 11.28);
  assert.equal(bundle.activity.trainingLoad, 118);
  assert.equal(bundle.activity.maxHeartRateBpm, 158);
  assert.equal(bundle.laps.length, 2);
  assert.equal(bundle.laps[0].heartRateBpm, 140);
  assert.equal(bundle.laps[1].maxHeartRateBpm, 158);
  assert.equal(bundle.trainingContext.planAssociation, 'MATCHED');
  assert.equal(bundle.trainingContext.todaySchedule?.estimatedDurationSec, 3600);
  assert.equal(bundle.trainingContext.todaySchedule?.plannedLoad, 120);
  assert.equal(bundle.tomorrowSchedule?.title, '轻松跑');
  assert.equal(bundle.recentLoad?.reportDate, '2026-08-28');
  assert.equal(bundle.recovery?.reportDateAligned, false);
  assert.equal(bundle.recovery?.recoveryPercent, null);
  assert.equal(bundle.fitness?.runningFitness, 62.5);
  const serialized = JSON.stringify(bundle);
  assert.equal(serialized.includes('labelId'), false);
  assert.equal(serialized.includes('hidden'), false);
  assert.equal(bundle.diagnostics?.laps.objectKeys.includes('avgHr'), true);
});
