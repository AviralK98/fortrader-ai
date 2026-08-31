# Development

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20+ | 24 LTS in use |
| Python | 3.10+ | 3.10.5 in use |
| Git | any | |

## Setup

```bash
npm install
python -m pip install -r requirements-dev.txt
```

`npm install` may report that Electron's install script is not approved.
The approval is already recorded in the root `package.json` under
`allowScripts`. If `node_modules/electron/dist/electron.exe` is missing,
run:

```bash
node node_modules/electron/install.js
```

## Running

```bash
npm run dev
```

That single command:

1. builds main, preload and renderer through electron-vite
2. starts the Electron app
3. spawns the Python backend automatically and waits for `/health`
4. loads Web Fortrader in the embedded view

No external Chrome, no debugging port, no separately started Python.

### The `ELECTRON_RUN_AS_NODE` trap

Terminals hosted inside Electron-based editors — VS Code, Cursor, the
Claude Code extension — export `ELECTRON_RUN_AS_NODE=1`. Any Electron
process spawned from such a terminal boots as plain Node, where
`require('electron')` returns the path to the binary instead of the API.
The symptom is:

```
TypeError: Cannot read properties of undefined (reading 'isPackaged')
```

`desktop/scripts/run-electron-vite.mjs` strips the variable before
launching, so `npm run dev` behaves the same from any terminal. If you
invoke `electron-vite` directly, unset it yourself.

## Discovering Fortrade's DOM

When Fortrade changes its markup, extraction tests fail. To find the new
structure, run the probe:

```bash
FORTRADER_DUMP_DOM=1 FORTRADER_DUMP_DOM_PATH=./dom-probe.json npm run dev
```

It runs a strictly read-only script inside our own Fortrade view — the
exact Chromium we ship, with the real session — and writes a structural
report: the markup around known labels, every `data-*` attribute in use,
watchlist row subtrees, and the positions region.

Update the selectors in `desktop/main/extraction/fortrade-script.ts`, then
update `desktop/tests/fixtures/fortrade-dom.ts` to match so the regression
tests cover the new shape.

Selectors currently in use, all discovered this way:

| Data | Selector |
|---|---|
| Balance / Equity / P&L | `.footerBalance` · `.footerEquity` · `.footerPnl` |
| Margins | `#footerUsedMargin` · `.footerAvailableMargin` |
| Quote row | `.instrument` (symbol in `.symbolName`) |
| Bid / ask | `.sellValue` + `.sellValueBig`, `.buyValue` + `.buyValueBig` |
| Spread | `.spread` |
| Chart tab | `.chartSymbolTab`, active marked `clicked`, `.timeframe` child |
| Position count | `.openPositionsCount` |
| Account type | `[data-nav="switchtoreal"]` implies DEMO |

Prices are rendered split across two elements — `.sellValue` holds
`1.352` and `.sellValueBig` holds `84` — so they are concatenated before
parsing. Chart tab labels concatenate with no separator (`GBP/USDM1`), so
the timeframe is removed as a suffix rather than matched mid-string.

To capture our renderer without fighting window z-order:

```bash
FORTRADER_CAPTURE_UI=./ui.png npm run dev
```

## Observing network traffic

To re-examine what the session receives (for example if the chart endpoint
changes shape):

```bash
FORTRADER_DUMP_NET=1 FORTRADER_DUMP_NET_PATH=./net-probe.json \
  FORTRADER_DUMP_NET_SECONDS=60 npm run dev
```

Passive only — it records metadata and bodies for traffic the page itself
requested, with credential redaction applied before anything is written.

Note that only one client may hold `webContents.debugger`, so enabling the
probe **disables candle capture for that run**. The app logs this.

## Checks

```bash
npm run check          # everything

npm run typecheck      # tsc --build, strict
npm run lint           # eslint, zero warnings
npm run test           # vitest
npm run typecheck:py   # mypy strict
npm run lint:py        # ruff
npm run test:py        # pytest
```

The Python suite runs entirely against fixtures in `tests/fixtures/`. It
never contacts Fortrade and never needs an account.

## Building the Windows installer

```powershell
npm run package:all
```

Runs three stages in order — PyInstaller bundles the backend, electron-vite
compiles the app, electron-builder packs both — and produces
`release/Fortrader AI Setup <version>.exe`.

The script smoke-tests the sidecar between stages. A bundle that builds but
cannot start is worse than a build failure, because it only surfaces on the
user's machine.

### Icon

`fortrader-ai.ico` at the repository root is the single source of truth —
referenced directly by `electron-builder.yml` rather than copied into
`build/`, so the two cannot drift. It supplies the executable icon, the
Start Menu and desktop shortcuts, and the installer and uninstaller.

It must keep a 256×256 frame; electron-builder rejects anything smaller.

In development there is no packaged executable to carry an icon, so
`main.ts` sets the window icon from that same file. Packaged builds take
it from the exe and need no such handling.

### What ships

| | |
|---|---|
| Installer | ~133 MB, NSIS, per-user (no admin prompt) |
| Sidecar | `resources/backend/fortrader-backend.exe` + `_internal/` |
| End-user requirements | **None** — no Python, no Node |

The sidecar is a PyInstaller *one-directory* bundle, not one-file: a
one-file build unpacks pandas and numpy to a temp directory on every
launch, adding seconds to each startup. The installer hides the directory
either way.

`electron` is pinned to an exact version in `desktop/package.json`.
electron-builder downloads platform binaries for a specific release and
cannot resolve a range.

### Two things to know

**The installer is unsigned.** Windows SmartScreen will warn on first run
until it is signed with a real code-signing certificate. Set `CSC_LINK`
and `CSC_KEY_PASSWORD` before building to sign it.

