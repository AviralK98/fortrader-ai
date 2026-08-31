import { useEffect, useState, type JSX } from 'react';

import type { McpSetup } from '../../../shared/types';

/**
 * Connect Claude Code to this installation.
 *
 * The paths differ per machine, so they are resolved at runtime rather
 * than written into documentation someone has to adapt.
 *
 * Writing to the user's Claude configuration happens only when they press
 * the button, and merges rather than replaces — anything else there is
 * left alone.
 */
export function SetupPanel(): JSX.Element {
  const [setup, setSetup] = useState<McpSetup | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void window.desktop.getMcpSetup().then(setSetup);
  }, []);

  if (!setup) {
    return <div className="empty-note">Resolving setup…</div>;
  }

  const copy = () => {
    window.desktop.copyToClipboard(setup.configJson);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const write = async () => {
    setBusy(true);

    try {
      const outcome = await window.desktop.writeMcpConfig();

      setResult(
        outcome.written
          ? `Added to ${outcome.path}. Restart Claude Code to load it.`
          : (outcome.detail ?? 'Could not write the config.'),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="setup">
      <p className="setup__intro">
        Claude Code can query this application through a read-only bridge —
        account, quotes, indicators, signals, backtests and paper trades. It
        cannot place trades.
      </p>

      <pre className="setup__code">{setup.configJson}</pre>

      <div className="setup__actions">
        <button type="button" className="button" onClick={copy}>
          {copied ? 'Copied' : 'Copy config'}
        </button>

        <button
          type="button"
          className="button"
          onClick={() => void write()}
          disabled={busy}
        >
          {busy ? 'Writing…' : 'Add to Claude Code'}
        </button>
      </div>

      {result && <div className="setup__result">{result}</div>}

      <p className="setup__note">
        Adds one entry to <code>{setup.configPath}</code>, leaving any other
        servers untouched. <strong>Restart Claude Code afterwards</strong> —
        it reads this file at startup. Fortrader AI must be running for the
        tools to return data.
        {!setup.packaged &&
          ' This is a development build, so it points at your source tree.'}
      </p>
    </div>
  );
}
