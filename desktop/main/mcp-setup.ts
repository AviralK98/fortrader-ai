/**
 * Generates the Claude Code MCP entry for *this* machine.
 *
 * A friend who ran the installer has no Python and no source tree, so the
 * bridge must be the backend executable that ships inside the app,
 * invoked with `--mcp`. The path differs per machine and per install
 * location, so it is resolved at runtime rather than documented.
 *
 * The config is never written without an explicit action from the user.
 * Silently editing someone's Claude configuration is not acceptable, and
 * the write path preserves any servers they already have.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { app } from 'electron';

import type { McpSetup } from '../shared/types';
import { SIDECAR_EXECUTABLE } from './backend-process';
import { createLogger } from './logging';

const log = createLogger('mcp-setup');

const SERVER_NAME = 'fortrader-ai';

/**
 * `python` on macOS and Linux is often absent or Python 2; `python3` is
 * the reliable name. Windows ships the `python` launcher.
 */
function defaultPythonCommand(): string {
  return process.platform === 'win32' ? 'python' : 'python3';
}

export function resolveMcpSetup(): McpSetup {
  const packaged = app.isPackaged;

  const command = packaged
    ? join(process.resourcesPath, 'backend', SIDECAR_EXECUTABLE)
    : (process.env.FORTRADER_PYTHON ?? defaultPythonCommand());

  const args = packaged ? ['--mcp'] : ['-m', 'backend.main', '--mcp'];

  const cwd = packaged ? undefined : join(app.getAppPath(), '..');

  const entry: Record<string, unknown> = {
    type: 'stdio',
    command,
    args,
  };

  if (cwd) entry.cwd = cwd;

  const configJson = JSON.stringify(
    { mcpServers: { [SERVER_NAME]: entry } },
    null,
    2,
  );

  return {
    command,
    args,
    cwd,
    configJson,
    configPath: claudeConfigPath(),
    packaged,
  };
}

function claudeConfigPath(): string {
  return join(app.getPath('home'), '.claude.json');
}

/**
 * Merge our entry into the user's Claude config.
 *
 * Reads what is there, adds or replaces only our own server, and writes
 * the whole file back. Other servers are left exactly as they were.
 */
export function writeMcpConfig(): {
  written: boolean;
  path: string;
  detail?: string;
} {
  const setup = resolveMcpSetup();
  const path = setup.configPath;

  try {
    let config: Record<string, unknown> = {};

    if (existsSync(path)) {
      const raw = readFileSync(path, 'utf8').trim();

      if (raw) {
        try {
          config = JSON.parse(raw) as Record<string, unknown>;
        } catch {
          // Refuse rather than overwrite a file we cannot parse; it may
          // hold configuration the user cares about.
          return {
            written: false,
            path,
            detail:
              'Existing Claude config is not valid JSON. Copy the entry in ' +
              'manually rather than risk overwriting it.',
          };
        }
      }
    }

    const servers =
      (config.mcpServers as Record<string, unknown> | undefined) ?? {};

    const parsed = JSON.parse(setup.configJson) as {
      mcpServers: Record<string, unknown>;
    };

    config.mcpServers = { ...servers, [SERVER_NAME]: parsed.mcpServers[SERVER_NAME] };

    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${JSON.stringify(config, null, 2)}\n`, 'utf8');

    log.info('Wrote MCP entry to Claude config', { path });

    return { written: true, path };
  } catch (error) {
    log.error('Could not write Claude config', { error: String(error) });

    return { written: false, path, detail: String(error) };
  }
}
