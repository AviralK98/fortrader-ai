# Security

This application sits next to a funded brokerage account. The rules below
are not aspirational.

## No execution capability

The application cannot place, modify or close a trade.

This is enforced structurally rather than by a flag:

- `FortradeDataSource` declares no write method. A test asserts that no
  method named `open_trade`, `close_trade`, `place_order`, `buy`, `sell` or
  similar exists on the interface.
- The public API is read-only apart from the explicitly simulated
  `/api/paper/` namespace, which opens and closes **paper** positions. A
  test asserts against the generated OpenAPI document that no
  order-shaped route exists outside that namespace, and that every other
  `/api/` route is GET-only.
- The backend has no outbound channel to Fortrade at all — the desktop
  shell pushes data *in*. A test asserts no Fortrade hostname appears
  anywhere under `backend/`, so a paper trade structurally cannot become
  a real one.
- The MCP bridge forwards reads. It has no tool that could reach order
  entry.
- `FORTRADER_TRADING_ENABLED` is not a way in — setting it raises at
  startup rather than enabling anything.

## Credentials

We never store the user's Fortrade username or password. There is no login
form in this application and no credential storage of any kind.

The user logs in through the real Web Fortrader interface inside the
embedded view. Chromium persists the session in the `persist:fortrade`
partition under Electron's user-data directory, exactly as a browser would.

## Log redaction

Session material must never reach a log file.

Redaction is implemented as a logging **filter** in Python
(`backend/logging_setup.py`) and as the only emit path in TypeScript
(`desktop/main/logging.ts`), so it cannot be bypassed by a caller who
forgets to sanitise.

Two rule families:

- **Bare secrets** — JWT triples and `Bearer` tokens are replaced outright.
  These run first, so a secret is never left behind by a rule that only
  rewrites its label.
- **Key/value pairs** — `cookie`, `authorization`, `token`, `password`,
  `api_key`, `session_id` and similar keep the key and lose the value.

Structured context is walked recursively; any key matching the sensitive
list is redacted whole.

Both implementations have direct unit tests asserting that known secret
shapes do not survive.

## Electron hardening

The embedded Fortrade view is treated as hostile input:

| Setting | Value | Why |
|---|---|---|
| `partition` | `persist:fortrade` | Isolated session and cookie jar |
| `contextIsolation` | `true` | No shared JS context |
| `nodeIntegration` | `false` | No Node in remote content |
| `nodeIntegrationInSubFrames` | `false` | Applies to embedded frames too |
| `sandbox` | `true` | OS-level renderer sandbox |
| `webSecurity` | `true` | Same-origin policy enforced |
| preload | **none** | No bridge exists into privileged code |

Additional controls:

- `setWindowOpenHandler` denies all popups; off-site links go to the
  system browser via `shell.openExternal`.
- `will-navigate` blocks navigation outside `fortrade.com` hosts, and
  requires HTTPS.
- `setPermissionRequestHandler` denies every permission request — camera,
  microphone, geolocation, notifications.
- `will-attach-webview` is blocked application-wide.

Our own renderer uses a preload that exposes a small, explicit API:
shell info, Fortrade view bounds and visibility, reload, and event
subscriptions. No filesystem, no shell, no arbitrary IPC.

## Content Security Policy

The renderer runs under a CSP injected by the main process.

Production is strict — `default-src 'self'`, no `unsafe-eval`,
`object-src 'none'`, `frame-src 'none'`, `base-uri 'none'`,
`form-action 'none'`; `connect-src` permits only loopback.

Development additionally allows the Vite dev server and the inline/eval
that HMR requires. This relaxation applies only when `app.isPackaged` is
false.

## Local network surface

The backend binds `127.0.0.1` only. It is never reachable off-machine.

Ingest routes require a random per-launch token supplied by the desktop
shell, so another local process cannot inject fabricated market data into
the analysis pipeline.

## Untrusted input handling

Everything read from Fortrade is validated before use. Pydantic models use
`extra="forbid"` and `frozen=True`; ingest payloads reject unknown fields
with `422`. IPC payloads from the renderer are shape-checked in
`desktop/main/ipc.ts` before reaching the view.

## What must never be committed

Enforced by `.gitignore`:

- `.env` and variants
- `fortrade_browser_profile/` and any `*_browser_profile/`
- Electron session partitions
- `*.sqlite3`, `data/`, `logs/`

The repository previously carried a 62 MB Chrome profile containing
`Cookies` and `Login Data` that was untracked but **not ignored** — one
`git add .` from being committed. That gap is closed. Nothing sensitive was
ever actually committed; verified against `git ls-files`.

## Demo account posture

The application displays the detected account type prominently. If an
account is detected as `LIVE`, analysis remains available but any future
trading-related functionality stays disabled.

No live execution is implemented, and none should be added without a
separate, deliberate design review.
