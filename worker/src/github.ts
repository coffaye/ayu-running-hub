import {
  buildDispatchPayload,
  normalizeRunId,
  parseDispatchResponse,
  runExistsInActivities,
  type DispatchDetails,
} from './core.ts';

export interface GithubClientConfig {
  token: string;
  repository: string;
  workflow: string;
  sourceRepository: string;
  fetcher?: typeof fetch;
  apiBaseUrl?: string;
}

const jsonHeaders = {
  accept: 'application/vnd.github+json',
  'content-type': 'application/json',
  'x-github-api-version': '2022-11-28',
};

export class GithubClient {
  private readonly fetcher: typeof fetch;
  private readonly apiBaseUrl: string;
  private readonly config: GithubClientConfig;

  constructor(config: GithubClientConfig) {
    this.config = config;
    if (!config.token) throw new Error('Hub Actions token is not configured');
    this.fetcher = config.fetcher ?? fetch;
    this.apiBaseUrl = config.apiBaseUrl ?? 'https://api.github.com';
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await this.fetcher(`${this.apiBaseUrl}${path}`, {
      ...init,
      headers: {
        ...jsonHeaders,
        authorization: `Bearer ${this.config.token}`,
        ...(init.headers ?? {}),
      },
    });
    return response;
  }

  async dispatch(runId: string, requestId: string): Promise<DispatchDetails> {
    const normalized = normalizeRunId(runId);
    const response = await this.request(
      `/repos/${this.config.repository}/actions/workflows/${this.config.workflow}/dispatches?return_run_details=true`,
      { method: 'POST', body: JSON.stringify(buildDispatchPayload(normalized, requestId)) }
    );
    if (!response.ok) throw new Error(`GitHub dispatch failed: ${response.status}`);
    const text = await response.text();
    if (!text.trim()) throw new Error('GitHub dispatch returned no workflow details');
    return parseDispatchResponse(JSON.parse(text));
  }

  async getWorkflowRun(workflowRunId: number): Promise<{ status: string; conclusion: string | null; htmlUrl: string | null }> {
    const response = await this.request(`/repos/${this.config.repository}/actions/runs/${workflowRunId}`);
    if (!response.ok) throw new Error(`GitHub status failed: ${response.status}`);
    const value = (await response.json()) as Record<string, unknown>;
    return {
      status: typeof value.status === 'string' ? value.status : 'unknown',
      conclusion: typeof value.conclusion === 'string' ? value.conclusion : null,
      htmlUrl: typeof value.html_url === 'string' ? value.html_url : null,
    };
  }

  async runExists(runId: string, ref = 'master'): Promise<boolean> {
    const normalized = normalizeRunId(runId);
    const response = await this.fetcher(
      `https://raw.githubusercontent.com/${this.config.sourceRepository}/${ref}/src/static/activities.json`,
      { headers: { accept: 'application/json', 'cache-control': 'max-age=30' } }
    );
    if (!response.ok) throw new Error(`running_page lookup failed: ${response.status}`);
    return runExistsInActivities(await response.json(), normalized);
  }
}
