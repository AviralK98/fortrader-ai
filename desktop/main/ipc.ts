/**
 * Typed IPC handlers.
 *
 * Only channels declared in `shared/types.ts` are registered, and every
 * payload is validated before use — the renderer is trusted more than
 * Fortrade content, but not blindly.
 */

import { ipcMain, type WebContents } from 'electron';

import { IPC, type ShellInfo, type ViewBounds } from '../shared/types';
import type { FortradeView } from './fortrade-view';
import { createLogger } from './logging';

const log = createLogger('ipc');

function isViewBounds(value: unknown): value is ViewBounds {
  if (!value || typeof value !== 'object') return false;

  const candidate = value as Record<string, unknown>;

  return (['x', 'y', 'width', 'height'] as const).every(
    (key) => typeof candidate[key] === 'number' && Number.isFinite(candidate[key]),
  );
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
}

export function unregisterIpc(): void {
  for (const channel of [
    IPC.getShellInfo,
    IPC.setFortradeBounds,
    IPC.setFortradeVisible,
    IPC.reloadFortrade,
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
