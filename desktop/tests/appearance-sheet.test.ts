import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const components = join(__dirname, '..', 'renderer', 'src', 'components');

const sheet = readFileSync(join(components, 'AppearancePanel.tsx'), 'utf-8');
const palette = readFileSync(join(components, 'CommandPalette.tsx'), 'utf-8');

describe('overlays', () => {
  it('are portalled out of the status strip', () => {
    // .status-strip carries a backdrop-filter, which makes it a
    // containing block for position:fixed descendants -- the same rule
    // that applies to transform and filter. An overlay rendered inside
    // it is trapped in that stacking context and paints *behind* the
    // panel beside it, whatever z-index it is given. It looked like a
    // z-index bug and no amount of z-index fixed it.
    for (const source of [sheet, palette]) {
      expect(source).toContain('createPortal');
      expect(source).toContain('document.body');
    }
  });
});

describe('the appearance sheet', () => {
  it('leaves the chart alone', () => {
    // It sits inside the analysis panel's own column and never covers
    // the chart, so there is nothing to hide. It used to hide it anyway,
    // which blanked the entire application to show a 340px panel.
    expect(sheet).not.toContain('setFortradeVisible');
  });

  it('closes on an outside click rather than behind a scrim', () => {
    // A full-screen scrim would dim the page and leave the chart at full
    // brightness beside it, because a native view cannot be covered by
    // anything this page draws.
    expect(sheet).not.toContain('sheet__scrim');
    expect(sheet).toContain('mousedown');
  });
});

describe('the command palette', () => {
  it('hides the native chart while it is open', () => {
    // Unlike the sheet, the palette is centred, so it does overlap the
    // chart -- and Fortrade's view is composited above the page, where
    // no z-index can reach it. Hiding it is the only way the palette is
    // fully visible.
    expect(palette).toContain('setFortradeVisible(false)');
    expect(palette).toContain('setFortradeVisible(true)');
  });

  it('opens on a keyboard shortcut, not only the button', () => {
    expect(palette).toContain("event.key.toLowerCase() === 'k'");
    expect(palette).toMatch(/ctrlKey \|\| event\.metaKey/);
  });
});
