/**
 * Hosts Web Fortrader as a top-level `WebContentsView`.
 *
 * Not an iframe, and not an external Chrome: this is Electron's own
 * Chromium, on a dedicated persistent session partition, so the user logs
 * in once and the session survives restarts.
 *
 * Security posture — remote Fortrade content is untrusted:
 *   * its own session partition, isolated from our renderer
 *   * `nodeIntegration` off, `contextIsolation` on, `sandbox` on
 *   * no preload script, so no bridge exists into privileged code
 *   * navigation restricted to Fortrade hosts; popups denied
 *
 * We never store the user's credentials. Only Chromium's own cookie jar
 * persists, inside the Electron user-data directory.
 */

import { WebContentsView, shell, type Session, session } from 'electron';

import {
  FORTRADE_ALLOWED_HOSTS,
  FORTRADE_URL,
  type FortradeViewState,
  type ViewBounds,
} from '../shared/types';
import { createLogger } from './logging';

const log = createLogger('fortrade-view');

const PARTITION = 'persist:fortrade';

function isAllowedHost(rawUrl: string): boolean {
  try {
    const { hostname, protocol } = new URL(rawUrl);

    if (protocol !== 'https:') return false;

    return FORTRADE_ALLOWED_HOSTS.some(
      (allowed) => hostname === allowed || hostname.endsWith(`.${allowed}`),
    );
  } catch {
    return false;
  }
}

export class FortradeView {
  readonly view: WebContentsView;
  readonly session: Session;

  private state: FortradeViewState = {
    url: FORTRADE_URL,
    loading: true,
    authenticated: false,
  };

  constructor(private readonly onChange: (state: FortradeViewState) => void) {
    this.session = session.fromPartition(PARTITION);

    this.view = new WebContentsView({
      webPreferences: {
        partition: PARTITION,
        contextIsolation: true,
        nodeIntegration: false,
        nodeIntegrationInSubFrames: false,
        sandbox: true,
        webSecurity: true,
        // No preload: remote content gets no bridge into our process.
        spellcheck: false,
      },
    });

    this.harden();
    this.wireEvents();
  }

  private harden(): void {
    const { webContents } = this.view;

    // External links open in the real browser, never as an in-app window
    // that would inherit our privileges.
    webContents.setWindowOpenHandler(({ url }) => {
      if (isAllowedHost(url)) {
        void webContents.loadURL(url);
      } else {
        log.info('Opening external link outside the app', { url });
        void shell.openExternal(url);
      }

      return { action: 'deny' };
    });

    webContents.on('will-navigate', (event, url) => {
      if (!isAllowedHost(url)) {
        log.warn('Blocked navigation outside Fortrade', { url });
        event.preventDefault();
        void shell.openExternal(url);
      }
    });

    // Deny every permission request; nothing here needs camera, mic,
    // geolocation or notifications.
    this.session.setPermissionRequestHandler((_wc, permission, callback) => {
      log.info('Denied permission request', { permission });
      callback(false);
    });
  }

  private wireEvents(): void {
    const { webContents } = this.view;

    webContents.on('did-start-loading', () => {
      this.update({ loading: true });
    });

    webContents.on('did-stop-loading', () => {
      this.update({ loading: false, url: webContents.getURL() });
    });

    webContents.on('did-navigate', (_e, url) => {
      this.update({ url });
    });

    webContents.on('did-navigate-in-page', (_e, url) => {
      this.update({ url });
    });

    webContents.on('render-process-gone', (_e, details) => {
      log.error('Fortrade view process gone', { reason: details.reason });
    });

    webContents.on(
      'did-fail-load',
      (_e, errorCode, errorDescription, validatedURL) => {
        // -3 is ERR_ABORTED, routinely emitted by client-side routing.
        if (errorCode === -3) return;

        log.error('Fortrade failed to load', {
          errorCode,
          errorDescription,
          url: validatedURL,
        });
      },
    );
  }

  private update(patch: Partial<FortradeViewState>): void {
    this.state = { ...this.state, ...patch };
    this.onChange(this.state);
  }

  load(): void {
    log.info('Loading Web Fortrader', { url: FORTRADE_URL });
    void this.view.webContents.loadURL(FORTRADE_URL);
  }

  reload(): void {
    this.view.webContents.reload();
  }

  setBounds(bounds: ViewBounds): void {
    this.view.setBounds({
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
      width: Math.round(Math.max(0, bounds.width)),
      height: Math.round(Math.max(0, bounds.height)),
    });
  }

  setVisible(visible: boolean): void {
    this.view.setVisible(visible);
  }

  getState(): FortradeViewState {
    return this.state;
  }

  openDevTools(): void {
    this.view.webContents.openDevTools({ mode: 'detach' });
  }
}
