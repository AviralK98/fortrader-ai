/**
 * Application auto-update.
 *
 * Updates are fetched from GitHub Releases and verified against the
 * SHA512 recorded in the release manifest before anything is applied.
 *
 * Two deliberate restraints, because this machine holds a live brokerage
 * session:
 *
 * 1. **Never restart on its own.** An update is downloaded quietly and
 *    then waits. Relaunching mid-session would drop the Fortrade view
 *    while the user is reading analysis or watching a paper position.
 * 2. **Never update in development.** `electron-updater` would otherwise
 *    try to replace a source checkout.
 *
 * Honest limitation: the build is unsigned, so the checksum proves the
 * download was not corrupted or altered in transit, but nothing proves
 * *who* published it. Whoever controls the release host can ship code to
 * every installed copy. That is an acceptable trade for a small trusted
 * group and is not acceptable for public distribution — see
 * docs/security.md.
 */

import { app } from 'electron';
import { autoUpdater } from 'electron-updater';

import type { UpdateState } from '../shared/types';
import { createLogger } from './logging';

const log = createLogger('updater');

/** Re-check while the app stays open for days at a time. */
const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

export class Updater {
  private state: UpdateState = { status: 'idle' };
  private timer: NodeJS.Timeout | null = null;

  constructor(private readonly onChange: (state: UpdateState) => void) {}

  start(): void {
    if (!app.isPackaged) {
      log.info('Update checks disabled in development');
      this.set({ status: 'disabled', detail: 'Development build' });
      return;
    }

    autoUpdater.autoDownload = true;
    // The user chooses the moment; see the restraint above.
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.logger = null;

    autoUpdater.on('checking-for-update', () => {
      this.set({ status: 'checking' });
    });

    autoUpdater.on('update-not-available', () => {
      this.set({ status: 'current', version: app.getVersion() });
    });

    autoUpdater.on('update-available', (info) => {
      log.info('Update available', { version: info.version });
      this.set({ status: 'downloading', version: info.version, percent: 0 });
    });

    autoUpdater.on('download-progress', (progress) => {
      this.set({
        status: 'downloading',
        version: this.state.version,
        percent: Math.round(progress.percent),
      });
    });

    autoUpdater.on('update-downloaded', (info) => {
      log.info('Update ready', { version: info.version });
      this.set({ status: 'ready', version: info.version });
    });

    autoUpdater.on('error', (error) => {
      // A failed update check must never be fatal. The application is
      // still perfectly usable on the version already installed.
      log.warn('Update check failed', { error: String(error) });
      this.set({ status: 'error', detail: String(error) });
    });

    void this.check();

    this.timer = setInterval(() => void this.check(), CHECK_INTERVAL_MS);
  }

  async check(): Promise<void> {
    if (!app.isPackaged) return;

    try {
      await autoUpdater.checkForUpdates();
    } catch (error) {
      log.warn('Update check threw', { error: String(error) });
    }
  }

  /** Quit and install. Only ever called from an explicit user action. */
  install(): void {
    if (this.state.status !== 'ready') return;

    log.info('Installing update on user request');
    autoUpdater.quitAndInstall(false, true);
  }

  current(): UpdateState {
    return this.state;
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private set(state: UpdateState): void {
    this.state = state;
    this.onChange(state);
  }
}
