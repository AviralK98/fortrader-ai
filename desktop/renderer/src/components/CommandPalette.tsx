import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { createPortal } from 'react-dom';

import { ACCENTS, MOTIONS, PRESETS } from '../appearance';
import { requestAppearance, requestView, score } from '../commands';
import { VIEW_ICONS } from './ViewIcons';

interface Command {
  id: string;
  label: string;
  group: string;
  /** Extra words to match against that are not shown. */
  keywords?: string;
  hint?: string;
  icon?: JSX.Element;
  run: () => void;
}

const VIEWS: { id: string; label: string }[] = [
  { id: 'signal', label: 'Signal' },
  { id: 'next', label: 'What To Do Next' },
  { id: 'indicators', label: 'Indicators' },
  { id: 'ask', label: 'Ask About This' },
  { id: 'paper', label: 'Paper Trading' },
  { id: 'positions', label: 'Open Positions' },
  { id: 'backtest', label: 'Backtest' },
  { id: 'strategy', label: 'Strategy' },
  { id: 'quotes', label: 'Watchlist' },
  { id: 'candles', label: 'Candle History' },
  { id: 'setup', label: 'Connect Claude Code' },
];

function buildCommands(): Command[] {
  return [
    ...VIEWS.map((view) => ({
      id: `view:${view.id}`,
      label: view.label,
      group: 'Go to',
      keywords: 'view panel section open',
      icon: VIEW_ICONS[view.id],
      run: () => requestView(view.id),
    })),

    ...PRESETS.map((preset) => ({
      id: `preset:${preset.id}`,
      label: preset.name,
      group: 'Theme',
      keywords: `preset theme colour color ${preset.hint ?? ''}`,
      hint: preset.hint,
      run: () => requestAppearance({ preset: preset.id, accent: preset.accent }),
    })),

    ...ACCENTS.map((accent) => ({
      id: `accent:${accent.id}`,
      label: accent.name,
      group: 'Accent',
      keywords: 'accent colour color highlight',
      run: () => requestAppearance({ accent: accent.id }),
    })),

    ...MOTIONS.map((motion) => ({
      id: `motion:${motion.id}`,
      label: `Background motion: ${motion.name}`,
      group: 'Appearance',
      keywords: 'waves animation movement speed',
      run: () => requestAppearance({ motion: motion.id }),
    })),

    {
      id: 'pointer:on',
      label: 'Waves follow the pointer',
      group: 'Appearance',
      keywords: 'cursor mouse lift',
      run: () => requestAppearance({ pointerLight: true }),
    },
    {
      id: 'pointer:off',
      label: 'Stop waves following the pointer',
      group: 'Appearance',
      keywords: 'cursor mouse lift disable',
      run: () => requestAppearance({ pointerLight: false }),
    },
    {
      id: 'scripts',
      label: 'Open strategy scripts folder',
      group: 'Actions',
      keywords: 'python custom analyse file',
      run: () => void window.desktop.openScriptsFolder(),
    },
    {
      id: 'updates',
      label: 'Check for updates',
      group: 'Actions',
      keywords: 'version upgrade release',
      run: () => window.desktop.checkForUpdates(),
    },
  ];
}

/**
 * Command palette.
 *
 * Everything the interface can do, reachable by typing. Opened with
 * Ctrl+K — the shortcut is registered on the window rather than on the
 * button, so it works wherever focus happens to be.
 *
 * Portalled to the body and hiding the Fortrade view while open, for the
 * same two reasons the appearance sheet does: an ancestor with a
 * backdrop-filter traps fixed positioning, and the chart is a native
 * view that no z-index can sit in front of.
 */
