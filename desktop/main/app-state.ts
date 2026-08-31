/**
 * Owns the application state machine in the main process.
 *
 * State is explicit and pushed to both the backend and the UI, so the
 * status strip never has to infer liveness from whether a request happened
 * to succeed.
 */

import type { AppStateValue } from '../shared/types';
import { createLogger } from './logging';

const log = createLogger('app-state');

type Listener = (state: AppStateValue, detail: string | null) => void;

export class AppStateMachine {
  private state: AppStateValue = 'STARTING';
  private detail: string | null = null;

  private readonly listeners = new Set<Listener>();

  get current(): AppStateValue {
    return this.state;
  }

  get currentDetail(): string | null {
    return this.detail;
  }

  set(state: AppStateValue, detail: string | null = null): void {
    if (this.state === state && this.detail === detail) return;

    log.info('State changed', { from: this.state, to: state, detail });

    this.state = state;
    this.detail = detail;

    for (const listener of this.listeners) {
      listener(state, detail);
    }
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);

    return () => this.listeners.delete(listener);
  }

  /**
   * Classify the Fortrade view's location into an application state.
   *
   * Phase B only distinguishes loading from loaded. Reliable detection of
   * the authenticated trading UI arrives in Phase C, where extraction
   * confirms the account panel is actually present — a URL alone is not
   * proof of a working session.
   */
  applyFortradeUrl(url: string, loading: boolean): void {
    if (loading) {
      this.set('FORTRADE_LOADING');
      return;
    }

    const isLoginSurface = /login|signin|sign-in|auth/i.test(url);

    this.set(isLoginSurface ? 'AUTH_REQUIRED' : 'FORTRADE_LOADING');
  }
}