Signing is the only part of this project that costs money, and it is
optional — the app builds, installs, updates and runs without it. Users
click "More info → Run anyway" once per install.

If the repository is public, free certificates are available to open
source projects (SignPath Foundation is the usual route; verify their
current eligibility terms). Certum sells low-cost open-source
certificates. A self-signed certificate is **not** a substitute — Windows
does not trust it, so it removes no warning.

**Development and installed builds share one data directory.** Electron
derives it from the package `name`, so both use
`%APPDATA%\fortrader-ai-desktop` rather than `%APPDATA%\Fortrader AI`.

That is left as-is deliberately: it means an installed build inherits the
Fortrade session, captured candles and paper record already collected in
development, and candle history is expensive to re-collect. The
consequences are that the folder name is the npm package name rather than
the product name, and that **a development and an installed instance
cannot run at the same time** — they contend for the same SQLite file and
port 8756.

To switch to a product-named directory, call `app.setName('Fortrader AI')`
before `app.whenReady()` in `desktop/main/main.ts` and rename the existing
folder, or the old data is orphaned.

## Shipping an update to users

Installed copies check GitHub Releases on launch and every six hours, and
apply nothing without the user pressing **Restart & update**.

Releases are built by GitHub Actions, so shipping is two commands:

```bash
# 1. Bump "version" in desktop/package.json, commit it.

# 2. Tag and push. The tag must match that version — the workflow
#    fails fast if it does not, because electron-updater compares
#    against package.json rather than the tag.
git tag v0.2.0
git push origin v0.2.0
```

`.github/workflows/release.yml` then runs the full test suite, builds the
sidecar, smoke-tests it, checks the MCP bridge answers, builds the
installer, and publishes both the `.exe` and `latest.yml` to a GitHub
release. Without `latest.yml` no existing client can discover the update,
which is why it is published automatically rather than by hand.

Users get it within six hours, or on their next launch. The Python backend
ships inside the app, so it updates too — there is no second mechanism.

To build locally instead (for testing, or without CI):

```powershell
npm run package:all
```

### Continuous integration

`.github/workflows/ci.yml` runs the same checks on every push and pull
request, without building an installer. Both workflows run on
`windows-latest` and cost nothing on GitHub's free tier.

One thing worth knowing: **`npm ci` does not install the Electron
binary.** npm's allow-scripts gate skips the lifecycle script, so both
workflows re-run `node node_modules/electron/install.js` when the binary
is absent. Without that step, `electron-builder` fails with a confusing
error. This was verified, not assumed.

### What the update channel does and does not protect

`electron-updater` verifies the download against the SHA512 recorded in
`latest.yml`, so a corrupted or altered file is rejected.

It does **not** prove who published it. The build is unsigned, so anyone
who gains write access to this repository's releases can ship code to
every installed copy — on machines holding a live brokerage session. For a
small group of people who know you, that is a considered trade. For public
distribution it is not: sign the build first (`CSC_LINK`,
`CSC_KEY_PASSWORD`) and protect the release process.

## Giving the app to someone else

They need only the installer. No Python, no Node, no repository.

1. Send them `Fortrader AI Setup <version>.exe`.
2. They click through the SmartScreen warning — it is unsigned.
3. They log into **their own** Fortrade account in the embedded view. The
   session lives in their own Electron partition; nothing is shared, and
   no credentials are ever stored by the application.
4. For Claude Code: **Setup → Connect Claude Code** in the right-hand
   panel resolves the paths for their machine and offers to add the entry
   to their `.claude.json`. It merges, leaving their other servers alone,
   and they restart Claude Code afterwards.

The MCP bridge is the same executable as the backend, run with `--mcp`, so
an installed copy has everything it needs:

```
%LOCALAPPDATA%\Programs\Fortrader AI\resources\backend\fortrader-backend.exe --mcp
```

Each person's data — session, candles, signals, paper record — is entirely
local to their machine. Nothing is shared between installations.

## Layout

```
desktop/          Electron shell
  main/           lifecycle, Fortrade view, backend supervision, IPC
  preload/        contextBridge surface
  renderer/       React UI
  shared/         types shared across the IPC boundary
  tests/          vitest

backend/          Python analysis service
  fortrade/       models, parsers, source abstraction
  analysis/       indicators and scoring          (Phase E)
  signals/        signal engine                   (Phase F)
  backtest/       engine and metrics              (Phase H)
  paper/          simulated positions             (Phase I)
  storage/        SQLite and migrations
  api/            FastAPI routes and schemas

mcp_bridge/       stdio bridge for Claude Code
legacy/           preserved proof-of-concept scripts
tests/python/     pytest
docs/
```

`mcp_bridge/` is deliberately not named `mcp/`: the Python MCP SDK is
imported as `mcp`, and a top-level directory of that name would shadow it
whenever the repository root is on `sys.path`.

## Adding a migration

Append to `MIGRATIONS` in `backend/storage/migrations.py` with the next
version number. Never edit a migration that has shipped. Each runs in a
transaction and is recorded in `schema_migrations` on success.

## Conventions

Python is fully type-annotated and passes `mypy --strict`. TypeScript runs
under `strict` with `noUncheckedIndexedAccess`.

Keep the boundaries intact:

- Fortrade selectors stay in `backend/fortrade` and the extraction script
- analysis code sees only normalised models
- no Claude-specific logic in indicator calculations
- no parsing logic in the renderer

## Backend on its own

```bash
python -m backend.main
```

Serves on `127.0.0.1:8756`. Interactive docs at `/docs`. Ingest routes need
`X-Ingest-Token`; when the desktop shell is not supplying one the backend
generates a random token at startup, so ingest is unusable by accident —
which is intended.
