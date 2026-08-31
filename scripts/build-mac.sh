#!/usr/bin/env bash
#
# Builds the macOS application.
#
#   chmod +x scripts/build-mac.sh
#   ./scripts/build-mac.sh
#
# Produces release/Fortrader AI-<version>-<arch>.dmg — the macOS
# equivalent of the Windows installer. Drag to Applications and run; no
# Python and no Node needed on the target machine.
#
# Must run on macOS: PyInstaller cannot cross-compile, so the sidecar has
# to be built on the platform and architecture it will run on.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || fail "This script must run on macOS. PyInstaller cannot cross-compile."

# Editor terminals export this; it makes Electron boot as plain Node.
unset ELECTRON_RUN_AS_NODE || true

python="${FORTRADER_PYTHON:-python3}"

command -v "$python" >/dev/null || fail "Python not found. Set FORTRADER_PYTHON or install python3."
command -v npm      >/dev/null || fail "npm not found. Install Node.js 20 or newer."
[[ -d node_modules ]]          || fail "node_modules missing. Run: npm install"

# PyInstaller builds for the host architecture only, so the Electron
# package must target the same one or the sidecar will not run.
case "$(uname -m)" in
  arm64)  eb_arch="--arm64"; arch_label="Apple Silicon (arm64)" ;;
  x86_64) eb_arch="--x64";   arch_label="Intel (x64)" ;;
  *)      fail "Unsupported architecture: $(uname -m)" ;;
esac

step "Target: $arch_label"

step "Building the Python sidecar (PyInstaller)"
"$python" -m PyInstaller backend.spec --noconfirm --distpath dist --workpath build

sidecar="$root/dist/fortrader-backend/fortrader-backend"
[[ -x "$sidecar" ]] || fail "Sidecar missing or not executable at $sidecar"

step "Smoke-testing the sidecar"
# A bundle that builds but cannot start is worse than a build failure,
# because it only surfaces on the user's machine.
FORTRADER_PORT=8797 \
FORTRADER_DATA_DIR="${TMPDIR:-/tmp}/fortrader-build-check" \
  "$sidecar" >/dev/null 2>&1 &
health_pid=$!
trap 'kill "$health_pid" 2>/dev/null || true' EXIT

ok=0
for _ in $(seq 1 30); do
  sleep 1
  if curl -sf --max-time 2 http://127.0.0.1:8797/health >/dev/null 2>&1; then ok=1; break; fi
  kill -0 "$health_pid" 2>/dev/null || break
done

kill "$health_pid" 2>/dev/null || true
trap - EXIT

[[ "$ok" == 1 ]] || fail "Sidecar did not answer /health — it built but cannot start."
echo "    sidecar healthy"

step "Verifying the MCP bridge"
# The same binary serves Claude Code, so a broken --mcp mode would
# silently disconnect every user.
#
# stdin is held open briefly rather than closed immediately: the server
# would otherwise see EOF and may exit before flushing its reply. The
# whole check is bounded by a polling loop because macOS has no GNU
# `timeout`, and an unbounded read here would hang the build silently.
request='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"build","version":"1"}}}'
mcp_out="$(mktemp)"

( printf '%s\n' "$request"; sleep 8 ) | "$sidecar" --mcp >"$mcp_out" 2>/dev/null &
mcp_pid=$!
trap 'kill "$mcp_pid" 2>/dev/null || true; rm -f "$mcp_out"' EXIT

mcp_ok=0
for _ in $(seq 1 20); do
  sleep 1
  if grep -q '"result"' "$mcp_out" 2>/dev/null; then mcp_ok=1; break; fi
done

kill "$mcp_pid" 2>/dev/null || true

[[ "$mcp_ok" == 1 ]] || fail "MCP bridge did not respond. Claude Code would not connect."
echo "    MCP bridge responded"

rm -f "$mcp_out"
trap - EXIT

step "Building the Electron bundles"
npm run build --workspace desktop

step "Packing the .dmg"
cd desktop
npx electron-builder --mac "$eb_arch" --config electron-builder.yml
cd "$root"

step "Done"
ls -lh release/*.dmg 2>/dev/null || fail "No .dmg produced — check the electron-builder output above."

cat <<'NOTE'

Install it by opening the .dmg and dragging Fortrader AI to Applications.

The build is unsigned. A locally built app runs normally; one that has
been *downloaded* is quarantined by Gatekeeper and needs either
right-click -> Open, or:

    xattr -dr com.apple.quarantine "/Applications/Fortrader AI.app"
NOTE
