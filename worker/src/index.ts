import {
  unauthorizedResponse,
  timingSafeEqual,
  verifyBasicCredentials,
  verifyCollectorRequest,
} from './auth.ts';
import { normalizeRunId, type LockRecord } from './core.ts';
import { CorosCredentialBroker, CorosBrokerError } from './coros.ts';
import { GithubClient } from './github.ts';
import { RunGenerationLock } from './lock.ts';
import { jsonResponse, renderGeneratePage } from './pages.ts';
import { statusFromGithub, statusFromLock } from './status.ts';

export interface DurableObjectIdLike {}
export interface DurableObjectStubLike { fetch: (request: Request) => Promise<Response> }
export interface DurableObjectNamespaceLike {
  idFromName: (name: string) => DurableObjectIdLike;
  get: (id: DurableObjectIdLike) => DurableObjectStubLike;
}

export interface GithubClientLike {
  runExists: (runId: string) => Promise<boolean>;
  dispatch: (runId: string, requestId: string) => Promise<{
    workflowRunId: number;
    runUrl: string;
    htmlUrl: string;
  }>;
  getWorkflowRun: (workflowRunId: number) => Promise<{
    status: string;
    conclusion: string | null;
    htmlUrl: string | null;
  }>;
  getLiveReportUrl?: (runId: string) => Promise<string | null>;
}

export interface WorkerDependencies {
  createGithubClient?: (env: Env) => GithubClientLike;
  sleep?: (milliseconds: number) => Promise<void>;
  createCorosBrokerStub?: (env: Env) => DurableObjectStubLike;
  now?: () => number;
}

export interface Env {
  REPORT_GENERATION_LOCK: DurableObjectNamespaceLike;
  HUB_ACTIONS_TOKEN: string;
  COROS_CREDENTIAL_BROKER?: DurableObjectNamespaceLike;
  AYU_COLLECTOR_SHARED_SECRET?: string;
  COROS_BOOTSTRAP_SECRET?: string;
  COROS_CREDENTIAL_KEK?: string;
  REPORT_AUTH_USERNAME?: string;
  REPORT_AUTH_PASSWORD?: string;
  HUB_REPOSITORY?: string;
  HUB_WORKFLOW?: string;
  RUNNING_PAGE_REPOSITORY?: string;
}

const clientFor = (env: Env) =>
  new GithubClient({
    token: env.HUB_ACTIONS_TOKEN,
    repository: env.HUB_REPOSITORY ?? 'coffaye/ayu-running-hub',
    workflow: env.HUB_WORKFLOW ?? 'generate-report.yml',
    sourceRepository: env.RUNNING_PAGE_REPOSITORY ?? 'coffaye/running_page',
    pagesOrigin: 'https://coffaye.github.io/running_page',
  });

const delay = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

const lockStub = (env: Env, runId: string): DurableObjectStubLike =>
  env.REPORT_GENERATION_LOCK.get(env.REPORT_GENERATION_LOCK.idFromName(`run:${runId}`));

const lockRequest = (path: string, runId: string, init: RequestInit = {}) =>
  new Request(`https://lock.internal${path}${path.includes('?') ? '&' : '?'}run_id=${encodeURIComponent(runId)}`, init);

export const validateGenerateBody = (value: unknown): string => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('request body must be an object');
  const keys = Object.keys(value as Record<string, unknown>);
  if (keys.length !== 1 || keys[0] !== 'runId') throw new Error('only runId is accepted');
  return normalizeRunId((value as Record<string, unknown>).runId);
};

export interface WorkflowAssignmentWaitOptions {
  initialIntervalMs?: number;
  maxIntervalMs?: number;
  maxWaitMs?: number;
}

export const awaitWorkflowAssignment = async (
  stub: DurableObjectStubLike,
  runId: string,
  initialRecord: LockRecord,
  sleep: (milliseconds: number) => Promise<void> = delay,
  options: WorkflowAssignmentWaitOptions = {}
): Promise<LockRecord> => {
  if (initialRecord.state !== 'reserved' || initialRecord.workflowRunId !== null) return initialRecord;
  const initialIntervalMs = options.initialIntervalMs ?? 75;
  const maxIntervalMs = options.maxIntervalMs ?? 250;
  const maxWaitMs = options.maxWaitMs ?? 5000;
  const startedAt = Date.now();
  let intervalMs = initialIntervalMs;
  let current = initialRecord;
  while (Date.now() - startedAt < maxWaitMs) {
    await sleep(Math.min(intervalMs, Math.max(0, maxWaitMs - (Date.now() - startedAt))));
    const response = await stub.fetch(lockRequest('/status', runId));
    if (!response.ok) return current;
    const value = (await response.json()) as { record: LockRecord | null };
    if (!value.record) return current;
    current = value.record;
    if (current.workflowRunId !== null || current.state === 'failure' || current.state === 'success') return current;
    intervalMs = Math.min(maxIntervalMs, intervalMs * 2);
  }
  return current;
};

