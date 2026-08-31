/**
 * The only bridge between the renderer and privileged code.
 *
 * Deliberately minimal: layout control, shell facts, and event
 * subscriptions. No filesystem, no shell, no network, no Node primitives,
 * and nothing that could reach an order-entry surface.
 *
 * This preload is attached to *our* UI view only. The Fortrade view runs
 * with no preload at all.
 */

import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

import {
  IPC,
  type AppStateValue,
  type DesktopApi,
  type FortradeViewState,
  type McpSetup,
  type ShellInfo,
  type UpdateState,
  type ViewBounds,
} from '../shared/types';

function subscribe<Args extends unknown[]>(
  channel: string,
  callback: (...args: Args) => void,
): () => void {
  const listener = (_event: IpcRendererEvent, ...args: unknown[]) => {
    callback(...(args as Args));
  };

  ipcRenderer.on(channel, listener);

  return () => {
    ipcRenderer.removeListener(channel, listener);
  };
}

const api: DesktopApi = {
  getShellInfo: (): Promise<ShellInfo> => ipcRenderer.invoke(IPC.getShellInfo),

  setFortradeBounds: (bounds: ViewBounds): void => {
    ipcRenderer.send(IPC.setFortradeBounds, bounds);
  },

  setFortradeVisible: (visible: boolean): void => {
    ipcRenderer.send(IPC.setFortradeVisible, visible);
  },

  reloadFortrade: (): void => {
    ipcRenderer.send(IPC.reloadFortrade);
  },

  onStateChanged: (
    cb: (state: AppStateValue, detail: string | null) => void,
  ): (() => void) => subscribe(IPC.stateChanged, cb),

  onFortradeViewChanged: (
    cb: (state: FortradeViewState) => void,
  ): (() => void) => subscribe(IPC.fortradeViewChanged, cb),

  onBackendLog: (cb: (line: string) => void): (() => void) =>
    subscribe(IPC.backendLog, cb),

  getMcpSetup: (): Promise<McpSetup> => ipcRenderer.invoke(IPC.getMcpSetup),

  // Deliberately a separate call from getMcpSetup: reading the config is
  // harmless, writing to the user's Claude configuration is not, and the
  // two must never be conflated.
  writeMcpConfig: (): Promise<{
    written: boolean;
    path: string;
    detail?: string;
  }> => ipcRenderer.invoke(IPC.writeMcpConfig),

  copyToClipboard: (text: string): void => {
    ipcRenderer.send(IPC.copyToClipboard, text);
  },

  getUpdateState: (): Promise<UpdateState> =>
    ipcRenderer.invoke(IPC.getUpdateState),

  checkForUpdates: (): void => {
    ipcRenderer.send(IPC.checkForUpdates);
  },

  installUpdate: (): void => {
    ipcRenderer.send(IPC.installUpdate);
  },

  onUpdateChanged: (cb: (state: UpdateState) => void): (() => void) =>
    subscribe(IPC.updateChanged, cb),
};

contextBridge.exposeInMainWorld('desktop', api);
