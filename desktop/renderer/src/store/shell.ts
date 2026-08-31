/**
 * Shell state fed by main-process IPC events.
 *
 * Kept separate from server state (which TanStack Query owns) because it
 * arrives by push, not by fetch.
 */

import { create } from 'zustand';

import type { AppStateValue, FortradeViewState, ShellInfo } from '../../../shared/types';

interface ShellStore {
  appState: AppStateValue;
  detail: string | null;
  fortrade: FortradeViewState;
  info: ShellInfo | null;

  setAppState: (state: AppStateValue, detail: string | null) => void;
  setFortrade: (state: FortradeViewState) => void;
  setInfo: (info: ShellInfo) => void;
}

export const useShellStore = create<ShellStore>((set) => ({
  appState: 'STARTING',
  detail: null,
  fortrade: { url: '', loading: true, authenticated: false },
  info: null,

  setAppState: (appState, detail) => set({ appState, detail }),
  setFortrade: (fortrade) => set({ fortrade }),
  setInfo: (info) => set({ info }),
}));

/** Subscribes to main-process events. Returns an unsubscribe function. */
export function connectShellEvents(): () => void {
  const store = useShellStore.getState();

  const offState = window.desktop.onStateChanged((state, detail) => {
    useShellStore.getState().setAppState(state, detail);
  });

  const offView = window.desktop.onFortradeViewChanged((state) => {
    useShellStore.getState().setFortrade(state);
  });

  void window.desktop.getShellInfo().then(store.setInfo);

  return () => {
    offState();
    offView();
  };
}
