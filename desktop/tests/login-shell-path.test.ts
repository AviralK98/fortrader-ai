/**
 * A .app launched from Finder inherits LaunchServices' PATH, not the
 * user's. Claude Code installs to ~/.local/bin, which only a shell
 * profile puts on PATH, so without this the app tells a user who has
 * Claude Code installed that they do not.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const execFileSync = vi.hoisted(() => vi.fn());

vi.mock('node:child_process', () => ({ execFileSync }));
vi.mock('../main/logging', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

const { applyLoginShellPath, readLoginShellPath } = await import(
  '../main/login-shell-path'
);

const START = '__FORTRADER_PATH_START__';
const END = '__FORTRADER_PATH_END__';

const wrap = (value: string, noise = '') => `${noise}${START}${value}${END}`;

let path: string | undefined;
let shell: string | undefined;

beforeEach(() => {
  path = process.env.PATH;
  shell = process.env.SHELL;
  process.env.SHELL = '/bin/zsh';
  execFileSync.mockReset();
});

afterEach(() => {
  process.env.PATH = path;
  process.env.SHELL = shell;
});

describe('readLoginShellPath', () => {
  it('extracts the value from between the sentinels', () => {
    execFileSync.mockReturnValue(wrap('/a:/b'));

    expect(readLoginShellPath('darwin')).toBe('/a:/b');
  });

  it('ignores whatever the profile printed first', () => {
    // Real shells emit version-manager banners and session restores on
    // the same stdout; this one is taken from an actual machine.
    execFileSync.mockReturnValue(
      wrap('/a:/b', 'Restored session: Fri  4 Sep 2026 01:04:39 BST\n'),
    );

    expect(readLoginShellPath('darwin')).toBe('/a:/b');
  });

  it('returns null rather than throwing when the shell fails', () => {
    execFileSync.mockImplementation(() => {
      throw new Error('profile exploded');
    });

    expect(readLoginShellPath('darwin')).toBeNull();
  });

  it('returns null when the sentinels are absent', () => {
    execFileSync.mockReturnValue('no markers here');

    expect(readLoginShellPath('darwin')).toBeNull();
  });

  it('returns null when SHELL is unset', () => {
    delete process.env.SHELL;

    expect(readLoginShellPath('darwin')).toBeNull();
    expect(execFileSync).not.toHaveBeenCalled();
  });

  it('does not run a shell on Windows', () => {
    // A GUI process there already inherits the user and machine PATH
    // from the registry, and -lic would be meaningless to cmd.exe.
    execFileSync.mockReturnValue(wrap('/a:/b'));

    expect(readLoginShellPath('win32')).toBeNull();
    expect(execFileSync).not.toHaveBeenCalled();
  });
});

describe('applyLoginShellPath', () => {
  it('appends entries the app did not already have', () => {
    process.env.PATH = '/usr/bin:/bin';
    execFileSync.mockReturnValue(wrap('/home/u/.local/bin:/usr/bin'));

    applyLoginShellPath('darwin');

    expect(process.env.PATH).toBe('/usr/bin:/bin:/home/u/.local/bin');
  });

  it('keeps the inherited PATH first so no name is redirected', () => {
    // A packaged build may be launched with entries pointing at its own
    // resources; the shell must widen the search, never reorder it.
    process.env.PATH = '/app/resources/bin:/usr/bin';
    execFileSync.mockReturnValue(wrap('/usr/bin:/opt/homebrew/bin'));

    applyLoginShellPath('darwin');

    expect(process.env.PATH).toBe(
      '/app/resources/bin:/usr/bin:/opt/homebrew/bin',
    );
  });

  it('does not duplicate an entry that is already present', () => {
    process.env.PATH = '/usr/bin:/bin';
    execFileSync.mockReturnValue(wrap('/bin:/usr/bin'));

    applyLoginShellPath('darwin');

    expect(process.env.PATH).toBe('/usr/bin:/bin');
  });

  it('leaves PATH untouched when the shell cannot be read', () => {
    process.env.PATH = '/usr/bin:/bin';
    execFileSync.mockImplementation(() => {
      throw new Error('nope');
    });

    applyLoginShellPath('darwin');

    expect(process.env.PATH).toBe('/usr/bin:/bin');
  });

  it('leaves PATH untouched on Windows', () => {
    process.env.PATH = 'C:\\Windows\\system32';
    execFileSync.mockReturnValue(wrap('/a:/b'));

    applyLoginShellPath('win32');

    expect(process.env.PATH).toBe('C:\\Windows\\system32');
  });
});
