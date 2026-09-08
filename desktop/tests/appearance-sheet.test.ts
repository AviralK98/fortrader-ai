import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const source = readFileSync(
  join(__dirname, '..', 'renderer', 'src', 'components', 'AppearancePanel.tsx'),
  'utf-8',
);

describe('appearance sheet', () => {
  it('is portalled out of the status strip', () => {
    // .status-strip carries a backdrop-filter, which makes it a
    // containing block for position:fixed descendants -- the same rule
    // that applies to transform and filter. A sheet rendered inside it
    // is trapped in that stacking context and paints *behind* the panel
    // beside it, whatever z-index it is given. It looked like a z-index
    // bug and no amount of z-index fixed it.
    expect(source).toContain('createPortal');
    expect(source).toContain('document.body');
  });

  it('hides the native Fortrade view while it is open', () => {
    // Fortrade's chart is a WebContentsView composited above the page.
    // No CSS can put HTML in front of it, so the sheet would be clipped
    // by it and the scrim would dim only half the window.
    expect(source).toContain('setFortradeVisible(false)');
    expect(source).toContain('setFortradeVisible(true)');
  });
});
