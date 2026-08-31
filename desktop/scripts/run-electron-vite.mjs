#!/usr/bin/env node
/**
 * Launches electron-vite with a sanitised environment.
 *
 * Terminals hosted inside Electron-based editors (VS Code, Cursor and the
 * Claude Code extension among them) export `ELECTRON_RUN_AS_NODE=1`. Any
 * Electron process spawned from such a terminal then boots as plain Node,
 * where `require('electron')` yields the path string to the binary rather
 * than the Electron API — producing a baffling
 * `Cannot read properties of undefined (reading 'isPackaged')`.
 *
 * Stripping the variable here means `npm run dev` behaves identically from
 * an editor terminal and a standalone one.
 */

import { spawn } from 'node:child_process';

const env = { ...process.env };

const STRIPPED = ['ELECTRON_RUN_AS_NODE', 'ELECTRON_NO_ATTACH_CONSOLE'];

for (const key of STRIPPED) {
  if (key in env) {
    console.warn(`[dev] Unsetting ${key} so Electron starts as Electron.`);
    delete env[key];
  }
}

const args = process.argv.slice(2);

const child = spawn('electron-vite', args, {
  env,
  stdio: 'inherit',
  // electron-vite is a shell shim (.cmd) on Windows.
  shell: process.platform === 'win32',
});

child.on('exit', (code, signal) => {
  process.exit(signal ? 1 : (code ?? 0));
});

child.on('error', (error) => {
  console.error('[dev] Failed to start electron-vite:', error.message);
  process.exit(1);
});
