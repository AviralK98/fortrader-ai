/**
 * Gives the app the PATH the user actually has.
 *
 * A .app launched from Finder inherits its environment from
 * LaunchServices, which never sources .zshrc, .bash_profile or any other
 * interactive profile. So the PATH inside the app is not the PATH in the
 * user's terminal, and anything installed to a directory that a profile
 * adds is invisible.
 *
 * Claude Code is exactly that case. Its installer puts the binary in
 * ~/.local/bin, which reaches PATH through the shell profile, so the
 * backend's `shutil.which("claude")` returns None and the app tells a
 * user with Claude Code installed that Claude Code is not installed.
 *
 * The fix is to ask the login shell what its PATH is and adopt it.
 * Windows is skipped: a GUI process there already inherits the user and
 * machine PATH from the registry, so there is nothing to recover.
 */

import { execFileSync } from 'node:child_process';

import { createLogger } from './logging';

const log = createLogger('login-shell-path');

/**
 * An interactive shell prints whatever the user's profile prints --
 * version managers, shell greetings, "Restored session:" -- onto the
 * same stdout. Delimiting the value is what separates it from that
 * noise; parsing the last line instead would break on any profile that
 * ends with a blank one.
 */
const START = '__FORTRADER_PATH_START__';
const END = '__FORTRADER_PATH_END__';

/** A profile that hangs must not hang the app's startup with it. */
const TIMEOUT_MS = 5_000;

/**
 * Ask the user's login shell for its PATH.
 *
 * Returns null when there is nothing to recover or the shell could not
 * be asked -- never throws, because failing to widen PATH degrades one
 * optional feature and must not stop the app from starting.
 */
export function readLoginShellPath(): string | null {
  if (process.platform === 'win32') return null;

  const shell = process.env.SHELL;

  if (!shell) return null;

  // -l -i: the PATH lines live in profiles that only one or the other
  // sources, and which is which varies by shell and by user. `command`
  // resolves to the builtin even if the profile defined a function
  // named printf.
  const script = `command printf '%s%s%s' '${START}' "$PATH" '${END}'`;

  try {
    const out = execFileSync(shell, ['-lic', script], {
      encoding: 'utf8',
      timeout: TIMEOUT_MS,
      // A profile that reads from stdin would otherwise block forever.
      stdio: ['ignore', 'pipe', 'ignore'],
    });

    const start = out.indexOf(START);
    const end = out.indexOf(END, start + START.length);

    if (start === -1 || end === -1) return null;

    const value = out.slice(start + START.length, end).trim();

    return value.length > 0 ? value : null;
  } catch (error) {
    log.warn('Could not read the login shell PATH', {
      shell,
      error: String(error),
    });

    return null;
  }
}

/**
 * Merge the login shell's PATH into this process's own.
 *
 * The inherited PATH is kept and kept first: it is what the app was
 * actually launched with, and on a packaged build it may point at
 * resources the shell knows nothing about. The shell's entries are
 * appended, so this can only ever widen the search, never redirect an
 * existing name to a different binary.
 *
 * Mutates process.env.PATH, which every later child inherits -- the
 * backend sidecar spawns with `...process.env`, so it picks this up
 * without knowing the function exists.
 */
export function applyLoginShellPath(): void {
  const fromShell = readLoginShellPath();

  if (fromShell === null) return;

  const current = process.env.PATH ?? '';
  const seen = new Set(current.split(':').filter(Boolean));
  const added = fromShell
    .split(':')
    .filter((entry) => entry.length > 0 && !seen.has(entry));

  if (added.length === 0) return;

  process.env.PATH = current ? `${current}:${added.join(':')}` : added.join(':');

  log.info('Widened PATH from the login shell', { added });
}
