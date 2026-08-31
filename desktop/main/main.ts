/**
 * Fortrader AI — Electron main process.
 *
 * Startup sequence:
 *   1. create the window and our React UI view
 *   2. start the Python backend sidecar and wait for /health
 *   3. create the Fortrade WebContentsView and load Web Fortrader
 *
 * The user double-clicks one icon. Nothing here requires an external
 * Chrome, a debugging port, or a manually started Python process.
 */

import { existsSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  BaseWindow,
  WebContentsView,
  app,
  session,
  shell,
} from 'electron';

import {
  IPC,
  type FortradeViewState,
  type ShellInfo,
  type ViewBounds,
} from '../shared/types';
import { AppStateMachine } from './app-state';
import { BackendProcess } from './backend-process';
import { CandleCapture } from './candle-capture';
import { dumpFortradeDom, isDomProbeEnabled } from './dom-probe';
import { FortradeAdapter } from './fortrade-adapter';
import { FortradeView } from './fortrade-view';
import { NetworkProbe, isNetworkProbeEnabled } from './network-probe';
import { Updater } from './updater';
import { registerIpc, safeSend, unregisterIpc } from './ipc';
import { createLogger } from './logging';

const log = createLogger('main');

const isDev = !app.isPackaged;

// Height kept under 1080p minus the taskbar so the account bar is never
// clipped on a standard display.
const WINDOW_DEFAULTS = { width: 1600, height: 920, minWidth: 1100, minHeight: 700 };

let window: BaseWindow | null = null;
let uiView: WebContentsView | null = null;
let fortradeView: FortradeView | null = null;
let backend: BackendProcess | null = null;
let backendReady = false;
let adapter: FortradeAdapter | null = null;
let candleCapture: CandleCapture | null = null;
let updater: Updater | null = null;

const appState = new AppStateMachine();

/**
 * Fortrade occupies the left pane. Until the renderer reports real bounds
 * we keep the view collapsed so it cannot cover our chrome.
 */
let fortradeBounds: ViewBounds = { x: 0, y: 0, width: 0, height: 0 };

function uiContents() {
  return uiView?.webContents ?? null;
}

/**
 * Content Security Policy for *our* renderer only.
 *
 * Development needs the Vite dev server plus the inline/eval it uses for
 * HMR. Production is strict: no eval, no remote origins, nothing but the
 * bundle we shipped.
 */
function applyRendererCsp(): void {
  const policy = isDev
    ? [
        "default-src 'self' 'unsafe-inline' data: blob:",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
        "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://localhost:*",
        "img-src 'self' data: blob:",
      ].join('; ')
    : [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "connect-src 'self' http://127.0.0.1:*",
        "img-src 'self' data:",
        "object-src 'none'",
        "frame-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
      ].join('; ');

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [policy],
      },
    });
  });
}

/**
 * Window icon for development.
 *
 * A packaged build takes its icon from the executable, which
 * electron-builder embeds. In development there is no such exe, so the
 * taskbar would otherwise show the stock Electron logo.
 */
function resolveWindowIcon(): string | undefined {
  if (app.isPackaged) return undefined;

  const root = join(app.getAppPath(), '..');

  // Windows loads .ico; macOS and Linux need a raster image, so the
  // exported PNG is used there. First match wins.
  const candidates =
    process.platform === 'win32'
      ? [join(root, 'fortrader-ai.ico')]
      : [
          join(root, 'export', 'mac', 'icon_512x512.png'),
          join(root, 'export', 'mac', 'icon_1024x1024.png'),
        ];

  return candidates.find((path) => existsSync(path));
}

function createWindow(): void {
  const icon = resolveWindowIcon();

  window = new BaseWindow({
    ...WINDOW_DEFAULTS,
    title: 'Fortrader AI',
    backgroundColor: '#0b0f14',
    show: false,
    ...(icon ? { icon } : {}),
  });

  uiView = new WebContentsView({
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  window.contentView.addChildView(uiView);

  // Our UI must never navigate away from the bundle.
  uiView.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: 'deny' };
  });

  layoutViews();

  window.on('resize', layoutViews);

  window.on('closed', () => {
    window = null;
    uiView = null;
    fortradeView = null;
  });

  if (isDev && process.env.ELECTRON_RENDERER_URL) {
    void uiView.webContents.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void uiView.webContents.loadFile(
      join(__dirname, '../renderer/index.html'),
    );
  }

  uiView.webContents.once('did-finish-load', () => {
    window?.show();
  });
}

function layoutViews(): void {
  if (!window || !uiView) return;

  const { width, height } = window.getContentBounds();

  uiView.setBounds({ x: 0, y: 0, width, height });

  // Re-assert the Fortrade rect; the renderer refreshes it on its own
  // resize observer, but this keeps the two in step during a drag.
  fortradeView?.setBounds(fortradeBounds);
}

/**
 * Fortrade is a single-page app, so `did-navigate-in-page` fires many times
 * per real transition. Settle before reclassifying, or the state machine
 * thrashes between LOADING and AUTH_REQUIRED on every client-side route.
 */
const STATE_SETTLE_MS = 750;

