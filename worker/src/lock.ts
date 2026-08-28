import { acquireLock, type LockRecord, type LockState } from './core.ts';

export interface SqlCursorLike {
  toArray?: () => Array<Record<string, unknown>>;
}

export interface LockStorageLike {
  get<T>(key: string): Promise<T | undefined>;
  put<T>(key: string, value: T): Promise<void>;
  sql?: { exec: (query: string, ...bindings: unknown[]) => SqlCursorLike };
}

export interface DurableObjectStateLike {
  storage: LockStorageLike;
  blockConcurrencyWhile?: <T>(callback: () => Promise<T>) => Promise<T>;
}

const ACTIVE_TTL_MS = 30 * 60 * 1000;

export class RunGenerationLock {
  private readonly state: DurableObjectStateLike;

  constructor(state: DurableObjectStateLike) {
    this.state = state;
    this.ensureSqlite();
  }

  private ensureSqlite(): void {
    this.state.storage.sql?.exec(
      'CREATE TABLE IF NOT EXISTS locks (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, workflow_run_id INTEGER, workflow_url TEXT, request_id TEXT NOT NULL, state TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)'
    );
  }

  private async read(): Promise<LockRecord | null> {
    if (this.state.storage.sql) {
      this.ensureSqlite();
      const rows = this.state.storage.sql.exec('SELECT run_id, workflow_run_id, workflow_url, request_id, state, created_at, updated_at FROM locks WHERE id = 1').toArray?.() ?? [];
      const row = rows[0];
      if (row) {
        return {
          runId: String(row.run_id),
          workflowRunId: typeof row.workflow_run_id === 'number' ? row.workflow_run_id : null,
          workflowUrl: typeof row.workflow_url === 'string' ? row.workflow_url : null,
          requestId: String(row.request_id),
          state: String(row.state) as LockState,
          createdAt: Number(row.created_at),
          updatedAt: Number(row.updated_at),
        };
      }
      return null;
    }
    return (await this.state.storage.get<LockRecord>('record')) ?? null;
  }

  private async write(record: LockRecord): Promise<void> {
    if (this.state.storage.sql) {
      this.ensureSqlite();
      this.state.storage.sql.exec(
        'INSERT INTO locks (id, run_id, workflow_run_id, workflow_url, request_id, state, created_at, updated_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id, workflow_run_id=excluded.workflow_run_id, workflow_url=excluded.workflow_url, request_id=excluded.request_id, state=excluded.state, created_at=excluded.created_at, updated_at=excluded.updated_at',
        record.runId,
        record.workflowRunId,
        record.workflowUrl ?? null,
        record.requestId,
        record.state,
        record.createdAt,
        record.updatedAt
      );
      return;
    }
    await this.state.storage.put('record', record);
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const run = async (): Promise<Response> => {
      const current = await this.read();
      if (url.pathname === '/acquire') {
        const runId = url.searchParams.get('run_id') ?? '';
        const requestId = url.searchParams.get('request_id') ?? '';
        const result = acquireLock(current, runId, requestId, Date.now(), ACTIVE_TTL_MS);
        if (result.created) await this.write(result.record);
        return Response.json({ created: result.created, record: result.record });
      }
      if (url.pathname === '/status') {
        return Response.json({ record: current });
      }
      if (url.pathname === '/workflow' || url.pathname === '/release') {
        if (!current) return Response.json({ record: null }, { status: 404 });
        const body = (await request.json()) as Record<string, unknown>;
        const next: LockRecord = {
          ...current,
          workflowRunId:
            typeof body.workflowRunId === 'number' ? body.workflowRunId : current.workflowRunId,
          workflowUrl: typeof body.workflowUrl === 'string' ? body.workflowUrl : current.workflowUrl,
          state: typeof body.state === 'string' ? (body.state as LockState) : current.state,
          updatedAt: Date.now(),
        };
        await this.write(next);
        return Response.json({ record: next });
      }
      return new Response('Not found', { status: 404 });
    };
    return this.state.blockConcurrencyWhile ? this.state.blockConcurrencyWhile(run) : run();
  }
}
