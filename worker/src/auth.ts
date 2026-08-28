export interface AccessConfig {
  issuer: string;
  audience: string;
  jwksUrl: string;
}

export interface AccessClaims {
  iss: string;
  aud: string | string[];
  exp: number;
  [key: string]: unknown;
}

const decodeBase64Url = (input: string): Uint8Array => {
  const normalized = input.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (input.length % 4)) % 4);
  const binary = atob(normalized);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
};

const decodeJson = (input: string): Record<string, unknown> => {
  const text = new TextDecoder().decode(decodeBase64Url(input));
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('JWT object expected');
  return value as Record<string, unknown>;
};

export const validateAccessClaims = (
  claims: Record<string, unknown>,
  config: AccessConfig,
  nowSeconds = Math.floor(Date.now() / 1000)
): AccessClaims => {
  if (!config.issuer || !config.audience || !config.jwksUrl) throw new Error('Access configuration required');
  if (claims.iss !== config.issuer) throw new Error('Access issuer mismatch');
  const aud = claims.aud;
  const audiences = typeof aud === 'string' ? [aud] : Array.isArray(aud) ? aud : [];
  if (!audiences.includes(config.audience)) throw new Error('Access audience mismatch');
  if (typeof claims.exp !== 'number' || claims.exp <= nowSeconds) throw new Error('Access assertion expired');
  if (typeof claims.nbf === 'number' && claims.nbf > nowSeconds) throw new Error('Access assertion not active');
  return claims as AccessClaims;
};

export const verifyAccessJwt = async (
  request: Request,
  config: AccessConfig,
  fetcher: typeof fetch = fetch
): Promise<AccessClaims> => {
  const assertion = request.headers.get('Cf-Access-Jwt-Assertion');
  if (!assertion) throw new Error('Access assertion missing');
  const parts = assertion.split('.');
  if (parts.length !== 3) throw new Error('Access assertion malformed');
  const header = decodeJson(parts[0]);
  const claims = decodeJson(parts[1]);
  if (header.alg !== 'RS256' || typeof header.kid !== 'string') throw new Error('Access signing algorithm unsupported');
  const jwksResponse = await fetcher(config.jwksUrl, { headers: { accept: 'application/json' } });
  if (!jwksResponse.ok) throw new Error('Access JWKS unavailable');
  const jwks = (await jwksResponse.json()) as { keys?: JsonWebKey[] };
  const key = jwks.keys?.find((candidate) => (candidate as JsonWebKey & { kid?: string }).kid === header.kid);
  if (!key) throw new Error('Access signing key unavailable');
  const cryptoKey = await crypto.subtle.importKey(
    'jwk',
    key,
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['verify']
  );
  const valid = await crypto.subtle.verify(
    { name: 'RSASSA-PKCS1-v1_5' },
    cryptoKey,
    decodeBase64Url(parts[2]) as unknown as BufferSource,
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`)
  );
  if (!valid) throw new Error('Access signature invalid');
  return validateAccessClaims(claims, config);
};
