/// <reference types="vite/client" />

import type { DesktopApi } from '../../shared/types';

declare global {
  interface Window {
    /** Exposed by preload via contextBridge. */
    desktop: DesktopApi;
  }
}

export {};
