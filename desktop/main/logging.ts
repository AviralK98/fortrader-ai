/**
 * Main-process logging with the same redaction guarantees as the backend.
 *
 * The embedded Fortrade session carries cookies and tokens. Anything we log
 * about it passes through here first.
 */

import {
  appendFileSync,
  existsSync,
  mkdirSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { join } from 'node:path';

import { app } from 'electron';

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

/** Beyond this the log is truncated; it is a diagnostic, not an archive. */
const MAX_LOG_BYTES = 2_000_000;

let logFile: string | null | undefined;

/**
 * Where main-process logs are written, beside the backend's own.
 *
 * Resolved lazily and cached, including the failure: `app` is only
 * available inside Electron, and this module is also loaded by tests.
 */
function resolveLogFile(): string | null {
  if (logFile !== undefined) return logFile;

  try {
    // Importing electron outside Electron is harmless; only calling
    // getPath is not, and that is what the catch is for. The tests load
    // this module in plain Node.
    const dir = join(app.getPath('userData'), 'data', 'logs');

    mkdirSync(dir, { recursive: true });

    logFile = join(dir, 'desktop.log');
  } catch {
    logFile = null;
  }

  return logFile;
}

function emit(level: Level, scope: string, message: string, context?: unknown): void {
  const payload = {
    ts: new Date().toISOString(),
    level: level.toUpperCase(),
    logger: scope,
    message: redactText(message),
    ...(context === undefined ? {} : { context: redact(context) }),
  };

  const line = `${JSON.stringify(payload)}\n`;

  // stderr keeps stdout free for structured child-process protocols.
  process.stderr.write(line);

  // A packaged Windows application has no console attached, so stderr
  // alone means every main-process diagnostic is discarded -- which is
  // exactly what made a failing update impossible to investigate. The
  // backend has kept a log file all along; this gives the shell one too.
  const target = resolveLogFile();

  if (target === null) return;

  try {
    if (existsSync(target) && statSync(target).size > MAX_LOG_BYTES) {
      writeFileSync(target, '');
    }

    appendFileSync(target, line);
  } catch {
    // Logging must never be the thing that breaks the application.
  }
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
