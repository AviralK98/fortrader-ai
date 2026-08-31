/**
 * Typed IPC handlers.
 *
 * Only channels declared in `shared/types.ts` are registered, and every
 * payload is validated before use — the renderer is trusted more than
 * Fortrade content, but not blindly.
 */

import { clipboard, ipcMain, type WebContents } from 'electron';

import {
  IPC,
  type ShellInfo,
  type UpdateState,
  type ViewBounds,
} from '../shared/types';
import type { FortradeView } from './fortrade-view';
import { createLogger } from './logging';
import { resolveMcpSetup, writeMcpConfig } from './mcp-setup';

const log = createLogger('ipc');

function isViewBounds(value: unknown): value is ViewBounds {
  if (!value || typeof value !== 'object') return false;

  const candidate = value as Record<string, unknown>;

  return (['x', 'y', 'width', 'height'] as const).every(
    (key) => typeof candidate[key] === 'number' && Number.isFinite(candidate[key]),
  );
}

export interface UpdaterBridge {
  current: () => UpdateState;
  check: () => void;
  install: () => void;
}

export interface IpcDependencies {
  /**
   * Resolved lazily: handlers are registered as soon as the window exists,
   * which is before the Fortrade view is created. Bounds that arrive early
   * are recorded by `onBounds` and replayed once the view appears.
   */
  getFortradeView: () => FortradeView | null;
  onBounds: (bounds: ViewBounds) => void;
  getShellInfo: () => ShellInfo;
  updater: UpdaterBridge;
}

export function registerIpc(deps: IpcDependencies): void {
  ipcMain.handle(IPC.getShellInfo, () => deps.getShellInfo());

  ipcMain.on(IPC.setFortradeBounds, (_event, bounds: unknown) => {
    if (!isViewBounds(bounds)) {
      log.warn('Rejected malformed bounds payload');
      return;
    }

    deps.onBounds(bounds);
    deps.getFortradeView()?.setBounds(bounds);
  });

  ipcMain.on(IPC.setFortradeVisible, (_event, visible: unknown) => {
    if (typeof visible !== 'boolean') {
      log.warn('Rejected malformed visibility payload');
      return;
    }

    deps.getFortradeView()?.setVisible(visible);
  });

  ipcMain.on(IPC.reloadFortrade, () => {
    deps.getFortradeView()?.reload();
  });

  // --- Claude Code setup ------------------------------------------

  ipcMain.handle(IPC.getMcpSetup, () => resolveMcpSetup());

  // Only ever reached from an explicit button press. The renderer cannot
  // trigger it on load, and the write merges rather than replaces.
  ipcMain.handle(IPC.writeMcpConfig, () => writeMcpConfig());

  ipcMain.on(IPC.copyToClipboard, (_event, text: unknown) => {
    if (typeof text !== 'string' || text.length > 20_000) {
      log.warn('Rejected malformed clipboard payload');
      return;
    }

    clipboard.writeText(text);
  });

  // --- Updates -----------------------------------------------------

  ipcMain.handle(IPC.getUpdateState, () => deps.updater.current());

  ipcMain.on(IPC.checkForUpdates, () => deps.updater.check());

  ipcMain.on(IPC.installUpdate, () => deps.updater.install());
}

export function unregisterIpc(): void {
  for (const channel of [
    IPC.getShellInfo,
    IPC.setFortradeBounds,
    IPC.setFortradeVisible,
    IPC.reloadFortrade,
    IPC.getMcpSetup,
    IPC.writeMcpConfig,
    IPC.copyToClipboard,
    IPC.getUpdateState,
    IPC.checkForUpdates,
    IPC.installUpdate,
  ]) {
    ipcMain.removeHandler(channel);
    ipcMain.removeAllListeners(channel);
  }
}

/** Fire-and-forget send that tolerates a destroyed renderer. */
export function safeSend(
  contents: WebContents | null,
  channel: string,
  ...args: unknown[]
): void {
  if (!contents || contents.isDestroyed()) return;

  contents.send(channel, ...args);
}