export function CommandPalette(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo(() => buildCommands(), []);

  const matches = useMemo(() => {
    const ranked = commands
      .map((command) => ({
        command,
        rank: score(`${command.label} ${command.keywords ?? ''}`, query),
      }))
      .filter((entry): entry is { command: Command; rank: number } =>
        entry.rank !== null,
      );

    // Stable within a group when nothing is typed, ranked when it is.
    if (query.trim()) ranked.sort((a, b) => b.rank - a.rank);

    // A heading is shown wherever the group differs from the row above.
    // Compared against the neighbour rather than tracked in a running
    // variable: mutation during a map is state in disguise, and it goes
    // wrong the moment React renders the list twice.
    const top = ranked.slice(0, 40);

    return top.map((entry, index) => ({
      command: entry.command,
      heading:
        top[index - 1]?.command.group === entry.command.group
          ? null
          : entry.command.group,
    }));
  }, [commands, query]);

  /** Always opens on a clean search rather than the last one. */
  const show = (): void => {
    setQuery('');
    setCursor(0);
    setOpen(true);
  };

  useEffect(() => {
    const shortcut = (event: KeyboardEvent): void => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((was) => {
          if (!was) {
            setQuery('');
            setCursor(0);
          }

          return !was;
        });
      }
    };

    window.addEventListener('keydown', shortcut);

    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  // Only external systems here: focus, and the native chart that would
  // otherwise sit in front of the overlay.
  useEffect(() => {
    if (!open) return;

    inputRef.current?.focus();
    window.desktop.setFortradeVisible(false);

    return () => window.desktop.setFortradeVisible(true);
  }, [open]);

  // Keep the highlighted row on screen while arrowing through a long list.
  useEffect(() => {
    listRef.current
      ?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [cursor, matches]);

  const runAt = (index: number): void => {
    const match = matches[index];

    if (!match) return;

    match.command.run();
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent): void => {
    if (event.key === 'Escape') {
      setOpen(false);
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setCursor((c) => (matches.length ? (c + 1) % matches.length : 0));
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setCursor((c) =>
        matches.length ? (c - 1 + matches.length) % matches.length : 0,
      );
    }

    if (event.key === 'Enter') {
      event.preventDefault();
      runAt(cursor);
    }
  };

  return (
    <>
      <button
        type="button"
        className="palette__trigger"
        onClick={show}
        title="Quick actions (Ctrl+K)"
        aria-label="Quick actions"
      >
        {/* A magnifier, not a command glyph: this is a search, and the
            shortcut is Ctrl+K on the platform this ships to. Same 16px
            grid and stroke weight as the view icons. */}
        <svg
          viewBox="0 0 16 16"
          aria-hidden="true"
          focusable="false"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <circle cx="7" cy="7" r="4.25" />
          <path d="M10.2 10.2 13.6 13.6" />
        </svg>
      </button>

      {open &&
        createPortal(
          <div
            className="palette__scrim"
            onClick={() => setOpen(false)}
            role="presentation"
          >
            <div
              className="palette"
              role="dialog"
              aria-modal="true"
              aria-label="Quick actions"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="palette__search">
                <input
                  ref={inputRef}
                  type="text"
                  className="palette__input"
                  placeholder="Search views, themes, actions…"
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setCursor(0);
                  }}
                  onKeyDown={onKeyDown}
                />
                <kbd className="palette__kbd">esc</kbd>
              </div>

              <div className="palette__list" ref={listRef}>
                {matches.length === 0 && (
                  <p className="palette__empty">Nothing matches that.</p>
                )}

                {matches.map(({ command, heading }, index) => (
                  <div key={command.id}>
                    {heading && (
                      <span className="palette__heading">{heading}</span>
                    )}
                    <button
                      type="button"
                      data-active={index === cursor}
                      className={`palette__item${
                        index === cursor ? ' palette__item--on' : ''
                      }`}
                      onMouseEnter={() => setCursor(index)}
                      onClick={() => runAt(index)}
                    >
                      <span className="palette__icon">{command.icon}</span>
                      <span className="palette__label">{command.label}</span>
                      {command.hint && (
                        <span className="palette__hint">{command.hint}</span>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
