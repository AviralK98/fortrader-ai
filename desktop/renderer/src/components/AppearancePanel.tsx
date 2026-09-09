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
import { APPEARANCE_EVENT, onCommand } from '../commands';

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
  const sheetRef = useRef<HTMLElement>(null);

  useEffect(() => {
    applyAppearance(state);
  }, [state]);

  // Merged rather than replaced: the palette sends only what it changes.
  useEffect(() => {
    return onCommand<Partial<Appearance>>(APPEARANCE_EVENT, (patch) =>
      setState((prev) => ({ ...prev, ...patch })),
    );
  }, []);

  useEffect(() => {
    if (!open) return;

    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false);
    };

    // Closes on a click outside. There is no full-screen scrim: this
    // sheet sits inside the analysis panel's column and never covers the
    // chart, so dimming the window would darken a region the sheet is
    // not over. Hiding the chart instead -- which is what this did --
    // blanked the whole application to show a 340px panel.
    const dismiss = (event: MouseEvent): void => {
      if (!sheetRef.current?.contains(event.target as Node)) setOpen(false);
    };

    document.addEventListener('keydown', escape);
    // Deferred a frame: the click that opened the sheet is still
    // propagating, and would otherwise close it immediately.
    const timer = window.setTimeout(
      () => document.addEventListener('mousedown', dismiss),
      0,
    );

    closeRef.current?.focus();

    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('keydown', escape);
      document.removeEventListener('mousedown', dismiss);
    };
  }, [open]);

  const set = <K extends keyof Appearance>(
    key: K,
    value: Appearance[K],
  ): void => setState((prev) => ({ ...prev, [key]: value }));

  /**
   * Choosing a preset adopts the accent it was designed around.
   *
   * The accent row still overrides it straight afterwards, so this is a
   * sensible starting point rather than a lock — and it means a preset
   * never lands with a colour that fights its own surfaces.
   */
  const choosePreset = (id: string): void =>
    setState((prev) => ({ ...prev, preset: id, accent: presetFor(id).accent }));

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
        {/* Three lines: a menu reads as "there is more in here" where a
            colour swatch read as a decoration. The active preset tints
            them so the button still says which one is on. */}
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <g
            stroke={preset.swatch[0]}
            strokeWidth="1.7"
            strokeLinecap="round"
          >
            <line x1="2.5" y1="4.5" x2="13.5" y2="4.5" />
            <line x1="2.5" y1="8" x2="13.5" y2="8" />
            <line x1="2.5" y1="11.5" x2="13.5" y2="11.5" />
          </g>
        </svg>
      </button>

      {open &&
        createPortal(
          <>
          <aside
            ref={sheetRef}
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
                      onClick={() => choosePreset(option.id)}
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
                  Waves follow the pointer
                  <span className="field__note">
                    The bands rise toward the cursor and settle back.
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
