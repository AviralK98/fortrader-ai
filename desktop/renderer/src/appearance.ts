/**
 * Appearance: what the interface looks like, and how much it moves.
 *
 * Four independent choices rather than one theme list. A preset sets the
 * surfaces, an accent sets the highlight, and the surface controls decide
 * how much glass, curvature and motion there is. Someone who wants the
 * Fortrade palette with a green accent and no animation should not have
 * to find a preset that happens to be all three.
 *
 * Everything resolves to CSS custom properties on the root element, so
 * changing any of it is an attribute write rather than a re-render.
 *
 * One thing worth knowing: only this panel is styled. Fortrade's terminal
 * fills the rest of the window as a native view painted over the page and
 * keeps its own dark look regardless, which is why the light presets say
 * so before you pick one.
 */

export interface Preset {
  id: string;
  name: string;
  /** Two stops describing the preset, drawn as its swatch. */
  swatch: [string, string];
  light: boolean;
  /**
   * The accent this preset is designed around. Applied when the preset
   * is chosen; the accent row still overrides it afterwards, so the
   * default is a starting point rather than a lock.
   */
  accent: string;
  hint?: string;
}

const FORTRADE_PRESET: Preset = {
  id: 'fortrade',
  name: 'Fortrade',
  swatch: ['#4c9aff', '#071322'],
  light: false,
  accent: 'blue',
  hint: "The platform's own navy.",
};

const TEAL_ACCENT: Accent = {
  id: 'teal',
  name: 'Teal',
  colours: ['#2ee6c5', '#14b8a6'],
};

const SOFT_RADIUS = { id: 'soft', name: 'Soft', value: '10px' } as const;

/** Guaranteed lookups: a stored id that no longer exists falls back. */
export function presetFor(id: string): Preset {
  return PRESETS.find((p) => p.id === id) ?? FORTRADE_PRESET;
}

export function accentFor(id: string): Accent {
  return ACCENTS.find((a) => a.id === id) ?? TEAL_ACCENT;
}

export function radiusFor(id: string): { value: string } {
  return RADII.find((r) => r.id === id) ?? SOFT_RADIUS;
}

export const PRESETS: Preset[] = [
  {
    id: 'fortrade',
    name: 'Fortrade',
    swatch: ['#4c9aff', '#071322'],
    accent: 'blue',
    light: false,
    hint: "The platform's own navy.",
  },
  {
    id: 'aurora',
    name: 'Aurora',
    swatch: ['#2ee6c5', '#0d1b2a'],
    accent: 'teal',
    light: false,
    hint: 'Teal over deep blue.',
  },
  {
    id: 'graphite',
    name: 'Graphite',
    swatch: ['#818cf8', '#12161c'],
    accent: 'indigo',
    light: false,
    hint: 'Neutral and quiet.',
  },
  {
    id: 'oled',
    name: 'OLED',
    swatch: ['#a78bfa', '#000000'],
    accent: 'violet',
    light: false,
    hint: 'True black, for dark rooms.',
  },
  {
    id: 'frost',
    name: 'Frost',
    swatch: ['#1668d8', '#eef2f8'],
    accent: 'blue',
    light: true,
    hint: 'Bright. Sits beside a dark chart.',
  },
  {
    id: 'paper',
    name: 'Paper',
    swatch: ['#35c98b', '#f6f4ef'],
    accent: 'green',
    light: true,
    hint: 'Warm and low glare.',
  },
];

export interface Accent {
  id: string;
  name: string;
  /** [base, strong] — strong is used for pressed and gradient ends. */
  colours: [string, string];
}

export const ACCENTS: Accent[] = [
  { id: 'teal', name: 'Teal', colours: ['#2ee6c5', '#14b8a6'] },
  { id: 'blue', name: 'Blue', colours: ['#4c9aff', '#2f6fd0'] },
  { id: 'violet', name: 'Violet', colours: ['#a78bfa', '#7c5cf0'] },
  { id: 'green', name: 'Green', colours: ['#35c98b', '#16a06a'] },
  { id: 'amber', name: 'Amber', colours: ['#f0b429', '#d18f06'] },
  { id: 'rose', name: 'Rose', colours: ['#fb7185', '#e11d48'] },
  { id: 'indigo', name: 'Indigo', colours: ['#818cf8', '#4f46e5'] },
];