const authenticate = async (request: Request, env: Env): Promise<Response | null> => {
  const valid = await verifyBasicCredentials(request.headers.get('authorization'), {
    username: env.REPORT_AUTH_USERNAME ?? 'ayu',
    password: env.REPORT_AUTH_PASSWORD ?? '',
  });
  return valid ? null : unauthorizedResponse();
};

const generate = async (request: Request, env: Env, dependencies: Required<WorkerDependencies>): Promise<Response> => {
  let runId: string;
  try {
    runId = validateGenerateBody(await request.json());
  } catch (error) {
    return jsonResponse({ error: error instanceof Error ? error.message : 'invalid request' }, 400);
  }
  const client = dependencies.createGithubClient(env);
  if (!(await client.runExists(runId))) return jsonResponse({ error: 'run_id not found in running_page master' }, 404);
  const requestId = crypto.randomUUID();
  const stub = lockStub(env, runId);
  const acquired = await stub.fetch(lockRequest(`/acquire?request_id=${encodeURIComponent(requestId)}`, runId));
  const acquiredValue = (await acquired.json()) as { created: boolean; record: LockRecord };
  if (!acquiredValue.created) {
    const settled = await awaitWorkflowAssignment(stub, runId, acquiredValue.record, dependencies.sleep);
    return jsonResponse(statusFromLock(settled), 202);
  }
  try {
    const dispatch = await client.dispatch(runId, requestId);
    const updated = await stub.fetch(lockRequest('/workflow', runId, { method: 'POST', body: JSON.stringify({ workflowRunId: dispatch.workflowRunId, workflowUrl: dispatch.htmlUrl, state: 'queued' }) }));
    const updatedValue = (await updated.json()) as { record: LockRecord };
    return jsonResponse(statusFromLock(updatedValue.record), 202);
  } catch (error) {
    await stub.fetch(lockRequest('/release', runId, { method: 'POST', body: JSON.stringify({ state: 'failure' }) }));
    return jsonResponse({ error: 'workflow dispatch failed' }, 502);
  }
};

const status = async (runId: string, env: Env, dependencies: Required<WorkerDependencies>): Promise<Response> => {
  const stub = lockStub(env, runId);
  const response = await stub.fetch(lockRequest('/status', runId));
  if (!response.ok) return jsonResponse({ error: 'generation not found' }, 404);
  const value = (await response.json()) as { record: LockRecord | null };
  if (!value.record) return jsonResponse({ error: 'generation not found' }, 404);
  if (!value.record.workflowRunId || value.record.state === 'failure' || value.record.state === 'success') {
    const result = statusFromLock(value.record);
    if (result.state === 'success') {
      try {
        result.reportUrl = await dependencies.createGithubClient(env).getLiveReportUrl?.(runId) ?? null;
      } catch {
        result.reportUrl = null;
      }
    }
    return jsonResponse(result);
  }
  try {
    const provider = await dependencies.createGithubClient(env).getWorkflowRun(value.record.workflowRunId);
    const normalized = statusFromGithub(value.record, provider);
    if (normalized.state === 'success' || normalized.state === 'failure') {
      await stub.fetch(lockRequest('/release', runId, { method: 'POST', body: JSON.stringify({ state: normalized.state, workflowUrl: normalized.runUrl }) }));
    } else if (normalized.state === 'running') {
      await stub.fetch(lockRequest('/workflow', runId, { method: 'POST', body: JSON.stringify({ state: 'running', workflowUrl: normalized.runUrl }) }));
    }
    if (normalized.state === 'success') {
      try {
        normalized.reportUrl = await dependencies.createGithubClient(env).getLiveReportUrl?.(runId) ?? null;
      } catch {
        normalized.reportUrl = null;
      }
    }
    return jsonResponse(normalized);
  } catch {
    return jsonResponse(statusFromLock(value.record));
  }
};

const corosBrokerStub = (env: Env): DurableObjectStubLike => {
  if (!env.COROS_CREDENTIAL_BROKER) throw new CorosBrokerError('COROS_BROKER_NOT_CONFIGURED', 503);
  return env.COROS_CREDENTIAL_BROKER.get(env.COROS_CREDENTIAL_BROKER.idFromName('coros:primary'));
};

const internalUnauthorized = (): Response =>
  jsonResponse({ error: 'Unauthorized' }, 401);

