import { describe, expect, it, vi } from 'vitest';

import { AppStateMachine } from '../main/app-state';

describe('AppStateMachine', () => {
  it('starts in STARTING', () => {
    expect(new AppStateMachine().current).toBe('STARTING');
  });

  it('notifies subscribers on change', () => {
    const machine = new AppStateMachine();
    const listener = vi.fn();

    machine.subscribe(listener);
    machine.set('CONNECTED', 'all good');

    expect(listener).toHaveBeenCalledWith('CONNECTED', 'all good');
  });

  it('does not re-notify for an identical transition', () => {
    const machine = new AppStateMachine();
    const listener = vi.fn();

    machine.subscribe(listener);

    machine.set('CONNECTED');
    machine.set('CONNECTED');

    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('notifies again when only the detail changes', () => {
    const machine = new AppStateMachine();
    const listener = vi.fn();

    machine.subscribe(listener);

    machine.set('BACKEND_ERROR', 'first');
    machine.set('BACKEND_ERROR', 'second');

    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('stops notifying after unsubscribe', () => {
    const machine = new AppStateMachine();
    const listener = vi.fn();

    const unsubscribe = machine.subscribe(listener);
    unsubscribe();

    machine.set('DISCONNECTED');

    expect(listener).not.toHaveBeenCalled();
  });

  describe('applyFortradeUrl', () => {
    it('reports loading while the page is in flight', () => {
      const machine = new AppStateMachine();

      machine.applyFortradeUrl('https://ready.fortrade.com/', true);

      expect(machine.current).toBe('FORTRADE_LOADING');
    });

    it.each([
      'https://ready.fortrade.com/login',
      'https://ready.fortrade.com/en/signin',
      'https://ready.fortrade.com/auth/callback',
    ])('detects the login surface at %s', (url) => {
      const machine = new AppStateMachine();

      machine.applyFortradeUrl(url, false);

      expect(machine.current).toBe('AUTH_REQUIRED');
    });

    it('does not claim CONNECTED from a URL alone', () => {
      // A trading URL is not proof the session works; only extraction is.
      const machine = new AppStateMachine();

      machine.applyFortradeUrl('https://ready.fortrade.com/trading', false);

      expect(machine.current).not.toBe('CONNECTED');
    });
  });
});
