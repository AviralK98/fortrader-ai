/**
 * Main-process logging with the same redaction guarantees as the backend.
 *
 * The embedded Fortrade session carries cookies and tokens. Anything we log
 * about it passes through here first.
 */

const REDACTED = '[REDACTED]';

const JWT = /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}/g;
const BEARER = /\bbearer\s+[A-Za-z0-9\-._~+/]+=*/gi;
const KEY_VALUE =
  /\b(authorization|set-cookie|cookie|password|passwd|secret|token|api[_-]?key|apikey|session[_-]?id|jwt|signature)\s*[:=]\s*[^\s;,&]+/gi;

const SENSITIVE_KEY =
  /(cookie|authorization|auth|token|password|secret|session|credential|api_?key|bearer|jwt|signature)/i;

export function redactText(text: string): string {
  return text
    .replace(JWT, REDACTED)
    .replace(BEARER, `Bearer ${REDACTED}`)
    .replace(KEY_VALUE, (_m, key: string) => `${key}=${REDACTED}`);
}

export function redact(value: unknown): unknown {
  if (typeof value === 'string') return redactText(value);

  if (Array.isArray(value)) return value.map(redact);

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k,
        SENSITIVE_KEY.test(k) ? REDACTED : redact(v),
      ]),
    );
  }

  return value;
}

type Level = 'debug' | 'info' | 'warn' | 'error';

function emit(level: Level, scope: string, message: string, context?: unknown): void {
  const payload = {
    ts: new Date().toISOString(),
    level: level.toUpperCase(),
    logger: scope,
    message: redactText(message),
    ...(context === undefined ? {} : { context: redact(context) }),
  };

  // stderr keeps stdout free for structured child-process protocols.
  process.stderr.write(`${JSON.stringify(payload)}\n`);
}

export function createLogger(scope: string) {
  return {
    debug: (m: string, c?: unknown) => emit('debug', scope, m, c),
    info: (m: string, c?: unknown) => emit('info', scope, m, c),
    warn: (m: string, c?: unknown) => emit('warn', scope, m, c),
    error: (m: string, c?: unknown) => emit('error', scope, m, c),
  };
}

export type Logger = ReturnType<typeof createLogger>;
