# DeepSeek Monitor - Windows one-click build script
# =================================================
#
# Usage (PowerShell):
#     cd "D:\DeepSeek Monitor\deepseek-monitor"
#     powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1
#
# Or directly in PowerShell terminal:
#     .\scripts\build_exe.ps1
#
# This script will:
#   1. Activate project .venv
#   2. Install Python dependencies
#   3. Keep Playwright browser runtime external to reduce package size
#   4. Clean old build/dist
#   5. Package with PyInstaller onedir mode
#   6. Verify Playwright driver is in the output
#   7. Print EXE path

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# 0. Locate project root
# ---------------------------------------------------------------------------
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ProjectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  DeepSeek Monitor - Build Script"      -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root: $ProjectRoot"

# ---------------------------------------------------------------------------
# 1. Activate virtual environment
# ---------------------------------------------------------------------------
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtualenv not found: $VenvPython" -ForegroundColor Red
    Write-Host "Run: py -3.12 -m venv .venv" -ForegroundColor Yellow
    Write-Host "Then: .\.venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Virtualenv Python: $VenvPython" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. Install/update dependencies
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[1/6] Installing Python dependencies ..." -ForegroundColor Yellow
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Dependencies ready" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. Slim Playwright packaging strategy
#
#    Do NOT set PLAYWRIGHT_BROWSERS_PATH=0 here.
#    Do NOT install Chromium into playwright package.
#    The app prefers the user's default Edge/Chrome, then installed Edge/Chrome.
#    This keeps the distributable much smaller.
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/6] Using slim Playwright mode (Chromium not bundled) ..." -ForegroundColor Yellow
Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue

# Verify playwright driver directory is non-empty
$PlaywrightPkgDir = & $VenvPython -c "import playwright, os; print(os.path.dirname(playwright.__file__))"
if (-not $PlaywrightPkgDir) {
    Write-Host "[ERROR] Cannot locate playwright package directory" -ForegroundColor Red
    exit 1
}
$DriverDir = Join-Path $PlaywrightPkgDir "driver"
if (-not (Test-Path $DriverDir)) {
    Write-Host "[ERROR] playwright driver directory not found: $DriverDir" -ForegroundColor Red
    exit 1
}
$NodeExe = Join-Path $DriverDir "node.exe"
if (Test-Path $NodeExe) {
    Write-Host "[OK] Playwright driver ready (node.exe found)" -ForegroundColor Green
} else {
    Write-Host "[WARN] playwright driver dir exists but node.exe not found, continuing..." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 4. Clean old build artifacts
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Cleaning old build artifacts ..." -ForegroundColor Yellow

$BuildDir = Join-Path $ProjectRoot "build"
$DistDir  = Join-Path $ProjectRoot "dist"

if (Test-Path $BuildDir) {
    Remove-Item -Recurse -Force $BuildDir
    Write-Host "  Deleted build/"
}
if (Test-Path $DistDir) {
    Remove-Item -Recurse -Force $DistDir
    Write-Host "  Deleted dist/"
}
Write-Host "[OK] Cleanup done" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 5. Verify runtime hook exists
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/6] Checking runtime hook ..." -ForegroundColor Yellow

$RuntimeHook = Join-Path $ProjectRoot "scripts\pyi_rth_playwright.py"
if (Test-Path $RuntimeHook) {
    Write-Host "[OK] pyi_rth_playwright.py ready" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Missing runtime hook: $RuntimeHook" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 6. PyInstaller build (onedir mode)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/6] PyInstaller packaging (onedir) ..." -ForegroundColor Yellow
Write-Host "  This may take a few minutes..."

$SpecFile = Join-Path $ProjectRoot "DeepSeekMonitor.spec"
Push-Location $ProjectRoot
try {
    & $VenvPython -m PyInstaller $SpecFile --noconfirm
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] PyInstaller build failed" -ForegroundColor Red
        exit 1
    }
}
finally {
    Pop-Location
}
Write-Host "[OK] Build complete" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 7. Verify output
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[6/6] Verifying output ..." -ForegroundColor Yellow

$ExeDir = Join-Path $DistDir "DeepSeek Monitor"
$ExePath = Join-Path $ExeDir "DeepSeek Monitor.exe"
$InternalDir = Join-Path $ExeDir "_internal"

if (-not (Test-Path $ExePath)) {
    Write-Host "[ERROR] EXE not found: $ExePath" -ForegroundColor Red
    exit 1
}

# Check if _internal/playwright/driver/ exists
$BundledDriver = Join-Path $InternalDir "playwright\driver"
if (Test-Path $BundledDriver) {
    $BundledNode = Join-Path $BundledDriver "node.exe"
    if (Test-Path $BundledNode) {
        Write-Host "[OK] playwright driver bundled in _internal/" -ForegroundColor Green
    } else {
        Write-Host "[WARN] playwright/driver bundled but node.exe not found" -ForegroundColor Yellow
    }
} else {
    Write-Host "[WARN] playwright/driver/ not found in _internal/" -ForegroundColor Yellow
    Write-Host "  This may affect automatic Usage sync at runtime" -ForegroundColor Yellow
    Write-Host "  Check PyInstaller output for playwright-related warnings" -ForegroundColor Yellow
}

$BundledBrowsers = Get-ChildItem -Path $InternalDir -Recurse -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -like "*.local-browsers*" -or
        $_.Name -like "chromium-*" -or
        $_.Name -like "chromium_headless*"
    }
if ($BundledBrowsers) {
    Write-Host "[WARN] Browser runtime appears to be bundled; output may still be large" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Chromium browser runtime not bundled (slim output)" -ForegroundColor Green
}

# Check for bundled runtime hook
$FoundRth = Get-ChildItem -Path $InternalDir -Recurse -Filter "pyi_rth_playwright*" -ErrorAction SilentlyContinue
if ($FoundRth) {
    Write-Host "[OK] runtime hook pyi_rth_playwright bundled" -ForegroundColor Green
} else {
    Write-Host "[WARN] runtime hook pyi_rth_playwright not found in output" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 8. Print results
# ---------------------------------------------------------------------------
$ExeSize = (Get-Item $ExePath).Length / 1MB
$InternalSize = 0
if (Test-Path $InternalDir) {
    $InternalSize = (Get-ChildItem -Path $InternalDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Build Successful!"                   -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  EXE path     : $ExePath"
Write-Host "  EXE size     : $([math]::Round($ExeSize, 1)) MB"
Write-Host "  Internal deps: $([math]::Round($InternalSize, 1)) MB"
Write-Host "  Output dir   : $ExeDir"
Write-Host ""
Write-Host "  To distribute:"
Write-Host '    Copy the entire "DeepSeek Monitor" folder to users.'
Write-Host "    No Python needed. For auto Usage sync, Microsoft Edge or Google Chrome should be installed."
Write-Host ""
Write-Host "  First-time use:"
Write-Host "    1. Run DeepSeek Monitor.exe"
Write-Host "    2. Click gear icon -> enter DeepSeek API Key"
Write-Host "    3. Click 'Open Login Window' -> login to DeepSeek"
Write-Host "    4. Click refresh -> auto-sync usage"
Write-Host ""
Write-Host "  User data location:"
Write-Host "    %LOCALAPPDATA%\DeepSeek Monitor\"
Write-Host "      browser_profile\   (browser login session)"
Write-Host "      exports\           (auto-synced export files)"
Write-Host "      logs\              (runtime logs)"
Write-Host "      config.json        (app settings)"
Write-Host "      usage.db           (local usage database)"
Write-Host ""
