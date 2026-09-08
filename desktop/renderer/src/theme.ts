/**
 * Colour themes.
 *
 * The chosen theme is written to `data-theme` on the root element and the
 * palette is entirely CSS custom properties, so switching costs one
 * attribute change rather than a re-render.
 *
 * Worth knowing: only this panel changes. Fortrade's terminal fills the
 * rest of the window as a native view painted over the page, and it keeps
 * its own dark styling whatever is chosen here. Dark themes therefore sit
 * beside it more comfortably than Light does — which is why Dark is the
 * default rather than the system preference.
 */

export const THEMES = [
  {
    id: 'dark',
    name: 'Dark',
    hint: 'Default. Sits closest to the terminal beside it.',
  },
  {
    id: 'fortrade',
    name: 'Fortrade',
    hint: "Deep navy and blue, following the platform's own palette.",
  },
  {
    id: 'midnight',
    name: 'Midnight',
    hint: 'Near-black with a cool cast, for low light.',
  },
  {
    id: 'light',
    name: 'Light',
    hint: 'Bright. Contrasts sharply with the dark chart beside it.',
  },
] as const;

export type ThemeId = (typeof THEMES)[number]['id'];

export const DEFAULT_THEME: ThemeId = 'dark';

const STORAGE_KEY = 'fortrader.theme';

function isTheme(value: string | null): value is ThemeId {
  return THEMES.some((theme) => theme.id === value);
}

export function storedTheme(): ThemeId {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);

    return isTheme(saved) ? saved : DEFAULT_THEME;
  } catch {
    // Private mode, or storage disabled. A default is a fine answer.
    return DEFAULT_THEME;
  }
}

export function applyTheme(theme: ThemeId): void {
  document.documentElement.dataset.theme = theme;

  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The theme still applies for this session; only the memory is lost.
  }
}
