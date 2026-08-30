export interface BasicAuthConfig {
  username: string;
  password: string;
}

export interface BasicCredentials {
  username: string;
  password: string;
}

const BASIC_CHALLENGE = 'Basic realm="Ayu Running"';
const BASE64 = /^[A-Za-z0-9+/]*={0,2}$/;

export const unauthorizedResponse = (): Response =>
  new Response(JSON.stringify({ error: 'Unauthorized' }), {
    status: 401,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'www-authenticate': BASIC_CHALLENGE,
    },
  });

const decodeBasic = (encoded: string): BasicCredentials | null => {
  if (!encoded || encoded.length % 4 === 1 || !BASE64.test(encoded)) return null;
  try {
    const binary = atob(encoded);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const decoded = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    const separator = decoded.indexOf(':');
    if (separator <= 0) return null;
    return {
      username: decoded.slice(0, separator),
      password: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
};

export const parseBasicCredentials = (header: string | null): BasicCredentials | null => {
  if (!header) return null;
  const match = /^Basic\s+([^\s]+)$/i.exec(header.trim());
  return match ? decodeBasic(match[1]) : null;
};

const digest = async (value: string): Promise<Uint8Array> =>
  new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));

/** Compare fixed-length digests so credentials are not compared by early exit. */
export const timingSafeEqual = async (left: string, right: string): Promise<boolean> => {
  const [leftDigest, rightDigest] = await Promise.all([digest(left), digest(right)]);
  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest[index] ^ rightDigest[index];
  }
  return difference === 0;
};

export const verifyBasicCredentials = async (
  header: string | null,
  config: BasicAuthConfig
): Promise<boolean> => {
  const credentials = parseBasicCredentials(header);
  if (!credentials || !config.username || !config.password) return false;
  const [usernameMatches, passwordMatches] = await Promise.all([
    timingSafeEqual(credentials.username, config.username),
    timingSafeEqual(credentials.password, config.password),
  ]);
  return usernameMatches && passwordMatches;
};

export interface CollectorAuthResult {
  body: string;
  timestamp: number;
  requestId: string;
  runId: string;
}

const bytesToHex = (bytes: Uint8Array): string =>
  Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');

const hexToBytes = (value: string): Uint8Array | null => {
  if (!/^[0-9a-f]{64}$/i.test(value)) return null;
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(value.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
};

export const sha256Hex = async (value: string): Promise<string> =>
  bytesToHex(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))));

export const collectorSigningPayload = async (
  timestamp: number,
  requestId: string,
  runId: string,
  method: string,
  path: string,
  body: string,
): Promise<string> =>
  [String(timestamp), requestId, runId, method.toUpperCase(), path, await sha256Hex(body)].join('\n');

export const signCollectorPayload = async (secret: string, payload: string): Promise<string> => {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  return bytesToHex(new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload))));
};

export const verifyCollectorRequest = async (
  request: Request,
  secret: string,
  nowSeconds = Math.floor(Date.now() / 1000),
  freshnessSeconds = 300,
): Promise<CollectorAuthResult | null> => {
  if (!secret) return null;
  const timestampValue = request.headers.get('x-ayu-timestamp');
  const requestId = request.headers.get('x-ayu-request-id') ?? '';
  const runId = request.headers.get('x-ayu-run-id') ?? '';
  const signature = request.headers.get('x-ayu-signature') ?? '';
  if (!timestampValue || !/^\d{1,12}$/.test(timestampValue) || !requestId || requestId.length > 128 || !runId || runId.length > 32 || !/^\d+$/.test(runId)) return null;
  const timestamp = Number(timestampValue);
  if (!Number.isSafeInteger(timestamp) || Math.abs(nowSeconds - timestamp) > freshnessSeconds) return null;
  const body = await request.clone().text();
  const payload = await collectorSigningPayload(timestamp, requestId, runId, request.method, new URL(request.url).pathname, body);
  const expected = hexToBytes(await signCollectorPayload(secret, payload));
  const actual = hexToBytes(signature);
  if (!expected || !actual || expected.length !== actual.length) return null;
  let difference = 0;
  for (let index = 0; index < expected.length; index += 1) difference |= expected[index] ^ actual[index];
  return difference === 0 ? { body, timestamp, requestId, runId } : null;
};
