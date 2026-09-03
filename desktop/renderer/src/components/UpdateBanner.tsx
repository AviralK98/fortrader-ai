import { useEffect, useState, type JSX } from 'react';

import type { UpdateState } from '../../../shared/types';

/**
 * Update status.
 *
 * Restarting is always the user's decision — the app may be holding a
 * chart they are reading or a paper position they are watching, and
 * relaunching underneath them would drop the Fortrade session view.
 */
export function UpdateBanner(): JSX.Element | null {
  const [state, setState] = useState<UpdateState>({ status: 'idle' });

  useEffect(() => {
    void window.desktop.getUpdateState().then(setState);

    return window.desktop.onUpdateChanged(setState);
  }, []);

  if (state.status === 'ready') {
    return (
      <div className="update-banner update-banner--ready">
        <span>
          Version <strong>{state.version}</strong> is ready.
        </span>
        <button
          type="button"
          className="button button--small"
          onClick={() => window.desktop.installUpdate()}
        >
          Restart &amp; update
        </button>
      </div>
    );
  }

  if (state.status === 'manual' && state.downloadUrl) {
    return (
      <div className="update-banner update-banner--ready">
        <span>
          Version <strong>{state.version}</strong> is available.
        </span>
        {/* An ordinary link: the main process routes target=_blank to the
            system browser, so no privileged channel is needed to open a
            download. */}
        <a
          className="button button--small"
          href={state.downloadUrl}
          target="_blank"
          rel="noreferrer"
        >
          Download
        </a>
        <span className="update-banner__note">
          Open the .dmg and drag the app to Applications, replacing the
          old one.
        </span>
      </div>
    );
  }

  if (state.status === 'downloading') {
    return (
      <div className="update-banner">
        Downloading {state.version}
        {typeof state.percent === 'number' ? ` — ${state.percent}%` : '…'}
      </div>
    );
  }

  return null;
}
