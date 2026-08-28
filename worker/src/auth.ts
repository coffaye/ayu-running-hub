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
