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

/**
 * macOS cannot install an update it cannot verify.
 *
 * electron-updater applies macOS updates through Squirrel.Mac, which
 * checks the running application's code signature before replacing it.
 * These builds are unsigned, so that check fails — and it fails *after*
 * the download has finished, which is the worst shape for it to take:
 * bandwidth spent, then an error the user can do nothing about.
 *
 * So macOS does not pretend to self-update. The release is read
 * directly, the user is told a newer version exists, and the download is
 * one click. Installing it is a drag to Applications, exactly as the
 * first install was. Signing the build with an Apple Developer ID is the
 * only thing that would change this.
 */
const CAN_SELF_INSTALL = process.platform !== 'darwin';

//: Must match the `publish` block in electron-builder.yml; a test keeps
//: the two honest, because a silent mismatch here means macOS checks a
//: repository that is not the one shipping the app.
const REPO_OWNER = 'AviralK98';
const REPO_NAME = 'fortrader-ai';

const LATEST_RELEASE_URL =
  `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest`;

const MANUAL_CHECK_TIMEOUT_MS = 15_000;

interface GithubRelease {
  tag_name?: string;
  assets?: { name: string; browser_download_url: string }[];
}

/** True when `candidate` is a later release than `current`. */
export function isNewerVersion(candidate: string, current: string): boolean {
  const parse = (v: string): number[] =>
    (
      v
        .replace(/^v/, '')
        // Drop any pre-release suffix; only the numeric core is compared.
        .split('-')[0] ?? ''
    )
      .split('.')
      .map((part) => Number.parseInt(part, 10) || 0);

  const a = parse(candidate);
  const b = parse(current);

  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const left = a[i] ?? 0;
    const right = b[i] ?? 0;

    if (left !== right) return left > right;
  }

  return false;
}

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

    if (!CAN_SELF_INSTALL) {
      void this.checkManually();

      this.timer = setInterval(
        () => void this.checkManually(),
        CHECK_INTERVAL_MS,
      );

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

    if (!CAN_SELF_INSTALL) {
      await this.checkManually();
      return;
    }

    try {
      await autoUpdater.checkForUpdates();
    } catch (error) {
      log.warn('Update check threw', { error: String(error) });
    }
  }

  /**
   * Read the published release directly, without Squirrel.
   *
   * Nothing is downloaded here. The point is to notice a new version and
   * hand the user a link, rather than fetching a disk image it has no
   * way to install.
   */
  private async checkManually(): Promise<void> {
    this.set({ status: 'checking' });

    try {
      const response = await fetch(LATEST_RELEASE_URL, {
        headers: { Accept: 'application/vnd.github+json' },
        signal: AbortSignal.timeout(MANUAL_CHECK_TIMEOUT_MS),
      });

      if (!response.ok) {
        throw new Error(`GitHub returned ${response.status}`);
      }

      const release = (await response.json()) as GithubRelease;
      const latest = (release.tag_name ?? '').replace(/^v/, '');

      if (!latest || !isNewerVersion(latest, app.getVersion())) {
        this.set({ status: 'current', version: app.getVersion() });
        return;
      }

      const image = release.assets?.find((asset) =>
        asset.name.endsWith('.dmg'),
      );

      if (!image) {
        // A release with no disk image is a release macOS cannot use.
        // Saying so beats offering a button that leads nowhere.
        log.warn('Release has no .dmg asset', { version: latest });
        this.set({
          status: 'error',
          detail: `Version ${latest} was published without a macOS download.`,
        });
        return;
      }

      log.info('Update available for manual install', { version: latest });

      this.set({
        status: 'manual',
        version: latest,
        downloadUrl: image.browser_download_url,
      });
    } catch (error) {
      // Being offline is not a problem worth interrupting anyone over.
      log.warn('Manual update check failed', { error: String(error) });
      this.set({ status: 'error', detail: String(error) });
    }
  }

  /** Quit and install. Only ever called from an explicit user action. */
  install(): void {
    // 'ready' is unreachable without self-install, but an IPC message is
    // not a trusted caller and quitAndInstall on an unsigned macOS build
    // would quit without installing anything.
    if (!CAN_SELF_INSTALL) return;

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
