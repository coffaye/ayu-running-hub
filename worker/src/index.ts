import { unauthorizedResponse, verifyBasicCredentials } from './auth.ts';
import { normalizeRunId, type LockRecord } from './core.ts';
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

export interface Env {
  REPORT_GENERATION_LOCK: DurableObjectNamespaceLike;
  HUB_ACTIONS_TOKEN: string;
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
  });

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

const authenticate = async (request: Request, env: Env): Promise<Response | null> => {
  const valid = await verifyBasicCredentials(request.headers.get('authorization'), {
    username: env.REPORT_AUTH_USERNAME ?? 'ayu',
    password: env.REPORT_AUTH_PASSWORD ?? '',
  });
  return valid ? null : unauthorizedResponse();
};

const generate = async (request: Request, env: Env): Promise<Response> => {
  let runId: string;
  try {
    runId = validateGenerateBody(await request.json());
  } catch (error) {
    return jsonResponse({ error: error instanceof Error ? error.message : 'invalid request' }, 400);
  }
  const client = clientFor(env);
  if (!(await client.runExists(runId))) return jsonResponse({ error: 'run_id not found in running_page master' }, 404);
  const requestId = crypto.randomUUID();
  const stub = lockStub(env, runId);
  const acquired = await stub.fetch(lockRequest(`/acquire?request_id=${encodeURIComponent(requestId)}`, runId));
  const acquiredValue = (await acquired.json()) as { created: boolean; record: LockRecord };
  if (!acquiredValue.created) return jsonResponse(statusFromLock(acquiredValue.record), 202);
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

const status = async (runId: string, env: Env): Promise<Response> => {
  const stub = lockStub(env, runId);
  const response = await stub.fetch(lockRequest('/status', runId));
  if (!response.ok) return jsonResponse({ error: 'generation not found' }, 404);
  const value = (await response.json()) as { record: LockRecord | null };
  if (!value.record) return jsonResponse({ error: 'generation not found' }, 404);
  if (!value.record.workflowRunId || value.record.state === 'failure' || value.record.state === 'success') {
    return jsonResponse(statusFromLock(value.record));
  }
  try {
    const provider = await clientFor(env).getWorkflowRun(value.record.workflowRunId);
    const normalized = statusFromGithub(value.record, provider);
    if (normalized.state === 'success' || normalized.state === 'failure') {
      await stub.fetch(lockRequest('/release', runId, { method: 'POST', body: JSON.stringify({ state: normalized.state, workflowUrl: normalized.runUrl }) }));
    } else if (normalized.state === 'running') {
      await stub.fetch(lockRequest('/workflow', runId, { method: 'POST', body: JSON.stringify({ state: 'running', workflowUrl: normalized.runUrl }) }));
    }
    return jsonResponse(normalized);
  } catch {
    return jsonResponse(statusFromLock(value.record));
  }
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const denied = await authenticate(request, env);
    if (denied) return denied;
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/generate') {
      try {
        return renderGeneratePage(normalizeRunId(url.searchParams.get('run_id') ?? ''));
      } catch {
        return jsonResponse({ error: 'invalid run_id' }, 400);
      }
    }
    if (request.method === 'POST' && url.pathname === '/api/generate') return generate(request, env);
    const match = url.pathname.match(/^\/api\/status\/([^/]+)$/);
    if (request.method === 'GET' && match) {
      try {
        return status(normalizeRunId(decodeURIComponent(match[1])), env);
      } catch {
        return jsonResponse({ error: 'invalid run_id' }, 400);
      }
    }
    return new Response('Not found', { status: 404 });
  },
};

export { RunGenerationLock };
