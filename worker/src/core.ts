export type LockState = 'reserved' | 'queued' | 'running' | 'success' | 'failure';
export type PublicState = 'queued' | 'running' | 'success' | 'failure';

export interface LockRecord {
  runId: string;
  workflowRunId: number | null;
  workflowUrl?: string | null;
  requestId: string;
  state: LockState;
  createdAt: number;
  updatedAt: number;
}

export interface DispatchDetails {
  workflowRunId: number;
  runUrl: string;
  htmlUrl: string;
}

const RUN_ID = /^[0-9]+$/;

export const normalizeRunId = (value: unknown): string => {
  if (typeof value !== 'string') throw new Error('runId must be a string');
  const candidate = value.trim();
  if (!RUN_ID.test(candidate) || BigInt(candidate) <= 0n) {
    throw new Error('runId must contain positive decimal digits only');
  }
  return candidate;
};

export const runIdMatches = (value: unknown, runId: string): boolean => {
  if (typeof value === 'string') return value.trim() === runId;
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) {
    return String(value) === runId;
  }
  return false;
};

export const runExistsInActivities = (value: unknown, runId: string): boolean => {
  if (!Array.isArray(value)) return false;
  return value.some((row) => {
    if (!row || typeof row !== 'object') return false;
    const candidate = row as Record<string, unknown>;
    return runIdMatches(candidate.run_id, runId) || runIdMatches(candidate.runId, runId);
  });
};

export const buildDispatchPayload = (runId: string, requestId: string) => ({
  ref: 'main',
  inputs: { run_id: normalizeRunId(runId), request_id: requestId },
  return_run_details: true,
});

export const parseDispatchResponse = (value: unknown): DispatchDetails => {
  const root = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  const nested = root.workflow_run && typeof root.workflow_run === 'object'
    ? (root.workflow_run as Record<string, unknown>)
    : root;
  const workflowRunId = nested.workflow_run_id ?? nested.id;
  const runUrl = nested.run_url ?? nested.url;
  const htmlUrl = nested.html_url ?? nested.htmlUrl;
  if (
    typeof workflowRunId !== 'number' ||
    !Number.isSafeInteger(workflowRunId) ||
    typeof runUrl !== 'string' ||
    typeof htmlUrl !== 'string'
  ) {
    throw new Error('GitHub dispatch did not return workflow run details');
  }
  return { workflowRunId, runUrl, htmlUrl };
};

export const normalizeWorkflowState = (
  status: unknown,
  conclusion: unknown
): PublicState => {
  if (status === 'queued' || status === 'waiting' || status === 'requested') return 'queued';
  if (status === 'in_progress' || status === 'pending') return 'running';
  if (status === 'completed') return conclusion === 'success' ? 'success' : 'failure';
  return 'running';
};

export const isActiveLock = (record: LockRecord | null, now = Date.now(), ttlMs = 30 * 60 * 1000) =>
  Boolean(
    record &&
      (record.state === 'reserved' || record.state === 'queued' || record.state === 'running') &&
      now - record.updatedAt < ttlMs
  );

export const acquireLock = (
  current: LockRecord | null,
  runId: string,
  requestId: string,
  now = Date.now(),
  ttlMs = 30 * 60 * 1000
): { created: boolean; record: LockRecord } => {
  const normalized = normalizeRunId(runId);
  if (isActiveLock(current, now, ttlMs)) return { created: false, record: current as LockRecord };
  return {
    created: true,
    record: {
      runId: normalized,
      workflowRunId: null,
      workflowUrl: null,
      requestId,
      state: 'reserved',
      createdAt: now,
      updatedAt: now,
    },
  };
};

export const isAllowedReportPath = (path: string, runId: string, localDate: string): boolean => {
  const normalized = normalizeRunId(runId);
  return (
    path === 'public/reports/manifest.json' ||
    path === `public/reports/daily/${localDate}/${normalized}.html`
  );
};

export const redactSecrets = (value: string): string =>
  value
    .replace(/Bearer\s+[^\s"']+/gi, 'Bearer [redacted]')
    .replace(/(DEEPSEEK_API_KEY|HUB_ACTIONS_TOKEN|RUNNING_PAGE_WRITE_TOKEN)(\s*[:=]\s*)[^\s,}]+/gi, '$1$2[redacted]');

