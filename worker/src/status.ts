import { normalizeWorkflowState, type LockRecord, type PublicState } from './core.ts';

export interface StatusResponse {
  runId: string;
  state: PublicState;
  workflowRunId: number | null;
  requestId: string;
  runUrl?: string | null;
  reportUrl?: string | null;
}

export const statusFromLock = (record: LockRecord): StatusResponse => ({
  runId: record.runId,
  state:
    record.state === 'success' || record.state === 'failure'
      ? record.state
      : record.workflowRunId
        ? record.state === 'running'
          ? 'running'
          : 'queued'
        : 'queued',
  workflowRunId: record.workflowRunId,
  requestId: record.requestId,
  runUrl: record.workflowUrl ?? null,
  reportUrl: null,
});

export const statusFromGithub = (
  record: LockRecord,
  provider: { status: unknown; conclusion: unknown; htmlUrl?: string | null }
): StatusResponse => ({
  runId: record.runId,
  state: normalizeWorkflowState(provider.status, provider.conclusion),
  workflowRunId: record.workflowRunId,
  requestId: record.requestId,
  runUrl: provider.htmlUrl ?? record.workflowUrl ?? null,
  reportUrl: null,
});
