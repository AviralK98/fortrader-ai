# Builds the complete Windows installer.
#
#   powershell -ExecutionPolicy Bypass -File scripts/build-installer.ps1
#
# Produces release/"Fortrader AI Setup <version>.exe".
#
# Three stages, in order, because each depends on the last:
#   1. PyInstaller bundles the Python backend into dist/fortrader-backend
#   2. electron-vite compiles main, preload and renderer into desktop/out
#   3. electron-builder packs both into an NSIS installer

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

# Editor terminals export this; it makes Electron boot as plain Node.
if ($env:ELECTRON_RUN_AS_NODE) {
    Write-Host "Unsetting ELECTRON_RUN_AS_NODE for this build." -ForegroundColor Yellow
    Remove-Item Env:ELECTRON_RUN_AS_NODE
}

$python = if ($env:FORTRADER_PYTHON) { $env:FORTRADER_PYTHON } else { "python" }

Step "Building the Python sidecar (PyInstaller)"
& $python -m PyInstaller backend.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$sidecar = Join-Path $root "dist\fortrader-backend\fortrader-backend.exe"
if (-not (Test-Path $sidecar)) { throw "Sidecar missing at $sidecar" }

Step "Smoke-testing the sidecar"
# A bundle that builds but cannot start is worse than a build failure,
# because it only surfaces on the user's machine.
$env:FORTRADER_PORT = "8797"
$env:FORTRADER_DATA_DIR = Join-Path $env:TEMP "fortrader-build-check"

$proc = Start-Process -PassThru -WindowStyle Hidden -FilePath $sidecar
try {
    $ok = $false
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:8797/health" -TimeoutSec 2
            if ($health.ok) { $ok = $true; break }
        } catch { }
    }
    if (-not $ok) { throw "Sidecar did not answer /health" }
    Write-Host "    sidecar healthy (schema v$($health.schema_version))" -ForegroundColor Green
} finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Remove-Item Env:FORTRADER_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:FORTRADER_DATA_DIR -ErrorAction SilentlyContinue
}

Step "Building the Electron bundles"
npm run build --workspace desktop
if ($LASTEXITCODE -ne 0) { throw "electron-vite build failed" }

Step "Packing the installer"
Set-Location (Join-Path $root "desktop")
npx electron-builder --win --config electron-builder.yml
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }

Set-Location $root

Step "Done"
Get-ChildItem release -Filter *.exe | ForEach-Object {
    "{0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB)
}