const parseObjectBody = (body: string): Record<string, unknown> | null => {
  try {
    const value: unknown = JSON.parse(body);
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
  } catch {
    return null;
  }
};

const bootstrap = async (request: Request, env: Env, dependencies: Required<WorkerDependencies>): Promise<Response> => {
  if (!env.COROS_BOOTSTRAP_SECRET) return jsonResponse({ error: 'Not found' }, 404);
  const supplied = request.headers.get('x-coros-bootstrap-secret') ?? '';
  const valid = supplied.length > 0 && await timingSafeEqual(supplied, env.COROS_BOOTSTRAP_SECRET);
  if (!valid) return internalUnauthorized();
  const contentLength = Number(request.headers.get('content-length') ?? '0');
  if (contentLength > 64 * 1024) return jsonResponse({ error: 'COROS_BOOTSTRAP_INVALID' }, 400);
  const body = await request.text();
  if (body.length > 64 * 1024) return jsonResponse({ error: 'COROS_BOOTSTRAP_INVALID' }, 400);
  if (!parseObjectBody(body)) return jsonResponse({ error: 'COROS_BOOTSTRAP_INVALID' }, 400);
  try {
    return await dependencies.createCorosBrokerStub(env).fetch(new Request('https://coros-broker.internal/bootstrap', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body,
    }));
  } catch {
    return jsonResponse({ error: 'COROS_BROKER_NOT_CONFIGURED' }, 503);
  }
};

const validateProbeBody = (body: Record<string, unknown>, auth: { requestId: string; runId: string }): boolean => {
  const keys = Object.keys(body).sort();
  return keys.length === 2 && keys[0] === 'requestId' && keys[1] === 'runId'
    && body.requestId === auth.requestId
    && body.runId === auth.runId;
};

const corosCollector = async (request: Request, env: Env, dependencies: Required<WorkerDependencies>, brokerPath: '/probe' | '/daily-bundle'): Promise<Response> => {
  if (!env.AYU_COLLECTOR_SHARED_SECRET) return jsonResponse({ error: 'Not found' }, 404);
  const auth = await verifyCollectorRequest(request, env.AYU_COLLECTOR_SHARED_SECRET, Math.floor(dependencies.now() / 1000));
  if (!auth) return internalUnauthorized();
  const body = parseObjectBody(auth.body);
  if (!body || !validateProbeBody(body, auth)) return jsonResponse({ error: 'COROS_PROBE_INVALID' }, 400);
  try {
    return await dependencies.createCorosBrokerStub(env).fetch(new Request(`https://coros-broker.internal${brokerPath}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ runId: auth.runId, requestId: auth.requestId }),
    }));
  } catch {
    return jsonResponse({ error: 'COROS_BROKER_NOT_CONFIGURED' }, 503);
  }
};

export const createApp = (overrides: WorkerDependencies = {}) => {
  const dependencies: Required<WorkerDependencies> = {
    createGithubClient: overrides.createGithubClient ?? clientFor,
    sleep: overrides.sleep ?? delay,
    createCorosBrokerStub: overrides.createCorosBrokerStub ?? corosBrokerStub,
    now: overrides.now ?? (() => Date.now()),
  };
  return {
    async fetch(request: Request, env: Env): Promise<Response> {
      const url = new URL(request.url);
      if (request.method === 'POST' && url.pathname === '/internal/coros/bootstrap') return bootstrap(request, env, dependencies);
      if (request.method === 'POST' && url.pathname === '/internal/coros/probe') return corosCollector(request, env, dependencies, '/probe');
      if (request.method === 'POST' && url.pathname === '/internal/coros/daily-bundle') return corosCollector(request, env, dependencies, '/daily-bundle');
      const denied = await authenticate(request, env);
      if (denied) return denied;
      if (request.method === 'GET' && url.pathname === '/generate') {
        try {
          return renderGeneratePage(normalizeRunId(url.searchParams.get('run_id') ?? ''));
        } catch {
          return jsonResponse({ error: 'invalid run_id' }, 400);
        }
      }
      if (request.method === 'POST' && url.pathname === '/api/generate') return generate(request, env, dependencies);
      const match = url.pathname.match(/^\/api\/status\/([^/]+)$/);
      if (request.method === 'GET' && match) {
        try {
          return status(normalizeRunId(decodeURIComponent(match[1])), env, dependencies);
        } catch {
          return jsonResponse({ error: 'invalid run_id' }, 400);
        }
      }
      return new Response('Not found', { status: 404 });
    },
  };
};

const app = createApp();

export default app;

export { RunGenerationLock, CorosCredentialBroker };