let settleTimer: NodeJS.Timeout | null = null;

function createFortradeView(): void {
  if (!window) return;

  fortradeView = new FortradeView((state: FortradeViewState) => {
    safeSend(uiContents(), IPC.fortradeViewChanged, state);

    if (settleTimer) clearTimeout(settleTimer);

    settleTimer = setTimeout(() => {
      // Only a provisional classification. Once extraction succeeds the
      // adapter owns the state, and a URL never overrides a confirmed
      // session.
      if (appState.current !== 'CONNECTED') {
        appState.applyFortradeUrl(state.url, state.loading);
      }
    }, STATE_SETTLE_MS);
  });

  window.contentView.addChildView(fortradeView.view);

  // Apply whatever bounds the renderer already reported while the view
  // was still being created.
  fortradeView.setBounds(fortradeBounds);
  fortradeView.load();

  if (backend && backendReady) {
    adapter = new FortradeAdapter(
      () => fortradeView?.view.webContents ?? null,
      {
        backendUrl: backend.url,
        ingestToken: backend.token,
        setState: (state, detail) => appState.set(state, detail ?? null),
      },
    );

    adapter.start();

    // Only one client may hold the debugger, so the dev network probe and
    // the real capture are mutually exclusive.
    if (isNetworkProbeEnabled()) {
      log.warn('Network probe enabled; candle capture disabled this run');
    } else {
      candleCapture = new CandleCapture(fortradeView.view.webContents, {
        backendUrl: backend.url,
        ingestToken: backend.token,
        getSymbolMap: () => adapter?.getSymbolMap() ?? {},
      });

      candleCapture.start();
    }
  } else {
    log.warn('Extraction not started: backend unavailable');
  }

  if (isNetworkProbeEnabled()) {
    const probe = new NetworkProbe(fortradeView.view.webContents);
    const out = process.env.FORTRADER_DUMP_NET_PATH ?? 'net-probe.json';
    const seconds = Number(process.env.FORTRADER_DUMP_NET_SECONDS ?? 45);

    probe.start();

    setTimeout(() => {
      probe.write(out);
      probe.stop();
    }, seconds * 1_000);
  }

  // Dev-only: capture our own renderer regardless of window z-order.
  if (process.env.FORTRADER_CAPTURE_UI) {
    const target = process.env.FORTRADER_CAPTURE_UI;

    setTimeout(() => {
      void uiView?.webContents
        .capturePage()
        .then((image) => {
          writeFileSync(target, image.toPNG());
          log.info('UI captured', { path: target });
        })
        .catch((error: unknown) => {
          log.error('UI capture failed', { error: String(error) });
        });
    }, 14_000);
  }

  if (isDomProbeEnabled()) {
    const outputPath = process.env.FORTRADER_DUMP_DOM_PATH ?? 'dom-probe.json';

    // Give the SPA time to render the account panel and watchlist.
    fortradeView.view.webContents.once('did-stop-loading', () => {
      setTimeout(() => {
        if (fortradeView) {
          void dumpFortradeDom(fortradeView.view.webContents, outputPath);
        }
      }, 8_000);
    });
  }
}

async function startBackend(): Promise<void> {
  backend = new BackendProcess((line: string) => {
    safeSend(uiContents(), IPC.backendLog, line);
  });

  try {
    await backend.start();
    backendReady = true;
  } catch (error) {
    backendReady = false;

    log.error('Backend failed to start', { error: String(error) });

    appState.set(
      'BACKEND_ERROR',
      'The analysis backend could not be started.',
    );
  }
}

function wireStateBroadcast(): void {
  appState.subscribe((state, detail) => {
    safeSend(uiContents(), IPC.stateChanged, state, detail);

    void backend?.postState(state, detail ?? undefined);
  });
}

// A second instance would fight over the session partition and the port.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });

  void app.whenReady().then(async () => {
    applyRendererCsp();

    wireStateBroadcast();

    createWindow();

    // Registered before the backend await: the renderer mounts immediately
    // and calls getShellInfo, which would otherwise find no handler.
    updater = new Updater((state) => {
      safeSend(uiContents(), IPC.updateChanged, state);
    });

    registerIpc({
      getFortradeView: () => fortradeView,
      onBounds: (bounds) => {
        fortradeBounds = bounds;
      },
      getShellInfo: (): ShellInfo => ({
        backendUrl: backend?.url ?? '',
        backendReady,
        appVersion: app.getVersion(),
        tradingEnabled: false,
      }),
      updater: {
        current: () => updater?.current() ?? { status: 'idle' },
        check: () => void updater?.check(),
        install: () => updater?.install(),
      },
    });

    updater.start();

    appState.set('STARTING');

    await startBackend();

    createFortradeView();

    appState.set('FORTRADE_LOADING');
  });
}

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  updater?.stop();
  candleCapture?.stop();
  adapter?.stop();
  unregisterIpc();
  backend?.stop();
});

// Defence in depth: refuse any preload attachment or webview creation we
// did not explicitly configure.
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => {
    log.warn('Blocked <webview> attachment');
    event.preventDefault();
  });
});
