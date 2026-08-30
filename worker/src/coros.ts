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

export interface CorosScheduleStep {
  title: string | null;
  phase: string | null;
  durationSec: number | null;
  distanceKm: number | null;
  targetPaceSecPerKm: number | null;
  targetHeartRateBpm: number | null;
}

export interface CorosSchedule {
  title: string | null;
  sportType: string | null;
  estimatedDistanceKm: number | null;
  estimatedDurationSec: number | null;
  plannedLoad: number | null;
  steps: CorosScheduleStep[];
  sourceDisplayValue: string | null;
}

export interface CorosActivityFacts {
  sportType: number | null;
  title: string | null;
  distanceKm: number | null;
  durationSec: number | null;
  movingPaceSecPerKm: number | null;
  averagePaceSecPerKm: number | null;
  adjustedPaceSecPerKm: number | null;
  bestKmPaceSecPerKm: number | null;
  averageHeartRateBpm: number | null;
  maxHeartRateBpm: number | null;
  cadenceSpm: number | null;
  strideM: number | null;
  powerW: number | null;
  elevationM: number | null;
  caloriesKcal: number | null;
  trainingLoad: number | null;
  aerobicTrainingEffect: number | null;
  anaerobicTrainingEffect: number | null;
  trainingFocus: string | null;
  performance: string | null;
  perceivedEffort: string | null;
  sourceDisplayValues: Record<string, string>;
}

export interface CorosLapFacts {
  index: number;
  distanceKm: number | null;
  durationSec: number | null;
  paceSecPerKm: number | null;
  heartRateBpm: number | null;
  maxHeartRateBpm: number | null;
  powerW: number | null;
  cadenceSpm: number | null;
  strideM: number | null;
  groundContactMs: number | null;
  elevationM: number | null;
  adjustedPaceSecPerKm: number | null;
  sourceDisplayValue: string | null;
}

export interface CorosLoadFacts {
  reportDate: string;
  shortTermLoad: number | null;
  longTermLoad: number | null;
  ratio: number | null;
  status: string | null;
  sourceDisplayValue: string | null;
}

export interface CorosRecoveryFacts {
  observedAt: string;
  recoveryPercent: number | null;
  estimatedFullRecoveryAt: string | null;
  reportDateAligned: boolean;
}

export interface CorosSafeDiagnostic {
  objectKeys: string[];
  textPreview: string | null;
}

