const COROS_MCP_PROTOCOL_VERSION = '2025-06-18';
const COROS_CLIENT_NAME = 'ayu-running-hub-phase6';
const COROS_CLIENT_VERSION = '0.1.0';
const ACCESS_EXPIRY_SKEW_SECONDS = 120;
const REPLAY_WINDOW_SECONDS = 5 * 60;
const ENCRYPTED_FORMAT_VERSION = 1;
const CREDENTIAL_SCHEMA_VERSION = 1;

export const COROS_REAUTH_REQUIRED = 'COROS_REAUTH_REQUIRED' as const;

export type CorosAuthState = 'READY' | typeof COROS_REAUTH_REQUIRED;

export class CorosBrokerError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status = 502) {
    super(code);
    this.name = 'CorosBrokerError';
    this.code = code;
    this.status = status;
  }
}

export interface SqlCursorLike {
  toArray?: () => Array<Record<string, unknown>>;
}

export interface SqlStorageLike {
  exec: (query: string, ...bindings: unknown[]) => SqlCursorLike;
}

export interface DurableObjectStateLike {
  storage: { sql?: SqlStorageLike };
}

export interface CorosCredentialBrokerEnv {
  COROS_CREDENTIAL_KEK?: string;
}

export interface CorosBrokerDependencies {
  fetcher?: typeof fetch;
  now?: () => number;
  accessExpirySkewSeconds?: number;
}

interface TokenSet {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  tokenType: string;
  scope: string;
  clientId: string;
}

interface CredentialRow extends TokenSet {
  schemaVersion: number;
  issuer: string;
  mcpUrl: string;
  updatedAt: number;
  credentialGeneration: number;
  authState: CorosAuthState;
  lastError: string | null;
}

export interface CorosCredentialMetadata {
  schemaVersion: number;
  issuer: string;
  mcpUrl: string;
  clientId: string;
  accessExpiresAt: number;
  scope: string;
  updatedAt: number;
  credentialGeneration: number;
  authState: CorosAuthState;
}

export interface CorosProbeSummary {
  runDate: string;
  tomorrowDate: string;
  credentialGeneration: number;
  accessExpiresAt: number;
  toolCount: number;
  categories: {
    activity: boolean;
    detail: boolean;
    laps: boolean;
    load: boolean;
    recovery: boolean;
    tomorrow: boolean;
    fitness: boolean;
  };
}

interface EncryptedSecret {
  v: number;
  iv: string;
  ciphertext: string;
}

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

const encodeBase64Url = (bytes: Uint8Array): string => {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
};

const decodeBase64Url = (value: string): Uint8Array => {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(normalized)) throw new CorosBrokerError('COROS_CREDENTIAL_UNAVAILABLE', 503);
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  try {
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    throw new CorosBrokerError('COROS_CREDENTIAL_UNAVAILABLE', 503);
  }
};

const bytesToHex = (bytes: Uint8Array): string => Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');

const parseJsonText = (text: string): unknown => {
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new CorosBrokerError('COROS_REMOTE_INVALID_RESPONSE', 502);
  }
};

const parseMcpBody = (text: string, contentType: string): unknown => {
  if (!contentType.toLowerCase().includes('text/event-stream')) return parseJsonText(text);
  const dataLines: string[] = [];
  let current: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line) {
      if (current.length) dataLines.push(current.join('\n'));
      current = [];
      continue;
    }
    if (line.startsWith('data:')) current.push(line.slice(5).trimStart());
  }
  if (current.length) dataLines.push(current.join('\n'));
  if (!dataLines.length) throw new CorosBrokerError('COROS_REMOTE_INVALID_RESPONSE', 502);
  return parseJsonText(dataLines[dataLines.length - 1]);
};

const objectValue = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

const requireString = (value: unknown, code: string, maxLength = 16000): string => {
  if (typeof value !== 'string' || value.length === 0 || value.length > maxLength) throw new CorosBrokerError(code, 400);
  return value;
};

const requirePositiveInteger = (value: unknown, code: string): number => {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) throw new CorosBrokerError(code, 400);
  return value;
};

const allowedIssuer = (issuer: string): boolean =>
  ['https://mcp.coros.com', 'https://mcpcn.coros.com', 'https://mcpeu.coros.com', 'https://mcpus.coros.com'].includes(issuer);

const sqlRows = (cursor: SqlCursorLike): Array<Record<string, unknown>> => cursor.toArray?.() ?? [];