export const RADII = [
  { id: 'sharp', name: 'Sharp', value: '4px' },
  { id: 'soft', name: 'Soft', value: '10px' },
  { id: 'round', name: 'Round', value: '18px' },
] as const;

export const MOTIONS = [
  { id: 'off', name: 'Off' },
  { id: 'subtle', name: 'Subtle' },
  { id: 'lively', name: 'Lively' },
] as const;

export interface Appearance {
  preset: string;
  accent: string;
  /** 0-100. Drives blur radius and surface translucency together. */
  glass: number;
  radius: (typeof RADII)[number]['id'];
  motion: (typeof MOTIONS)[number]['id'];
  /** The surfaces catch a faint highlight near the cursor. */
  pointerLight: boolean;
}

export const DEFAULT_APPEARANCE: Appearance = {
  preset: 'fortrade',
  accent: FORTRADE_PRESET.accent,
  glass: 55,
  radius: 'soft',
  motion: 'subtle',
  pointerLight: true,
};

const STORAGE_KEY = 'fortrader.appearance';

export function storedAppearance(): Appearance {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);

    if (!raw) return DEFAULT_APPEARANCE;

    const saved = JSON.parse(raw) as Partial<Appearance>;

    // Merged rather than trusted: a value written by an older version, or
    // edited by hand, must not leave the interface unusable.
    return {
      preset: PRESETS.some((p) => p.id === saved.preset)
        ? (saved.preset as string)
        : DEFAULT_APPEARANCE.preset,
      accent: ACCENTS.some((a) => a.id === saved.accent)
        ? (saved.accent as string)
        : DEFAULT_APPEARANCE.accent,
      glass:
        typeof saved.glass === 'number' && saved.glass >= 0 && saved.glass <= 100
          ? saved.glass
          : DEFAULT_APPEARANCE.glass,
      radius: RADII.some((r) => r.id === saved.radius)
        ? (saved.radius as Appearance['radius'])
        : DEFAULT_APPEARANCE.radius,
      motion: MOTIONS.some((m) => m.id === saved.motion)
        ? (saved.motion as Appearance['motion'])
        : DEFAULT_APPEARANCE.motion,
      pointerLight:
        typeof saved.pointerLight === 'boolean'
          ? saved.pointerLight
          : DEFAULT_APPEARANCE.pointerLight,
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function applyAppearance(appearance: Appearance): void {
  const root = document.documentElement;
  const accent = accentFor(appearance.accent);
  const radius = radiusFor(appearance.radius);

  root.dataset.theme = appearance.preset;
  root.dataset.motion = appearance.motion;
  root.dataset.pointer = appearance.pointerLight ? 'on' : 'off';

  root.style.setProperty('--accent', accent.colours[0]);
  root.style.setProperty('--accent-strong', accent.colours[1]);
  root.style.setProperty('--radius', radius.value);

  // One control, two effects: blur grows with the setting while the
  // surface becomes more translucent, which is what reads as "more
  // glass" rather than simply "blurrier".
  const g = appearance.glass / 100;

  // The range has to be wide to be visible at all: at the previous
  // 0.92-0.57 the panel colour and the backdrop were close enough
  // that the whole slider moved the result by 13/765 of a channel.
  root.style.setProperty('--glass-blur', `${(g * 26).toFixed(1)}px`);
  root.style.setProperty('--glass-alpha', (0.98 - g * 0.62).toFixed(3));
  root.style.setProperty('--glass-edge', (0.05 + g * 0.16).toFixed(3));

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance));
  } catch {
    // Applies for this session; only the memory is lost.
  }
}
