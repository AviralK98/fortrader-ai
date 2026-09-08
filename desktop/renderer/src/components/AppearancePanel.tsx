import { useEffect, useRef, useState, type JSX } from 'react';
import { createPortal } from 'react-dom';

import {
  ACCENTS,
  applyAppearance,
  MOTIONS,
  PRESETS,
  presetFor,
  RADII,
  storedAppearance,
  type Appearance,
} from '../appearance';

/**
 * Appearance settings.
 *
 * A slide-over rather than a dropdown: there are enough controls that a
 * menu would be a scrolling list, and changes apply live so the panel
 * behind is the preview.
 */
export function AppearancePanel(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<Appearance>(() => storedAppearance());
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    applyAppearance(state);
  }, [state]);

  useEffect(() => {
    if (!open) return;

    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('keydown', escape);
    closeRef.current?.focus();

    // Fortrade's chart is a native view composited above this page, so
    // no z-index can put the sheet in front of it. Hiding it while the
    // sheet is open is the only way the panel is fully visible -- and it
    // lets the scrim actually dim the whole window.
    window.desktop.setFortradeVisible(false);

    return () => {
      document.removeEventListener('keydown', escape);
      window.desktop.setFortradeVisible(true);
    };
  }, [open]);

  const set = <K extends keyof Appearance>(
    key: K,
    value: Appearance[K],
  ): void => setState((prev) => ({ ...prev, [key]: value }));

  const preset = presetFor(state.preset);

  return (
    <>
      <button
        type="button"
        className="appearance__trigger"
        onClick={() => setOpen(true)}
        title="Appearance"
        aria-label="Appearance settings"
      >
        <span
          className="swatch"
          style={{
            background: `linear-gradient(135deg, ${preset.swatch[0]}, ${preset.swatch[1]})`,
          }}
          aria-hidden="true"
        />
      </button>

      {open &&
        createPortal(
          <>
          <div
            className="sheet__scrim"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <aside
            className="sheet"
            role="dialog"
            aria-modal="true"
            aria-label="Appearance"
          >
            <header className="sheet__head">
              <h2>Appearance</h2>
              <button
                ref={closeRef}
                type="button"
                className="sheet__close"
                onClick={() => setOpen(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </header>

            <div className="sheet__body">
              <section className="field">
                <span className="field__label">Preset</span>
                <div className="preset-grid">
                  {PRESETS.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={`preset${
                        option.id === state.preset ? ' preset--on' : ''
                      }`}
                      onClick={() => set('preset', option.id)}
                      title={option.hint}
                    >
                      <span
                        className="preset__swatch"
                        style={{
                          background: `linear-gradient(135deg, ${option.swatch[0]}, ${option.swatch[1]})`,
                        }}
                        aria-hidden="true"
                      />
                      <span className="preset__name">{option.name}</span>
                    </button>
                  ))}
                </div>
                {preset.light && (
                  <p className="field__note">
                    Fortrade&apos;s chart keeps its own dark styling, so this
                    sits beside a dark panel.
                  </p>
                )}
              </section>

              <section className="field">
                <span className="field__label">Accent</span>
                <div className="accent-row">
                  {ACCENTS.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={`accent${
                        option.id === state.accent ? ' accent--on' : ''
                      }`}
                      style={{ background: option.colours[0] }}
                      onClick={() => set('accent', option.id)}
                      title={option.name}
                      aria-label={option.name}
                    />
                  ))}
                </div>
              </section>

              <section className="field">
                <span className="field__label">
                  Glass
                  <span className="field__value">{state.glass}%</span>
                </span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={state.glass}
                  onChange={(e) => set('glass', Number(e.target.value))}
                />
                <p className="field__note">
                  How much the panels blur and let the background through.
                </p>
              </section>

              <section className="field">
                <span className="field__label">Corners</span>
                <div className="segmented">
                  {RADII.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={option.id === state.radius ? 'on' : ''}
                      onClick={() => set('radius', option.id)}
                    >
                      {option.name}
                    </button>
                  ))}
                </div>
              </section>

              <section className="field">
                <span className="field__label">Background motion</span>
                <div className="segmented">
                  {MOTIONS.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={option.id === state.motion ? 'on' : ''}
                      onClick={() => set('motion', option.id)}
                    >
                      {option.name}
                    </button>
                  ))}
                </div>
              </section>

              <section className="field field--row">
                <span className="field__label">
                  Pointer lighting
                  <span className="field__note">
                    The glass catches a faint highlight near the cursor.
                  </span>
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={state.pointerLight}
                  className={`toggle${state.pointerLight ? ' toggle--on' : ''}`}
                  onClick={() => set('pointerLight', !state.pointerLight)}
                >
                  <span className="toggle__knob" />
                </button>
              </section>
            </div>
          </aside>
          </>,
          document.body,
        )}
    </>
  );
}