const rowToMetadata = (row: CredentialRow): CorosCredentialMetadata => ({
  schemaVersion: row.schemaVersion,
  issuer: row.issuer,
  mcpUrl: row.mcpUrl,
  clientId: row.clientId,
  accessExpiresAt: row.expiresAt,
  scope: row.scope,
  updatedAt: row.updatedAt,
  credentialGeneration: row.credentialGeneration,
  authState: row.authState,
});

export class CorosCredentialBroker {
  private readonly state: DurableObjectStateLike;
  private readonly env: CorosCredentialBrokerEnv;
  private readonly fetcher: typeof fetch;
  private readonly now: () => number;
  private readonly accessExpirySkewSeconds: number;
  private keyPromise: Promise<CryptoKey> | null = null;
  private refreshInFlight: Promise<CredentialRow> | null = null;

  constructor(state: DurableObjectStateLike, env: CorosCredentialBrokerEnv, dependencies: CorosBrokerDependencies = {}) {
    this.state = state;
    this.env = env;
    this.fetcher = dependencies.fetcher ?? fetch.bind(globalThis);
    this.now = dependencies.now ?? (() => Math.floor(Date.now() / 1000));
    this.accessExpirySkewSeconds = dependencies.accessExpirySkewSeconds ?? ACCESS_EXPIRY_SKEW_SECONDS;
    this.ensureSchema();
  }

  private get sql(): SqlStorageLike {
    if (!this.state.storage.sql) throw new CorosBrokerError('COROS_STORAGE_UNAVAILABLE', 503);
    return this.state.storage.sql;
  }

  private ensureSchema(): void {
    this.sql.exec(
      'CREATE TABLE IF NOT EXISTS coros_credentials (id INTEGER PRIMARY KEY CHECK (id = 1), schema_version INTEGER NOT NULL, issuer TEXT NOT NULL, mcp_url TEXT NOT NULL, client_id TEXT NOT NULL, access_token_encrypted TEXT NOT NULL, refresh_token_encrypted TEXT NOT NULL, access_expires_at INTEGER NOT NULL, scope TEXT NOT NULL, updated_at INTEGER NOT NULL, credential_generation INTEGER NOT NULL, auth_state TEXT NOT NULL, last_error TEXT)'
    );
    this.sql.exec(
      'CREATE TABLE IF NOT EXISTS coros_replays (request_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)'
    );
  }

