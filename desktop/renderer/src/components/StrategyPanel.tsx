import { useState, type JSX } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { Strategy, StrategyParameters } from '../../../shared/types';
import { backend } from '../services/backend';

/**
 * Choose and tune the parameters the signal engine runs on.
 *
 * A strategy is a set of numbers, never code, so this panel is a form
 * rather than an editor. The built-in one is read-only: it is the
 * reference the application ships with, and duplicating it is how you
 * start your own.
 */

interface Field {
  key: keyof Omit<StrategyParameters, 'timeframe_weights'>;
  label: string;
  min: number;
  max: number;
  step: number;
  /** What moving it actually does, in the user's terms. */
  help: string;
}

const FIELDS: Field[] = [
  {
    key: 'direction_threshold',
    label: 'Conviction to leave WAIT',
    min: 0.05,
    max: 0.9,
    step: 0.01,
    help: 'How much the components must agree before a side is called. Higher means fewer signals.',
  },
  {
    key: 'stretched_rsi_penalty',
    label: 'Stretched-RSI penalty',
    min: 0,
    max: 1,
    step: 0.05,
    help: 'How much an already-extended move is marked down.',
  },
  {
    key: 'level_proximity_atr',
    label: 'Level proximity (ATR)',
    min: 0.2,
    max: 5,
    step: 0.1,
    help: 'How near support or resistance counts as approaching it.',
  },
  {
    key: 'level_proximity_effect',
    label: 'Level proximity effect',
    min: 0,
    max: 1,
    step: 0.05,
    help: 'How much being near a level moves the structure component.',
  },
  {
    key: 'minimum_bars_for_timeframe',
    label: 'Minimum bars per timeframe',
    min: 20,
    max: 1000,
    step: 10,
    help: 'Bars needed before a timeframe is allowed to contribute.',
  },
];

const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1'] as const;

