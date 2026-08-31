import { describe, expect, it } from 'vitest';

import { redact, redactText } from '../main/logging';

describe('redactText', () => {
  it.each([
    ['Cookie: session=abc123secret', 'abc123secret'],
    ['authorization: Bearer eyJhbGciOi.JzdWIiOiIx.SflKxwRJSM', 'SflKxwRJSM'],
    ['Set-Cookie: FTSESSION=deadbeefcafe; Path=/', 'deadbeefcafe'],
    ['password=hunter2', 'hunter2'],
    ['api_key: sk-live-0123456789', 'sk-live-0123456789'],
  ])('removes the secret from %j', (input, secret) => {
    const result = redactText(input);

    expect(result).not.toContain(secret);
    expect(result).toContain('[REDACTED]');
  });

  it('removes a bare JWT', () => {
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.dBjftJeZ4CVPmB92K';

    expect(redactText(`frame ${jwt} seen`)).not.toContain(jwt);
  });

  it('leaves ordinary market text alone', () => {
    const text = 'GBP/USD 1.35284/1.35408 spread 124';

    expect(redactText(text)).toBe(text);
  });

  it('keeps the cookie path suffix readable', () => {
    // Trailing context after the separator survives, so logs stay useful.
    expect(redactText('Set-Cookie: a=b; Path=/')).toContain('Path=/');
  });
});

describe('redact', () => {
  it('redacts sensitive keys but keeps market data', () => {
    const result = redact({
      symbol: 'GBP/USD',
      balance: 10000,
      cookie: 'FTSESSION=abc',
      Authorization: 'Bearer xyz',
      sessionToken: 'tok_1',
    }) as Record<string, unknown>;

    expect(result.symbol).toBe('GBP/USD');
    expect(result.balance).toBe(10000);
    expect(result.cookie).toBe('[REDACTED]');
    expect(result.Authorization).toBe('[REDACTED]');
    expect(result.sessionToken).toBe('[REDACTED]');
  });

  it('recurses through nested structures', () => {
    const result = redact({
      request: { headers: [{ cookie: 'a=b' }, { accept: 'json' }] },
    }) as { request: { headers: Array<Record<string, unknown>> } };

    expect(result.request.headers[0]?.cookie).toBe('[REDACTED]');
    expect(result.request.headers[1]?.accept).toBe('json');
  });

  it('passes non-string scalars through', () => {
    expect(redact({ n: 5, ok: true })).toEqual({ n: 5, ok: true });
  });
});
