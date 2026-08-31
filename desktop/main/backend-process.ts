/**
 * Supervises the Python backend sidecar.
 *
 * The user never starts this themselves. In development it runs the
 * `backend` package with the local interpreter; in a packaged build it runs
 * the PyInstaller-produced `fortrader-backend.exe` shipped in resources.
 */

import { spawn, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { app } from 'electron';

import { createLogger } from './logging';

const log = createLogger('backend');

const DEFAULT_PORT = 8756;
const HOST = '127.0.0.1';

/** How long to wait for the port to answer before declaring failure. */
const READY_TIMEOUT_MS = 30_000;
const POLL_INTERVAL_MS = 250;

const MAX_RESTARTS = 3;
const RESTART_BACKOFF_MS = 2_000;

export interface BackendHandle {
  url: string;
  token: string;
}

export class BackendProcess {
  private child: ChildProcess | null = null;
  private restarts = 0;
  private stopping = false;

  readonly port = Number(process.env.FORTRADER_PORT ?? DEFAULT_PORT);
  readonly url = `http://${HOST}:${this.port}`;

  /** Shared secret authenticating ingest calls from this process only. */
  readonly token = randomBytes(32).toString('base64url');

  private readonly dataDir = join(app.getPath('userData'), 'data');

  constructor(private readonly onLog: (line: string) => void) {}

  async start(): Promise<BackendHandle> {
    this.spawnChild();

    await this.waitForReady();

    this.writeRuntimeFile();

    log.info('Backend ready', { url: this.url });

    return { url: this.url, token: this.token };
  }

  private spawnChild(): void {
    const { command, args, cwd } = this.resolveCommand();

    log.info('Starting backend', { command, args, cwd });

    this.child = spawn(command, args, {
      cwd,
      env: {
        ...process.env,
        FORTRADER_HOST: HOST,
        FORTRADER_PORT: String(this.port),
        FORTRADER_DATA_DIR: this.dataDir,
        FORTRADER_INGEST_TOKEN: this.token,
        PYTHONUNBUFFERED: '1',
        PYTHONIOENCODING: 'utf-8',
      },
      // Never a shell: arguments must not be re-parsed.
      shell: false,
      windowsHide: true,
    });

    this.child.stdout?.on('data', (chunk: Buffer) => {
      this.onLog(chunk.toString('utf8').trimEnd());
    });

    this.child.stderr?.on('data', (chunk: Buffer) => {
      this.onLog(chunk.toString('utf8').trimEnd());
    });

    this.child.on('exit', (code, signal) => {
      if (this.stopping) return;

      log.error('Backend exited unexpectedly', { code, signal });

      if (this.restarts < MAX_RESTARTS) {
        this.restarts += 1;

        log.info('Restarting backend', {
          attempt: this.restarts,
          of: MAX_RESTARTS,
        });

        setTimeout(() => this.spawnChild(), RESTART_BACKOFF_MS);
      } else {
        log.error('Backend restart limit reached; giving up');
      }
    });

    this.child.on('error', (error) => {
      log.error('Backend failed to spawn', { error: String(error) });
    });
  }

  private resolveCommand(): {
    command: string;
    args: string[];
    cwd: string;
  } {
    if (app.isPackaged) {
      // PyInstaller sidecar shipped alongside the app (Phase K).
      const exe = join(process.resourcesPath, 'backend', 'fortrader-backend.exe');

      return { command: exe, args: [], cwd: process.resourcesPath };
    }

    const repoRoot = join(app.getAppPath(), '..');
    const python = process.env.FORTRADER_PYTHON ?? 'python';

    return {
      command: python,
      args: ['-m', 'backend.main'],
      cwd: repoRoot,
    };
  }

  /** Poll /health until it answers, rather than guessing with a sleep. */
  private async waitForReady(): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS;

    while (Date.now() < deadline) {
      if (this.child?.exitCode !== null && this.child?.exitCode !== undefined) {
        throw new Error(
          `Backend exited during startup with code ${this.child.exitCode}`,
        );
      }

      try {
        const response = await fetch(`${this.url}/health`, {
          signal: AbortSignal.timeout(1_000),
        });

        if (response.ok) return;
      } catch {
        // Not listening yet — expected during startup.
      }

      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }

    throw new Error(
      `Backend did not become ready within ${READY_TIMEOUT_MS}ms`,
    );
  }

  /**
   * Publishes the live URL so the MCP stdio bridge can find this instance
   * without the user configuring a port. Removed on shutdown, so a stale
   * file never makes the bridge think the app is running.
   */
  private writeRuntimeFile(): void {
    try {
      mkdirSync(this.dataDir, { recursive: true });

      writeFileSync(
        this.runtimeFilePath,
        JSON.stringify({ url: this.url, pid: process.pid }, null, 2),
        'utf8',
      );
    } catch (error) {
      log.warn('Could not write runtime file', { error: String(error) });
    }
  }

  private get runtimeFilePath(): string {
    return join(this.dataDir, 'runtime.json');
  }

  async postState(state: string, detail?: string): Promise<void> {
    try {
      await fetch(`${this.url}/internal/state`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Ingest-Token': this.token,
        },
        body: JSON.stringify({ state, detail: detail ?? null }),
        signal: AbortSignal.timeout(2_000),
      });
    } catch (error) {
      log.debug('Could not post state', { error: String(error) });
    }
  }

  stop(): void {
    this.stopping = true;

    if (existsSync(this.runtimeFilePath)) {
      try {
        rmSync(this.runtimeFilePath);
      } catch {
        // Best effort.
      }
    }

    if (this.child && this.child.exitCode === null) {
      log.info('Stopping backend');
      this.child.kill();
    }

    this.child = null;
  }
}