  private async cryptoKey(): Promise<CryptoKey> {
    if (!this.keyPromise) {
      this.keyPromise = Promise.resolve().then(async () => {
        const raw = decodeBase64Url(this.env.COROS_CREDENTIAL_KEK ?? '');
        if (raw.byteLength !== 32) throw new CorosBrokerError('COROS_CREDENTIAL_UNAVAILABLE', 503);
        return crypto.subtle.importKey('raw', raw as unknown as BufferSource, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
      });
    }
    return this.keyPromise;
  }

  private async encryptSecret(value: string): Promise<string> {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv as unknown as BufferSource }, await this.cryptoKey(), textEncoder.encode(value) as unknown as BufferSource);
    return JSON.stringify({
      v: ENCRYPTED_FORMAT_VERSION,
      iv: encodeBase64Url(iv),
      ciphertext: encodeBase64Url(new Uint8Array(ciphertext)),
    } satisfies EncryptedSecret);
  }

  private async decryptSecret(serialized: string): Promise<string> {
    let encrypted: EncryptedSecret;
    try {
      encrypted = JSON.parse(serialized) as EncryptedSecret;
    } catch {
      throw new CorosBrokerError('COROS_CREDENTIAL_UNAVAILABLE', 503);
    }
    if (encrypted.v !== ENCRYPTED_FORMAT_VERSION || typeof encrypted.iv !== 'string' || typeof encrypted.ciphertext !== 'string') {
      throw new CorosBrokerError('COROS_CREDENTIAL_UNAVAILABLE', 503);
    }
    try {
      const plaintext = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: decodeBase64Url(encrypted.iv) as unknown as BufferSource },
        await this.cryptoKey(),
        decodeBase64Url(encrypted.ciphertext) as unknown as BufferSource,
      );
      return textDecoder.decode(plaintext);
    } catch {
      throw new CorosBrokerError('COROS_CREDENTIAL_UNAVAILABLE', 503);
    }
  }

  private async readCredential(): Promise<CredentialRow | null> {
    const row = sqlRows(this.sql.exec('SELECT schema_version, issuer, mcp_url, client_id, access_token_encrypted, refresh_token_encrypted, access_expires_at, scope, updated_at, credential_generation, auth_state, last_error FROM coros_credentials WHERE id = 1'))[0];
    if (!row) return null;
    const accessToken = await this.decryptSecret(String(row.access_token_encrypted));
    const refreshToken = await this.decryptSecret(String(row.refresh_token_encrypted));
    return {
      schemaVersion: Number(row.schema_version),
      issuer: String(row.issuer),
      mcpUrl: String(row.mcp_url),
      clientId: String(row.client_id),
      accessToken,
      refreshToken,
      expiresAt: Number(row.access_expires_at),
      tokenType: 'Bearer',
      scope: String(row.scope),
      updatedAt: Number(row.updated_at),
      credentialGeneration: Number(row.credential_generation),
      authState: String(row.auth_state) as CorosAuthState,
      lastError: typeof row.last_error === 'string' ? row.last_error : null,
    };
  }

  private async writeCredential(row: CredentialRow): Promise<void> {
    const accessTokenEncrypted = await this.encryptSecret(row.accessToken);
    const refreshTokenEncrypted = await this.encryptSecret(row.refreshToken);
    this.sql.exec(
      'INSERT INTO coros_credentials (id, schema_version, issuer, mcp_url, client_id, access_token_encrypted, refresh_token_encrypted, access_expires_at, scope, updated_at, credential_generation, auth_state, last_error) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET schema_version=excluded.schema_version, issuer=excluded.issuer, mcp_url=excluded.mcp_url, client_id=excluded.client_id, access_token_encrypted=excluded.access_token_encrypted, refresh_token_encrypted=excluded.refresh_token_encrypted, access_expires_at=excluded.access_expires_at, scope=excluded.scope, updated_at=excluded.updated_at, credential_generation=excluded.credential_generation, auth_state=excluded.auth_state, last_error=excluded.last_error',
      row.schemaVersion,
      row.issuer,
      row.mcpUrl,
      row.clientId,
      accessTokenEncrypted,
      refreshTokenEncrypted,
      row.expiresAt,
      row.scope,
      row.updatedAt,
      row.credentialGeneration,
      row.authState,
      row.lastError,
    );
  }

  private markReauthRequired(): void {
    this.sql.exec('UPDATE coros_credentials SET auth_state = ?, last_error = ?, updated_at = ? WHERE id = 1', COROS_REAUTH_REQUIRED, 'invalid_grant', this.now());
  }

  public async metadata(): Promise<CorosCredentialMetadata | null> {
    const row = sqlRows(this.sql.exec('SELECT schema_version, issuer, mcp_url, client_id, access_expires_at, scope, updated_at, credential_generation, auth_state FROM coros_credentials WHERE id = 1'))[0];
    if (!row) return null;
    return {
      schemaVersion: Number(row.schema_version),
      issuer: String(row.issuer),
      mcpUrl: String(row.mcp_url),
      clientId: String(row.client_id),
      accessExpiresAt: Number(row.access_expires_at),
      scope: String(row.scope),
      updatedAt: Number(row.updated_at),
      credentialGeneration: Number(row.credential_generation),
      authState: String(row.auth_state) as CorosAuthState,
    };
  }

  public async bootstrap(value: unknown): Promise<CorosCredentialMetadata> {
    const body = objectValue(value);
    const allowedKeys = new Set(['issuer', 'mcpUrl', 'clientId', 'accessToken', 'refreshToken', 'accessExpiresAt', 'scope', 'reauthorize']);
    if (Object.keys(body).some((key) => !allowedKeys.has(key))) throw new CorosBrokerError('COROS_BOOTSTRAP_INVALID', 400);
    const issuer = requireString(body.issuer, 'COROS_BOOTSTRAP_INVALID', 200).replace(/\/$/, '');
    const mcpUrl = requireString(body.mcpUrl, 'COROS_BOOTSTRAP_INVALID', 300).replace(/\/$/, '');
    if (!allowedIssuer(issuer) || mcpUrl !== `${issuer}/mcp`) throw new CorosBrokerError('COROS_BOOTSTRAP_INVALID', 400);
    const clientId = requireString(body.clientId, 'COROS_BOOTSTRAP_INVALID', 300);
    const accessToken = requireString(body.accessToken, 'COROS_BOOTSTRAP_INVALID');
    const refreshToken = requireString(body.refreshToken, 'COROS_BOOTSTRAP_INVALID');
    const accessExpiresAt = requirePositiveInteger(body.accessExpiresAt, 'COROS_BOOTSTRAP_INVALID');
    const scope = requireString(body.scope, 'COROS_BOOTSTRAP_INVALID', 500);
    if (!scope.split(/\s+/).includes('offline_access') || !scope.split(/\s+/).includes('mcp.tools')) {
      throw new CorosBrokerError('COROS_BOOTSTRAP_INVALID', 400);
    }
    if (body.reauthorize !== undefined && typeof body.reauthorize !== 'boolean') throw new CorosBrokerError('COROS_BOOTSTRAP_INVALID', 400);
    const existing = await this.metadata();
    if (existing && body.reauthorize !== true) throw new CorosBrokerError('COROS_BOOTSTRAP_ALREADY_INITIALIZED', 409);
    const nextGeneration = existing ? existing.credentialGeneration + 1 : 1;
    const row: CredentialRow = {
      schemaVersion: CREDENTIAL_SCHEMA_VERSION,
      issuer,
      mcpUrl,
      clientId,
      accessToken,
      refreshToken,
      expiresAt: accessExpiresAt,
      tokenType: 'Bearer',
      scope,
      updatedAt: this.now(),
      credentialGeneration: nextGeneration,
      authState: 'READY',
      lastError: null,
    };
    await this.writeCredential(row);
    return rowToMetadata(row);
  }

  private async readRemotePayload(response: Response): Promise<Record<string, unknown>> {
    const payload = objectValue(parseJsonText(await response.text()));
    return payload;
  }

  private async refresh(row: CredentialRow): Promise<CredentialRow> {
    let response: Response;
    try {
      response = await this.fetcher(`${row.issuer}/oauth2/token`, {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' },
        body: new URLSearchParams({
          grant_type: 'refresh_token',
          client_id: row.clientId,
          refresh_token: row.refreshToken,
        }).toString(),
      });
    } catch {
      throw new CorosBrokerError('COROS_OAUTH_UNAVAILABLE', 502);
    }
    const payload = await this.readRemotePayload(response);
    if (!response.ok) {
      if (payload.error === 'invalid_grant' || payload.error === 'invalid_request' && payload.error_description === 'invalid_grant') {
        this.markReauthRequired();
        throw new CorosBrokerError(COROS_REAUTH_REQUIRED, 503);
      }
      throw new CorosBrokerError('COROS_OAUTH_REFRESH_FAILED', 502);
    }
    const accessToken = payload.access_token;
    const refreshToken = payload.refresh_token;
    const expiresIn = payload.expires_in;
    if (typeof accessToken !== 'string' || !accessToken || typeof refreshToken !== 'string' || !refreshToken || typeof expiresIn !== 'number' || !Number.isFinite(expiresIn) || expiresIn <= 0) {
      throw new CorosBrokerError('COROS_OAUTH_INVALID_TOKEN_RESPONSE', 502);
    }
    const next: CredentialRow = {
      ...row,
      accessToken,
      refreshToken,
      expiresAt: this.now() + Math.floor(expiresIn),
      updatedAt: this.now(),
      credentialGeneration: row.credentialGeneration + 1,
      authState: 'READY',
      lastError: null,
    };
    await this.writeCredential(next);
    return next;
  }

  /** Internal-only token access. It is never exposed by the Worker routes. */
  public async getValidCredential(): Promise<{ accessToken: string; tokenType: string; scope: string; generation: number; accessExpiresAt: number }> {
    const current = await this.readCredential();
    if (!current || current.authState === COROS_REAUTH_REQUIRED) throw new CorosBrokerError(COROS_REAUTH_REQUIRED, 503);
    if (current.expiresAt - this.now() > this.accessExpirySkewSeconds) {
      return { accessToken: current.accessToken, tokenType: current.tokenType, scope: current.scope, generation: current.credentialGeneration, accessExpiresAt: current.expiresAt };
    }
    if (!this.refreshInFlight) {
      this.refreshInFlight = this.refresh(current).finally(() => {
        this.refreshInFlight = null;
      });
    }
    const refreshed = await this.refreshInFlight;
    return { accessToken: refreshed.accessToken, tokenType: refreshed.tokenType, scope: refreshed.scope, generation: refreshed.credentialGeneration, accessExpiresAt: refreshed.expiresAt };
  }

  private async mcpRequest(token: { accessToken: string; tokenType: string }, id: number, method: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
    let response: Response;
    try {
      response = await this.fetcher(this.mcpUrlForRequest, {
        method: 'POST',
        headers: {
          authorization: `${token.tokenType} ${token.accessToken}`,
          accept: 'application/json, text/event-stream',
          'content-type': 'application/json',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
      });
    } catch {
      throw new CorosBrokerError('COROS_MCP_UNAVAILABLE', 502);
    }
    const payload = objectValue(parseMcpBody(await response.text(), response.headers.get('content-type') ?? 'application/json'));
    if (!response.ok || payload.error) throw new CorosBrokerError('COROS_MCP_CALL_FAILED', 502);
    return payload;
  }

  private get mcpUrlForRequest(): string {
    const row = sqlRows(this.sql.exec('SELECT mcp_url FROM coros_credentials WHERE id = 1'))[0];
    if (!row || typeof row.mcp_url !== 'string') throw new CorosBrokerError(COROS_REAUTH_REQUIRED, 503);
    return row.mcp_url;
  }

  private async initialize(token: { accessToken: string; tokenType: string }): Promise<void> {
    await this.mcpRequest(token, 1, 'initialize', {
      protocolVersion: COROS_MCP_PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: COROS_CLIENT_NAME, version: COROS_CLIENT_VERSION },
    });
  }

  private async listTools(token: { accessToken: string; tokenType: string }): Promise<Array<Record<string, unknown>>> {
    const payload = await this.mcpRequest(token, 2, 'tools/list', {});
    const tools = objectValue(payload.result).tools;
    if (!Array.isArray(tools)) throw new CorosBrokerError('COROS_MCP_INVALID_TOOL_LIST', 502);
    return tools.filter((tool): tool is Record<string, unknown> => Boolean(tool && typeof tool === 'object' && !Array.isArray(tool)));
  }

  private async callTool(token: { accessToken: string; tokenType: string }, name: string, argumentsValue: Record<string, unknown>, id: number): Promise<Record<string, unknown>> {
    const payload = await this.mcpRequest(token, id, 'tools/call', { name, arguments: argumentsValue });
    const result = objectValue(payload.result);
    if (result.isError === true) throw new CorosBrokerError('COROS_MCP_TOOL_FAILED', 502);
    return result;
  }

  private dateForRun(runId: string): string {
    const numeric = Number(runId);
    if (!Number.isSafeInteger(numeric) || numeric <= 0) throw new CorosBrokerError('COROS_PROBE_INVALID', 400);
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date(numeric));
    const values = Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
    if (!values.year || !values.month || !values.day) throw new CorosBrokerError('COROS_PROBE_INVALID', 400);
    return `${values.year}${values.month}${values.day}`;
  }

  private textFromResult(value: unknown): string {
    const texts: string[] = [];
    const visit = (node: unknown): void => {
      if (typeof node === 'string') texts.push(node);
      else if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === 'object') Object.values(node).forEach(visit);
    };
    visit(value);
    return texts.join('\n');
  }

  private activityArguments(result: unknown, runId: string): { labelId: string; sportType: number } {
    const text = this.textFromResult(result);
    const runSeconds = String(Math.floor(Number(runId) / 1000));
    const startLines = text.split(/\r?\n/).filter((line) => /startTimestamp/i.test(line));
    const timestampMatches = text.includes(runId) || startLines.some((line) => line.includes(runSeconds));
    if (!timestampMatches) throw new CorosBrokerError('COROS_ACTIVITY_NOT_FOUND', 404);
    const labelMatch = /labelId\s*[=:]\s*["']?(\d+)/i.exec(text) ?? /["']labelId["']\s*:\s*["']?(\d+)/i.exec(text);
    if (!labelMatch) throw new CorosBrokerError('COROS_ACTIVITY_ID_MISSING', 502);
    const sportMatch = /sportType\s*[=:]\s*["']?(\d+)/i.exec(text) ?? /["']sportType["']\s*:\s*["']?(\d+)/i.exec(text);
    return { labelId: labelMatch[1], sportType: sportMatch ? Number(sportMatch[1]) : 100 };
  }

  private claimReplay(requestId: string): boolean {
    const now = this.now();
    this.sql.exec('DELETE FROM coros_replays WHERE expires_at < ?', now);
    if (sqlRows(this.sql.exec('SELECT request_id FROM coros_replays WHERE request_id = ? AND expires_at >= ?', requestId, now)).length) return false;
    this.sql.exec('INSERT INTO coros_replays (request_id, expires_at) VALUES (?, ?)', requestId, now + REPLAY_WINDOW_SECONDS);
    return true;
  }

  public async probe(runId: string, requestId: string): Promise<CorosProbeSummary> {
    if (!this.claimReplay(requestId)) throw new CorosBrokerError('COROS_REQUEST_REPLAYED', 409);
    const runDate = this.dateForRun(runId);
    const tomorrowDate = this.dateForRun(String(Number(runId) + 24 * 60 * 60 * 1000));
    const credential = await this.getValidCredential();
    const token = { accessToken: credential.accessToken, tokenType: credential.tokenType };
    await this.initialize(token);
    const tools = await this.listTools(token);
    const toolNames = new Set(tools.map((tool) => typeof tool.name === 'string' ? tool.name : ''));
    const required = ['querySportRecords', 'getActivityDetail', 'queryActivityLapData', 'queryTrainingLoadAssessment', 'queryRecoveryStatus', 'queryTrainingSchedule'];
    if (required.some((name) => !toolNames.has(name))) throw new CorosBrokerError('COROS_REQUIRED_TOOL_MISSING', 502);
    const records = await this.callTool(token, 'querySportRecords', {
      startDate: runDate,
      endDate: runDate,
      limit: 20,
      locationKeyword: '',
      minDistanceKm: 0,
      maxDistanceKm: 0,
      minDurationMinutes: 0,
      maxDurationMinutes: 0,
      maxAveragePace: '',
      sportTypeCodes: [65535],
    }, 3);
    const activity = this.activityArguments(records, runId);
    await this.callTool(token, 'getActivityDetail', activity, 4);
    await this.callTool(token, 'queryActivityLapData', activity, 5);
    await this.callTool(token, 'queryTrainingLoadAssessment', { days: 1 }, 6);
    await this.callTool(token, 'queryRecoveryStatus', {}, 7);
    await this.callTool(token, 'queryTrainingSchedule', { startDate: tomorrowDate, endDate: tomorrowDate }, 8);
    return {
      runDate,
      tomorrowDate,
      credentialGeneration: credential.generation,
      accessExpiresAt: credential.accessExpiresAt,
      toolCount: tools.length,
      categories: { activity: true, detail: true, laps: true, load: true, recovery: true, tomorrow: true, fitness: false },
    };
  }

  public async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    try {
      if (request.method === 'POST' && url.pathname === '/bootstrap') {
        const contentLength = Number(request.headers.get('content-length') ?? '0');
        if (contentLength > 64 * 1024) throw new CorosBrokerError('COROS_BOOTSTRAP_INVALID', 400);
        return Response.json(await this.bootstrap(parseJsonText(await request.text())));
      }
      if (request.method === 'GET' && url.pathname === '/metadata') {
        const metadata = await this.metadata();
        return Response.json(metadata ?? { authState: COROS_REAUTH_REQUIRED });
      }
      if (request.method === 'POST' && url.pathname === '/probe') {
        const body = objectValue(parseJsonText(await request.text()));
        const keys = Object.keys(body);
        if (keys.length !== 2 || !keys.includes('runId') || !keys.includes('requestId')) throw new CorosBrokerError('COROS_PROBE_INVALID', 400);
        const runId = requireString(body.runId, 'COROS_PROBE_INVALID', 32);
        const requestId = requireString(body.requestId, 'COROS_PROBE_INVALID', 128);
        if (!/^\d+$/.test(runId) || !/^[-A-Za-z0-9_.:]+$/.test(requestId)) throw new CorosBrokerError('COROS_PROBE_INVALID', 400);
        return Response.json(await this.probe(runId, requestId));
      }
      return Response.json({ error: 'Not found' }, { status: 404 });
    } catch (error) {
      if (error instanceof CorosBrokerError) return Response.json({ error: error.code }, { status: error.status, headers: { 'cache-control': 'no-store' } });
      return Response.json({ error: 'COROS_BROKER_FAILED' }, { status: 502, headers: { 'cache-control': 'no-store' } });
    }
  }
}