function Editor({
  draft,
  onChange,
}: {
  draft: StrategyParameters;
  onChange: (next: StrategyParameters) => void;
}): JSX.Element {
  return (
    <div className="strategy__fields">
      {FIELDS.map((field) => (
        <label key={field.key} className="strategy__field">
          <span className="strategy__field-label">
            {field.label}
            <span className="strategy__value">{draft[field.key]}</span>
          </span>
          <input
            type="range"
            min={field.min}
            max={field.max}
            step={field.step}
            value={draft[field.key]}
            onChange={(e) =>
              onChange({ ...draft, [field.key]: Number(e.target.value) })
            }
          />
          <span className="strategy__help">{field.help}</span>
        </label>
      ))}

      <div className="strategy__weights">
        <span className="strategy__field-label">Timeframe weights</span>
        <span className="strategy__help">
          How much each timeframe counts toward the combined view. They are
          used in proportion, so only the ratios matter.
        </span>
        <div className="strategy__weight-row">
          {TIMEFRAMES.map((tf) => (
            <label key={tf} className="strategy__weight">
              <span>{tf}</span>
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={draft.timeframe_weights[tf] ?? 0}
                onChange={(e) =>
                  onChange({
                    ...draft,
                    timeframe_weights: {
                      ...draft.timeframe_weights,
                      [tf]: Number(e.target.value),
                    },
                  })
                }
              />
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

export function StrategyPanel(): JSX.Element {
  const client = useQueryClient();

  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [draft, setDraft] = useState<StrategyParameters | null>(null);
  const [error, setError] = useState<string | null>(null);

  const strategies = useQuery({
    queryKey: ['strategies'],
    queryFn: () => backend.strategies(),
  });

  const active = useQuery({
    queryKey: ['strategy-active'],
    queryFn: () => backend.activeStrategy(),
  });

  /** Every panel downstream reads the engine, so refresh all of them. */
  const refresh = async (): Promise<void> => {
    setError(null);

    await Promise.all(
      [
        'strategies',
        'strategy-active',
        'signal',
        'multi',
        'analysis',
        'plan',
      ].map((key) => client.invalidateQueries({ queryKey: [key] })),
    );
  };

  const save = useMutation({
    mutationFn: () =>
      backend.saveStrategy(
        { name, parameters: draft as StrategyParameters, notes: '' },
        editing && editing !== 'new' ? editing : undefined,
      ),
    onSuccess: async () => {
      setEditing(null);
      setDraft(null);
      await refresh();
    },
    onError: (e) => setError(String(e instanceof Error ? e.message : e)),
  });

  const activate = useMutation({
    mutationFn: (id: string) => backend.activateStrategy(id),
    onSuccess: refresh,
    onError: (e) => setError(String(e)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => backend.deleteStrategy(id),
    onSuccess: refresh,
    onError: (e) => setError(String(e)),
  });

  const startEdit = (strategy: Strategy, duplicate: boolean): void => {
    setError(null);
    setEditing(duplicate ? 'new' : strategy.id);
    setName(duplicate ? `${strategy.name} copy` : strategy.name);
    setDraft({ ...strategy.parameters });
  };

  if (strategies.isPending) {
    return <p className="strategy__empty">Loading…</p>;
  }

  if (strategies.isError) {
    return <p className="strategy__empty">Strategies are unavailable.</p>;
  }

  const activeId = active.data?.id;

  return (
    <div className="strategy">
      {editing && draft ? (
        <form
          className="strategy__editor"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <input
            className="strategy__name"
            value={name}
            maxLength={60}
            placeholder="Name this strategy"
            onChange={(e) => setName(e.target.value)}
          />

          <Editor draft={draft} onChange={setDraft} />

          {error && <p className="strategy__error">{error}</p>}

          <p className="strategy__caveat">
            Changing these changes what the engine calls a signal. It does
            not make the signals better — only a backtest can say whether a
            change helped, and this system has no measured record yet.
          </p>

          <div className="strategy__actions">
            <button
              type="submit"
              className="button button--small"
              disabled={save.isPending || !name.trim()}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => {
                setEditing(null);
                setDraft(null);
                setError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          {error && <p className="strategy__error">{error}</p>}

          <ul className="strategy__list">
            {strategies.data.map((strategy) => (
              <li
                key={strategy.id}
                className={`strategy__item${
                  strategy.id === activeId ? ' strategy__item--active' : ''
                }`}
              >
                <div className="strategy__head">
                  <span className="strategy__title">
                    {strategy.name}
                    {strategy.builtin && (
                      <span className="strategy__tag">read-only</span>
                    )}
                    {strategy.id === activeId && (
                      <span className="strategy__tag strategy__tag--on">
                        in use
                      </span>
                    )}
                  </span>
                </div>

                <p className="strategy__summary">
                  Conviction {strategy.parameters.direction_threshold} · RSI
                  penalty {strategy.parameters.stretched_rsi_penalty} · levels{' '}
                  {strategy.parameters.level_proximity_atr} ATR
                </p>

                <div className="strategy__actions">
                  {strategy.id !== activeId && (
                    <button
                      type="button"
                      className="button button--small"
                      onClick={() => activate.mutate(strategy.id)}
                      disabled={activate.isPending}
                    >
                      Use this
                    </button>
                  )}
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => startEdit(strategy, true)}
                  >
                    Duplicate
                  </button>
                  {!strategy.builtin && (
                    <>
                      <button
                        type="button"
                        className="button button--small"
                        onClick={() => startEdit(strategy, false)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="button button--small"
                        onClick={() => {
                          if (
                            window.confirm(`Delete "${strategy.name}"?`)
                          ) {
                            remove.mutate(strategy.id);
                          }
                        }}
                        disabled={remove.isPending}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>

          <p className="strategy__caveat">
            The built-in strategy is the engine as shipped and cannot be
            changed. Duplicate it to make your own. Strategies are numbers,
            not code — nothing here runs a script.
          </p>
        </>
      )}
    </div>
  );
}