export interface CorosDailyBundle {
  schemaVersion: '1.0';
  runId: string;
  reportDate: string;
  retrievedAt: string;
  timezone: 'Asia/Shanghai';
  activity: CorosActivityFacts;
  laps: CorosLapFacts[];
  trainingContext: {
    todaySchedule: CorosSchedule | null;
    planAssociation: 'MATCHED' | 'UNMATCHED' | 'AMBIGUOUS';
    planAssociationEvidence: string[];
  };
  recentLoad: CorosLoadFacts | null;
  recovery: CorosRecoveryFacts | null;
  fitness: Record<string, unknown> | null;
  tomorrowSchedule: CorosSchedule | null;
  dataQuality: {
    activity: 'complete' | 'partial';
    laps: 'available' | 'unavailable' | 'automatic';
    todaySchedule: 'available' | 'unavailable' | 'ambiguous';
    tomorrowSchedule: 'available' | 'unavailable';
    load: 'date-matched' | 'unavailable' | 'out-of-range';
    recovery: 'report-date-aligned' | 'current-only-excluded' | 'unavailable';
    fitness: 'available' | 'unavailable';
  };
  provenance: {
    source: 'coros-mcp';
    tools: Record<string, string>;
  };
  diagnostics?: {
    activityDetail: CorosSafeDiagnostic;
    laps: CorosSafeDiagnostic;
    todaySchedule: CorosSafeDiagnostic | null;
    tomorrowSchedule: CorosSafeDiagnostic | null;
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

type JsonRecord = Record<string, unknown>;

const normalizedKey = (value: string): string => value.replace(/[^a-z0-9]/gi, '').toLowerCase();

const embeddedJson = (value: unknown): unknown => {
  if (typeof value !== 'string') return value;
  const trimmed = value.trim();
  if (!trimmed) return value;
  const candidates = [trimmed.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')];
  const objectStart = trimmed.indexOf('{');
  const objectEnd = trimmed.lastIndexOf('}');
  const arrayStart = trimmed.indexOf('[');
  const arrayEnd = trimmed.lastIndexOf(']');
  if (objectStart >= 0 && objectEnd > objectStart) candidates.push(trimmed.slice(objectStart, objectEnd + 1));
  if (arrayStart >= 0 && arrayEnd > arrayStart) candidates.push(trimmed.slice(arrayStart, arrayEnd + 1));
  for (const candidate of candidates) {
    if (!['{', '[', '"'].includes(candidate.trim()[0])) continue;
    try {
      return JSON.parse(candidate);
    } catch {
      // Try the next wrapper-free candidate.
    }
  }
  return value;
};

const collectObjects = (value: unknown, output: JsonRecord[] = [], seen = new Set<object>()): JsonRecord[] => {
  const parsed = embeddedJson(value);
  if (Array.isArray(parsed)) {
    for (const item of parsed) collectObjects(item, output, seen);
    return output;
  }
  if (!parsed || typeof parsed !== 'object') return output;
  if (seen.has(parsed)) return output;
  seen.add(parsed);
  const record = parsed as JsonRecord;
  output.push(record);
  for (const child of Object.values(record)) collectObjects(child, output, seen);
  return output;
};

const firstValue = (value: unknown, aliases: string[]): unknown => {
  const wanted = new Set(aliases.map(normalizedKey));
  for (const record of collectObjects(value)) {
    for (const [key, candidate] of Object.entries(record)) {
      if (wanted.has(normalizedKey(key))) return embeddedJson(candidate);
    }
  }
  return null;
};

const numberValue = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const match = value.replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
};

const timestampSeconds = (value: unknown): number | null => {
  const numeric = numberValue(value);
  if (numeric !== null) return numeric;
  if (value && typeof value === 'object') {
    const nested = firstValue(value, ['value', 'timestamp', 'seconds', 'milliseconds']);
    if (nested !== value) return timestampSeconds(nested);
  }
  if (typeof value === 'string') {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed / 1000;
  }
  return null;
};

const durationSeconds = (value: unknown, key = ''): number | null => {
  if (typeof value === 'string') {
    const match = value.trim().match(/^(\d+):([0-5]?\d)(?::([0-5]?\d)(?:\.\d+)?)?$/);
    if (match) {
      if (match[3] !== undefined) return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
      return Number(match[1]) * 60 + Number(match[2]);
    }
  }
  const numeric = numberValue(value);
  if (numeric === null || numeric < 0) return null;
  const normalized = normalizedKey(key);
  if (normalized.includes('millisecond') || normalized.endsWith('ms')) return numeric / 1000;
  if (normalized.includes('minute')) return numeric * 60;
  return numeric;
};

const distanceKm = (value: unknown, key = ''): number | null => {
  const numeric = numberValue(value);
  if (numeric === null || numeric < 0) return null;
  const normalized = normalizedKey(key);
  if (normalized.includes('meter') || normalized.endsWith('m')) return numeric / 1000;
  if (normalized.includes('kilometer') || normalized.endsWith('km')) return numeric;
  // COROS lap rows expose the unqualified distance field in centimetres;
  // summary/detail text carries an explicit `km` unit and is handled above.
  if (normalized === 'distance' && numeric >= 10000) return numeric / 100000;
  return numeric >= 1000 ? numeric / 1000 : numeric;
};

const paceSecondsPerKm = (value: unknown, key = ''): number | null => {
  if (typeof value === 'string') {
    const match = value.trim().match(/^(\d+):([0-5]?\d)(?:\.\d+)?/);
    if (match) return Number(match[1]) * 60 + Number(match[2]);
  }
  const numeric = numberValue(value);
  if (numeric === null || numeric <= 0) return null;
  const normalized = normalizedKey(key);
  if (normalized.includes('speed')) return 3600 / numeric;
  return numeric;
};

const stringValue = (value: unknown): string | null => {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
};

const textLineValue = (value: unknown, aliases: string[]): { value: string; label: string } | null => {
  const wanted = new Set(aliases.map(normalizedKey));
  const textParts: string[] = [];
  const visit = (node: unknown): void => {
    const parsed = embeddedJson(node);
    if (typeof parsed === 'string') textParts.push(parsed);
    else if (Array.isArray(parsed)) parsed.forEach(visit);
    else if (parsed && typeof parsed === 'object') Object.values(parsed).forEach(visit);
  };
  visit(value);
  const text = textParts.join('\n');
  for (const line of text.split(/\r?\n/)) {
    const match = /^\s*([^:：]+)\s*[:：]\s*(.*?)\s*$/.exec(line);
    if (!match || !wanted.has(normalizedKey(match[1]))) continue;
    return { value: match[2], label: match[1] };
  }
  return null;
};

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
      const parsed = embeddedJson(node);
      if (parsed !== node) visit(parsed);
      else if (typeof node === 'string') texts.push(node);
      else if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === 'object') Object.values(node).forEach(visit);
    };
    visit(value);
    return texts.join('\n');
  }

  private safeDiagnostic(value: unknown): CorosSafeDiagnostic {
    const forbidden = /(?:labelid|planid|idinplan|deviceid|activityid|fiturl|accesstoken|refreshtoken|coordinates?|polyline|route|mapurl|location)/i;
    const objectKeys = [...new Set(
      collectObjects(value)
        .flatMap((record) => Object.keys(record))
        .filter((key) => !forbidden.test(normalizedKey(key))),
    )].sort().slice(0, 120);
    const textPreview = this.textFromResult(value)
      .split(/\r?\n/)
      .filter((line) => !forbidden.test(normalizedKey(line.split(/[:：=]/, 1)[0] ?? '')))
      .map((line) => line
        .replace(/https?:\/\/\S+/gi, '[REDACTED_URL]')
        .replace(/\b[A-Za-z0-9_-]{32,}\b/g, '[REDACTED_TOKEN]'))
      .join('\n')
      .trim()
      .slice(0, 6000);
    return { objectKeys, textPreview: textPreview || null };
  }

  private activityArguments(result: unknown, runId: string): { labelId: string; sportType: number } {
    const runMilliseconds = Number(runId);
    const runSeconds = Math.floor(runMilliseconds / 1000);
    const candidates = collectObjects(result).filter((record) => {
      const timestamp = timestampSeconds(firstValue(record, ['startTimestamp', 'startTime', 'activityStartTimestamp']));
      const sportType = numberValue(firstValue(record, ['sportType', 'sportTypeCode', 'sport']));
      return timestamp !== null
        && (timestamp === runMilliseconds || timestamp === runSeconds)
        && (sportType === null || [100, 101, 102, 103].includes(sportType));
    });
    const unique = new Map<string, JsonRecord>();
    for (const candidate of candidates) {
      const label = stringValue(firstValue(candidate, ['labelId', 'activityLabelId']));
      if (label) unique.set(label, candidate);
    }
    if (!unique.size) {
      const text = this.textFromResult(result);
      const blocks = text.split(/\n(?=#\.\s)/).filter((block) => /startTimestamp\s*[=:]/i.test(block));
      for (const block of blocks) {
        const timestampMatch = /startTimestamp\s*[=:]\s*(\d+)/i.exec(block);
        const timestamp = timestampMatch ? Number(timestampMatch[1]) : null;
        if (timestamp !== runMilliseconds && timestamp !== runSeconds) continue;
        const sportMatch = /SportType\s*[=:]\s*(\d+)/i.exec(block);
        const sportType = sportMatch ? Number(sportMatch[1]) : 100;
        if (![100, 101, 102, 103].includes(sportType)) continue;
        const labelMatch = /LabelId\s*[=:]\s*([A-Za-z0-9_-]+)/i.exec(block);
        if (labelMatch) unique.set(labelMatch[1], { labelId: labelMatch[1], sportType });
      }
      if (!unique.size) throw new CorosBrokerError('COROS_ACTIVITY_NOT_FOUND', 404);
    }
    if (unique.size !== 1) throw new CorosBrokerError('COROS_ACTIVITY_AMBIGUOUS', 409);
    const candidate = [...unique.values()][0];
    const labelId = stringValue(firstValue(candidate, ['labelId', 'activityLabelId']));
    if (!labelId) throw new CorosBrokerError('COROS_ACTIVITY_ID_MISSING', 502);
    const sportType = numberValue(firstValue(candidate, ['sportType', 'sportTypeCode', 'sport'])) ?? 100;
    return { labelId, sportType };
  }

  private metric(value: unknown, aliases: string[], kind: 'distance' | 'duration' | 'pace' | 'number'): { value: number | null; display: string | null } {
    const wanted = new Set(aliases.map(normalizedKey));
    for (const record of collectObjects(value)) {
      for (const [key, candidate] of Object.entries(record)) {
        if (!wanted.has(normalizedKey(key))) continue;
        const parsed = kind === 'distance'
          ? distanceKm(candidate, key)
          : kind === 'duration'
            ? durationSeconds(candidate, key)
            : kind === 'pace'
              ? paceSecondsPerKm(candidate, key)
              : numberValue(candidate);
        if (parsed !== null && Number.isFinite(parsed)) return { value: parsed, display: stringValue(candidate) };
      }
    }
    const textMetricValue = textLineValue(embeddedJson(value), aliases);
    if (textMetricValue) {
      const parsed = kind === 'distance'
        ? distanceKm(textMetricValue.value, textMetricValue.label)
        : kind === 'duration'
          ? durationSeconds(textMetricValue.value, textMetricValue.label)
          : kind === 'pace'
            ? paceSecondsPerKm(textMetricValue.value, textMetricValue.label)
            : numberValue(textMetricValue.value);
      if (parsed !== null && Number.isFinite(parsed)) return { value: parsed, display: textMetricValue.value };
    }
    return { value: null, display: null };
  }

  private textMetric(value: unknown, aliases: string[]): string | null {
    const candidate = firstValue(value, aliases);
    return stringValue(candidate) ?? textLineValue(embeddedJson(value), aliases)?.value ?? null;
  }

  private activityFacts(detail: unknown, summary: unknown): CorosActivityFacts {
    const source = detail ?? summary;
    const distance = this.metric(source, ['distance', 'totalDistance', 'distanceKm', 'totalDistanceKm', 'distanceM', 'totalDistanceM'], 'distance');
    const duration = this.metric(source, ['duration', 'durationSec', 'totalTime', 'elapsedTime', 'movingTime'], 'duration');
    const movingPace = this.metric(source, ['movingPace', 'movingAveragePace', 'movingPaceSecPerKm'], 'pace');
    const averagePace = this.metric(source, ['averagePace', 'avgPace', 'averagePaceSecPerKm'], 'pace');
    const adjustedPace = this.metric(source, ['adjustedPace', 'adjustedPaceSecPerKm'], 'pace');
    const bestKm = this.metric(source, ['bestKm', 'bestKilometer', 'bestKmPace'], 'pace');
    const averageHr = this.metric(source, ['averageHeartRate', 'avgHeartRate', 'averageHr', 'avgHr'], 'number');
    const maxHr = this.metric(source, ['maxHeartRate', 'maximumHeartRate', 'maxHr', 'maximumHr', 'maxHeartRateBpm'], 'number');
    const cadence = this.metric(source, ['cadence', 'averageCadence', 'cadenceSpm'], 'number');
    const stride = this.metric(source, ['stride', 'strideLength', 'averageStride', 'averageStrideLength'], 'number');
    const power = this.metric(source, ['power', 'averagePower', 'powerW'], 'number');
    const elevation = this.metric(source, ['elevationGain', 'elevationGain / Loss', 'ascent', 'ascentM', 'elevation'], 'number');
    const calories = this.metric(source, ['calories', 'calorie', 'caloriesKcal'], 'number');
    const trainingLoad = this.metric(source, ['trainingLoad', 'activityTrainingLoad', 'load'], 'number');
    const aerobic = this.metric(source, ['aerobicTrainingEffect', 'aerobicEffect', 'aerobicTe'], 'number');
    const anaerobic = this.metric(source, ['anaerobicTrainingEffect', 'anaerobicEffect', 'anaerobicTe'], 'number');
    const sourceDisplayValues: Record<string, string> = {};
    for (const [name, metricValue] of Object.entries({ distanceKm: distance, durationSec: duration, movingPaceSecPerKm: movingPace, averagePaceSecPerKm: averagePace, adjustedPaceSecPerKm: adjustedPace, bestKmPaceSecPerKm: bestKm, averageHeartRateBpm: averageHr, maxHeartRateBpm: maxHr, cadenceSpm: cadence, strideM: stride, powerW: power, elevationM: elevation, caloriesKcal: calories, trainingLoad, aerobicTrainingEffect: aerobic, anaerobicTrainingEffect: anaerobic })) {
      if (metricValue.display !== null) sourceDisplayValues[name] = metricValue.display;
    }
    return {
      sportType: numberValue(firstValue(summary, ['sportType', 'sportTypeCode', 'sport'])) ?? numberValue(this.textMetric(summary, ['sportType', 'sportTypeCode', 'sport'])),
      title: this.textMetric(source, ['title', 'activityTitle', 'name', 'activityName']),
      distanceKm: distance.value,
      durationSec: duration.value,
      movingPaceSecPerKm: movingPace.value,
      averagePaceSecPerKm: averagePace.value,
      adjustedPaceSecPerKm: adjustedPace.value,
      bestKmPaceSecPerKm: bestKm.value,
      averageHeartRateBpm: averageHr.value,
      maxHeartRateBpm: maxHr.value,
      cadenceSpm: cadence.value,
      strideM: stride.value,
      powerW: power.value,
      elevationM: elevation.value,
      caloriesKcal: calories.value,
      trainingLoad: trainingLoad.value,
      aerobicTrainingEffect: aerobic.value,
      anaerobicTrainingEffect: anaerobic.value,
      trainingFocus: this.textMetric(source, ['trainingFocus', 'focus']),
      performance: this.textMetric(source, ['performance', 'performanceRating']),
      perceivedEffort: this.textMetric(source, ['perceivedEffort', 'effort', 'rpe']),
      sourceDisplayValues,
    };
  }

  private lapFacts(value: unknown): CorosLapFacts[] {
    const rows = collectObjects(value).filter((record) => {
      const keys = Object.keys(record).map(normalizedKey);
      const hasIndex = ['lapindex', 'splitindex', 'index'].some((key) => keys.includes(key));
      const hasMetric = ['distance', 'distancekm', 'distancem', 'pace', 'averagepace'].some((key) => keys.includes(key));
      return hasIndex && hasMetric;
    });
    const sequences: JsonRecord[][] = [];
    let sequence: JsonRecord[] = [];
    for (const row of rows) {
      const currentIndex = numberValue(firstValue(row, ['lapIndex', 'splitIndex', 'index']));
      const previous = sequence.at(-1);
      const previousIndex = previous ? numberValue(firstValue(previous, ['lapIndex', 'splitIndex', 'index'])) : null;
      const currentTotal = numberValue(firstValue(row, ['totalLength', 'cumulativeTime', 'cumulativeDuration']));
      const previousTotal = previous ? numberValue(firstValue(previous, ['totalLength', 'cumulativeTime', 'cumulativeDuration'])) : null;
      const continues = sequence.length > 0 && currentIndex !== null && previousIndex !== null && currentIndex === previousIndex + 1
        && (currentTotal === null || previousTotal === null || currentTotal > previousTotal);
      if (!continues && sequence.length > 0) sequences.push(sequence);
      sequence = continues ? [...sequence, row] : [row];
    }
    if (sequence.length > 0) sequences.push(sequence);
    const selectedRows = sequences.sort((left, right) => right.length - left.length)[0] ?? rows;
    const seen = new Set<string>();
    const result: CorosLapFacts[] = [];
    for (const record of selectedRows) {
      const distance = this.metric(record, ['distance', 'distanceKm', 'distanceM'], 'distance');
      const duration = this.metric(record, ['duration', 'durationSec', 'time'], 'duration');
      const pace = this.metric(record, ['pace', 'averagePace', 'avgPace', 'paceSecPerKm'], 'pace');
      const key = JSON.stringify([distance.value, duration.value, pace.value, firstValue(record, ['lapIndex', 'splitIndex', 'index'])]);
      if (seen.has(key)) continue;
      seen.add(key);
      const index = numberValue(firstValue(record, ['lapIndex', 'splitIndex', 'index'])) ?? result.length + 1;
      result.push({
        index: Math.max(1, Math.floor(index)),
        distanceKm: distance.value,
        durationSec: duration.value,
        paceSecPerKm: pace.value,
        heartRateBpm: this.metric(record, ['averageHeartRate', 'avgHeartRate', 'averageHr', 'avgHr', 'heartRate', 'heartRateBpm'], 'number').value,
        maxHeartRateBpm: this.metric(record, ['maxHeartRate', 'maxHr', 'maximumHr', 'maxHeartRateBpm'], 'number').value,
        powerW: this.metric(record, ['power', 'averagePower', 'powerW'], 'number').value,
        cadenceSpm: this.metric(record, ['cadence', 'averageCadence', 'cadenceSpm'], 'number').value,
        strideM: this.metric(record, ['stride', 'strideLength', 'averageStride', 'averageStrideLength'], 'number').value,
        groundContactMs: this.metric(record, ['groundContact', 'groundContactTime', 'groundTime', 'groundContactMs'], 'number').value,
        elevationM: this.metric(record, ['elevationGain', 'elevation', 'ascent', 'elevGain'], 'number').value,
        adjustedPaceSecPerKm: this.metric(record, ['adjustedPace', 'adjustedPaceSecPerKm'], 'pace').value,
        sourceDisplayValue: [distance.display, pace.display].filter((item): item is string => item !== null).join(' · ') || null,
      });
    }
    return result.sort((left, right) => left.index - right.index);
  }

  private compactDateToIso(value: string): string {
    if (!/^\d{8}$/.test(value)) throw new CorosBrokerError('COROS_DATE_INVALID', 400);
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }

  private dateValue(value: unknown): string | null {
    const candidate = stringValue(value);
    if (!candidate) return null;
    const match = candidate.match(/(\d{4})[-/]?(\d{2})[-/]?(\d{2})/);
    return match ? `${match[1]}${match[2]}${match[3]}` : null;
  }

  private textBlockForDate(value: unknown, compactDate: string): string | null {
    const text = this.textFromResult(value);
    const blocks = text.split(/(?=^\s*\d{4}[-/]?\d{2}[-/]?\d{2}\s*$)/m);
    return blocks.find((block) => this.dateValue(block.match(/^\s*(\d{4}[-/]?\d{2}[-/]?\d{2})\s*$/m)?.[1]) === compactDate) ?? null;
  }

  private scheduleSteps(value: unknown): CorosScheduleStep[] {
    const arrays: unknown[] = [];
    for (const record of collectObjects(value)) {
      for (const [key, candidate] of Object.entries(record)) {
        if (!/^(steps?|workoutsteps?|segments?)$/i.test(normalizedKey(key)) || !Array.isArray(candidate)) continue;
        arrays.push(...candidate);
      }
    }
    const steps: CorosScheduleStep[] = [];
    for (const item of arrays) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
      const title = this.textMetric(item, ['title', 'name', 'stepName', 'workoutStepName']);
      const phase = this.textMetric(item, ['phase', 'stepType', 'type', 'purpose']);
      const duration = this.metric(item, ['duration', 'durationSec', 'time'], 'duration').value;
      const distance = this.metric(item, ['distance', 'distanceKm', 'distanceM'], 'distance').value;
      const targetPace = this.metric(item, ['targetPace', 'targetPaceSecPerKm', 'pace'], 'pace').value;
      const targetHr = this.metric(item, ['targetHeartRate', 'targetHr', 'heartRate'], 'number').value;
      if (title === null && phase === null && duration === null && distance === null && targetPace === null && targetHr === null) continue;
      steps.push({ title, phase, durationSec: duration, distanceKm: distance, targetPaceSecPerKm: targetPace, targetHeartRateBpm: targetHr });
    }
    return steps;
  }

  private schedules(value: unknown, compactDate: string): CorosSchedule[] {
    const candidates = collectObjects(value).filter((record) => {
      const date = this.dateValue(firstValue(record, ['date', 'scheduleDate', 'workoutDate', 'plannedDate', 'startDate']));
      if (date !== null && date !== compactDate) return false;
      return firstValue(record, ['title', 'workoutTitle', 'workoutName', 'activityTitle', 'name']) !== null
        || firstValue(record, ['plannedDistance', 'estimatedDistance', 'plannedDuration', 'estimatedDuration', 'plannedLoad', 'trainingLoad']) !== null;
    });
    const result: CorosSchedule[] = [];
    const seen = new Set<string>();
    for (const record of candidates) {
      const title = this.textMetric(record, ['title', 'workoutTitle', 'workoutName', 'activityTitle', 'name']);
      const sportType = this.textMetric(record, ['sportType', 'sport', 'trainingType', 'workoutType']);
      const distance = this.metric(record, ['plannedDistance', 'estimatedDistance', 'distance', 'distanceKm', 'distanceM'], 'distance');
      const duration = this.metric(record, ['plannedDuration', 'estimatedDuration', 'duration', 'durationSec', 'time'], 'duration');
      const load = this.metric(record, ['plannedLoad', 'trainingLoad', 'load'], 'number');
      const steps = this.scheduleSteps(record);
      const dedupe = JSON.stringify([title, sportType, distance.value, duration.value, load.value, steps.length]);
      if (seen.has(dedupe)) continue;
      seen.add(dedupe);
      result.push({
        title,
        sportType,
        estimatedDistanceKm: distance.value,
        estimatedDurationSec: duration.value,
        plannedLoad: load.value,
        steps,
        sourceDisplayValue: [title, distance.display, duration.display].filter((item): item is string => item !== null).join(' · ') || null,
      });
    }
    return result;
  }

  private scheduleAssociation(activity: CorosActivityFacts, schedules: CorosSchedule[]): { status: CorosDailyBundle['trainingContext']['planAssociation']; evidence: string[]; selected: CorosSchedule | null } {
    if (!schedules.length) return { status: 'UNMATCHED', evidence: [], selected: null };
    const normalizedTitle = (value: string | null): string => value ? value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '') : '';
    const activityTitle = normalizedTitle(activity.title);
    const activitySport = activity.sportType;
    const candidates = schedules.map((schedule) => {
      const evidence: string[] = [];
      const scheduleTitle = normalizedTitle(schedule.title);
      const titleMatch = Boolean(activityTitle && scheduleTitle && activityTitle === scheduleTitle);
      if (titleMatch) evidence.push('title');
      const sportText = (schedule.sportType ?? '').toLowerCase();
      const sportMatch = !sportText || sportText.includes('run') || sportText.includes('跑') || (activitySport !== null && sportText.includes(String(activitySport)));
      if (sportMatch) evidence.push('sport');
      const distanceMatch = activity.distanceKm !== null && schedule.estimatedDistanceKm !== null
        && Math.abs(activity.distanceKm - schedule.estimatedDistanceKm) <= Math.max(0.25, schedule.estimatedDistanceKm * 0.1);
      if (distanceMatch) evidence.push('distance');
      const durationMatch = activity.durationSec !== null && schedule.estimatedDurationSec !== null
        && Math.abs(activity.durationSec - schedule.estimatedDurationSec) <= Math.max(180, schedule.estimatedDurationSec * 0.15);
      if (durationMatch) evidence.push('duration');
      const strong = titleMatch || (sportMatch && distanceMatch && durationMatch);
      return { schedule, evidence, strong };
    }).filter((candidate) => candidate.strong);
    if (candidates.length > 1) return { status: 'AMBIGUOUS', evidence: ['multiple strong schedule matches'], selected: null };
    if (!candidates.length) return { status: 'UNMATCHED', evidence: [], selected: null };
    return { status: 'MATCHED', evidence: candidates[0].evidence, selected: candidates[0].schedule };
  }

  private loadFacts(value: unknown, reportDate: string): CorosLoadFacts | null {
    const compact = reportDate.replace(/-/g, '');
    const candidates = collectObjects(value).filter((record) => this.dateValue(firstValue(record, ['date', 'recordDate', 'loadDate', 'day'])) === compact);
    const record = candidates.find((candidate) => firstValue(candidate, ['shortTermLoad', 'longTermLoad', 'acuteLoad', 'chronicLoad', 'loadRatio', 'ratio', 'loadStatus', 'status']) !== null);
    if (!record) {
      const block = this.textBlockForDate(value, compact);
      if (!block) return null;
      const shortTerm = this.metric(block, ['shortTermLoad', 'shortTermTrainingLoad', 'acuteLoad'], 'number');
      const longTerm = this.metric(block, ['longTermLoad', 'longTermTrainingLoad', 'chronicLoad'], 'number');
      const ratio = this.metric(block, ['loadRatio', 'ratio', 'acuteChronicRatio'], 'number');
      if (shortTerm.value === null && longTerm.value === null && ratio.value === null) return null;
      return {
        reportDate,
        shortTermLoad: shortTerm.value,
        longTermLoad: longTerm.value,
        ratio: ratio.value,
        status: this.textMetric(block, ['loadStatus', 'status', 'assessment', 'comment']),
        sourceDisplayValue: [shortTerm.display, longTerm.display, ratio.display].filter((item): item is string => item !== null).join(' · ') || null,
      };
    }
    const shortTerm = this.metric(record, ['shortTermLoad', 'shortTermTrainingLoad', 'acuteLoad'], 'number');
    const longTerm = this.metric(record, ['longTermLoad', 'longTermTrainingLoad', 'chronicLoad'], 'number');
    const ratio = this.metric(record, ['loadRatio', 'ratio', 'acuteChronicRatio'], 'number');
    return {
      reportDate,
      shortTermLoad: shortTerm.value,
      longTermLoad: longTerm.value,
      ratio: ratio.value,
      status: this.textMetric(record, ['loadStatus', 'status', 'assessment', 'comment']),
      sourceDisplayValue: [shortTerm.display, longTerm.display, ratio.display].filter((item): item is string => item !== null).join(' · ') || null,
    };
  }

  private recoveryFacts(value: unknown, reportDate: string): CorosRecoveryFacts | null {
    const observedAt = new Date(this.now() * 1000).toISOString();
    const percent = this.metric(value, ['recoveryPercent', 'recoveryPercentage', 'percent', 'score'], 'number').value;
    const estimated = firstValue(value, ['estimatedFullRecoveryAt', 'fullRecoveryTime', 'recoveryTime', 'estimatedRecoveryTime']);
    if (percent === null && estimated === null) {
      return { observedAt, recoveryPercent: null, estimatedFullRecoveryAt: null, reportDateAligned: false };
    }
    const currentDate = this.compactDateToIso(this.dateForRun(String(this.now() * 1000)));
    return {
      observedAt,
      recoveryPercent: reportDate === currentDate ? percent : null,
      estimatedFullRecoveryAt: reportDate === currentDate ? stringValue(estimated) : null,
      reportDateAligned: reportDate === currentDate,
    };
  }

  private fitnessFacts(value: unknown): Record<string, unknown> | null {
    if (!value) return null;
    const output: Record<string, unknown> = {};
    for (const [key, aliases] of Object.entries({ runningFitness: ['runningFitness', 'fitnessScore'], vo2max: ['vo2max', 'vo2Max'] })) {
      const numeric = this.metric(value, aliases, 'number').value;
      if (numeric !== null) output[key] = numeric;
    }
    const marathonPrediction = this.metric(value, ['marathonPrediction', 'marathonPredictionSec'], 'duration').value;
    if (marathonPrediction !== null) output.marathonPredictionSec = marathonPrediction;
    const label = this.textMetric(value, ['assessment', 'status', 'fitnessStatus']);
    if (label !== null) output.status = label;
    return Object.keys(output).length ? output : null;
  }

  private async optionalTool(token: { accessToken: string; tokenType: string }, name: string, argumentsValue: Record<string, unknown>, id: number): Promise<Record<string, unknown> | null> {
    try {
      return await this.callTool(token, name, argumentsValue, id);
    } catch {
      return null;
    }
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

  public async dailyBundle(runId: string, requestId: string): Promise<CorosDailyBundle> {
    if (!this.claimReplay(requestId)) throw new CorosBrokerError('COROS_REQUEST_REPLAYED', 409);
    const compactReportDate = this.dateForRun(runId);
    const compactTomorrowDate = this.dateForRun(String(Number(runId) + 24 * 60 * 60 * 1000));
    const reportDate = this.compactDateToIso(compactReportDate);
    const tomorrowDate = this.compactDateToIso(compactTomorrowDate);
    const credential = await this.getValidCredential();
    const token = { accessToken: credential.accessToken, tokenType: credential.tokenType };
    await this.initialize(token);
    const tools = await this.listTools(token);
    const toolNames = new Set(tools.map((tool) => typeof tool.name === 'string' ? tool.name : ''));
    const required = ['querySportRecords', 'getActivityDetail', 'queryActivityLapData', 'queryTrainingLoadAssessment', 'queryRecoveryStatus', 'queryTrainingSchedule'];
    if (required.some((name) => !toolNames.has(name))) throw new CorosBrokerError('COROS_REQUIRED_TOOL_MISSING', 502);

    const records = await this.callTool(token, 'querySportRecords', {
      startDate: compactReportDate,
      endDate: compactReportDate,
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
    const detail = await this.callTool(token, 'getActivityDetail', activity, 4);
    const lapsResult = await this.callTool(token, 'queryActivityLapData', activity, 5);
    const activityFacts = { ...this.activityFacts({ detail, summary: records }, records), sportType: activity.sportType };
    const laps = this.lapFacts(lapsResult);

    let loadResult = await this.optionalTool(token, 'queryTrainingLoadAssessment', { startDate: compactReportDate, endDate: compactReportDate }, 6);
    if (!loadResult) loadResult = await this.optionalTool(token, 'queryTrainingLoadAssessment', { days: 30 }, 16);
    const recentLoad = loadResult ? this.loadFacts(loadResult, reportDate) : null;

    const recoveryResult = await this.optionalTool(token, 'queryRecoveryStatus', {}, 7);
    const recovery = recoveryResult ? this.recoveryFacts(recoveryResult, reportDate) : null;

    const todayResult = await this.optionalTool(token, 'queryTrainingSchedule', { startDate: compactReportDate, endDate: compactReportDate }, 8);
    const tomorrowResult = await this.optionalTool(token, 'queryTrainingSchedule', { startDate: compactTomorrowDate, endDate: compactTomorrowDate }, 9);
    const todayCandidates = todayResult ? this.schedules(todayResult, compactReportDate) : [];
    const tomorrowCandidates = tomorrowResult ? this.schedules(tomorrowResult, compactTomorrowDate) : [];
    const association = this.scheduleAssociation(activityFacts, todayCandidates);
    let todaySchedule = association.selected ?? (todayCandidates.length === 1 ? todayCandidates[0] : null);
    let tomorrowSchedule = tomorrowCandidates.length === 1 ? tomorrowCandidates[0] : null;

    if (toolNames.has('queryTrainingPlanDetail')) {
      if (association.selected) {
        const todayDetail = await this.optionalTool(token, 'queryTrainingPlanDetail', { date: compactReportDate }, 10);
        if (todayDetail && todaySchedule && !todaySchedule.steps.length) todaySchedule = { ...todaySchedule, steps: this.scheduleSteps(todayDetail) };
      }
      if (tomorrowSchedule) {
        const tomorrowDetail = await this.optionalTool(token, 'queryTrainingPlanDetail', { date: compactTomorrowDate }, 11);
        if (tomorrowDetail && !tomorrowSchedule.steps.length) tomorrowSchedule = { ...tomorrowSchedule, steps: this.scheduleSteps(tomorrowDetail) };
      }
    }

    let fitness: Record<string, unknown> | null = null;
    if (toolNames.has('queryFitnessAssessmentOverview')) {
      const fitnessResult = await this.optionalTool(token, 'queryFitnessAssessmentOverview', {}, 12);
      fitness = this.fitnessFacts(fitnessResult);
    }

    const recoveryQuality: CorosDailyBundle['dataQuality']['recovery'] = recovery
      ? recovery.reportDateAligned ? 'report-date-aligned' : 'current-only-excluded'
      : 'unavailable';
    return {
      schemaVersion: '1.0',
      runId,
      reportDate,
      retrievedAt: new Date(this.now() * 1000).toISOString(),
      timezone: 'Asia/Shanghai',
      activity: activityFacts,
      laps,
      trainingContext: {
        todaySchedule,
        planAssociation: association.status,
        planAssociationEvidence: association.evidence,
      },
      recentLoad,
      recovery,
      fitness,
      tomorrowSchedule,
      dataQuality: {
        activity: Object.values(activityFacts).some((value) => value !== null && !(typeof value === 'object' && Object.keys(value as object).length === 0)) ? 'complete' : 'partial',
        laps: laps.length ? 'available' : 'unavailable',
        todaySchedule: todayCandidates.length > 1 ? 'ambiguous' : todaySchedule ? 'available' : 'unavailable',
        tomorrowSchedule: tomorrowSchedule ? 'available' : 'unavailable',
        load: recentLoad ? 'date-matched' : loadResult ? 'out-of-range' : 'unavailable',
        recovery: recoveryQuality,
        fitness: fitness ? 'available' : 'unavailable',
      },
      provenance: {
        source: 'coros-mcp',
        tools: {
          activity: 'querySportRecords',
          detail: 'getActivityDetail',
          laps: 'queryActivityLapData',
          recentLoad: 'queryTrainingLoadAssessment',
          recovery: 'queryRecoveryStatus',
          todaySchedule: 'queryTrainingSchedule',
          tomorrowSchedule: 'queryTrainingSchedule',
          ...(toolNames.has('queryFitnessAssessmentOverview') ? { fitness: 'queryFitnessAssessmentOverview' } : {}),
        },
      },
      diagnostics: {
        activityDetail: this.safeDiagnostic(detail),
        laps: this.safeDiagnostic(lapsResult),
        todaySchedule: todayResult ? this.safeDiagnostic(todayResult) : null,
        tomorrowSchedule: tomorrowResult ? this.safeDiagnostic(tomorrowResult) : null,
      },
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
      if (request.method === 'POST' && url.pathname === '/daily-bundle') {
        const body = objectValue(parseJsonText(await request.text()));
        const keys = Object.keys(body);
        if (keys.length !== 2 || !keys.includes('runId') || !keys.includes('requestId')) throw new CorosBrokerError('COROS_BUNDLE_INVALID', 400);
        const runId = requireString(body.runId, 'COROS_BUNDLE_INVALID', 32);
        const requestId = requireString(body.requestId, 'COROS_BUNDLE_INVALID', 128);
        if (!/^\d+$/.test(runId) || !/^[-A-Za-z0-9_.:]+$/.test(requestId)) throw new CorosBrokerError('COROS_BUNDLE_INVALID', 400);
        return Response.json(await this.dailyBundle(runId, requestId));
      }
      return Response.json({ error: 'Not found' }, { status: 404 });
    } catch (error) {
      if (error instanceof CorosBrokerError) return Response.json({ error: error.code }, { status: error.status, headers: { 'cache-control': 'no-store' } });
      return Response.json({ error: 'COROS_BROKER_FAILED' }, { status: 502, headers: { 'cache-control': 'no-store' } });
    }
  }
}
