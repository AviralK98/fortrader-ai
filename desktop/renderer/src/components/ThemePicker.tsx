import { useEffect, useRef, useState, type JSX } from 'react';

import { applyTheme, storedTheme, THEMES, type ThemeId } from '../theme';

/**
 * Theme selector.
 *
 * A menu rather than a row of swatches: the names carry a hint about
 * when each one is worth using, and "Light sits next to a dark chart" is
 * worth saying before someone picks it rather than after.
 */
export function ThemePicker(): JSX.Element {
  const [theme, setTheme] = useState<ThemeId>(() => storedTheme());
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (!open) return;

    const dismiss = (event: MouseEvent): void => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };

    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', escape);

    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const current = THEMES.find((t) => t.id === theme) ?? THEMES[0];

  return (
    <div className="theme" ref={root}>
      <button
        type="button"
        className="theme__trigger"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Change theme"
      >
        <span className="theme__swatch" aria-hidden="true" />
        <span className="theme__name">{current.name}</span>
      </button>

      {open && (
        <div className="theme__menu" role="menu">
          {THEMES.map((option) => (
            <button
              key={option.id}
              type="button"
              role="menuitemradio"
              aria-checked={option.id === theme}
              className={`theme__option${
                option.id === theme ? ' theme__option--on' : ''
              }`}
              onClick={() => {
                setTheme(option.id);
                setOpen(false);
              }}
            >
              <span
                className="theme__swatch"
                data-preview={option.id}
                aria-hidden="true"
              />
              <span className="theme__option-text">
                <span className="theme__option-name">{option.name}</span>
                <span className="theme__option-hint">{option.hint}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
