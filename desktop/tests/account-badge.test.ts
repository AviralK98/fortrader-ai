import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const bar = readFileSync(
  join(__dirname, '..', 'renderer', 'src', 'components', 'AccountBar.tsx'),
  'utf-8',
);

describe('the account badge', () => {
  it('calls a live account REAL, as Fortrade does', () => {
    expect(bar).toMatch(/LIVE:\s*\{[^}]*label:\s*'REAL'/);
  });

  it('does not dress UNKNOWN as a live account', () => {
    // It used to share the red live style, which read as a warning about
    // real money when the app simply had not seen the account type yet.
    expect(bar).toMatch(/UNKNOWN:\s*\{[^}]*tone:\s*'unknown'/);
  });
});
