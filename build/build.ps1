# build.ps1
# Builds the TELMA Windows installer (Setup_TELMA.exe).
# Run via build.bat or from a PowerShell terminal.
#
# Prerequisites (install once):
#   - Python 3.11+ on PATH  (python.org)
#   - Inno Setup 6          (jrsoftware.org/isdl.php)
#   - Portable MongoDB zip  (see step 4 below)

$ErrorActionPreference = "Stop"
$BuildDir = $PSScriptRoot
$RootDir  = Split-Path $BuildDir -Parent

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TELMA Installer Build" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Locate Python ──────────────────────────────────────────
Write-Host "[1] Locating Python 3.11+..."
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    Write-Host "    ERROR: python not found on PATH." -ForegroundColor Red
    Write-Host "    Install from https://python.org and tick 'Add to PATH'." -ForegroundColor Red
    exit 1
}
$PyVersion = & $Python --version 2>&1
Write-Host "    Found: $Python ($PyVersion)"

# ── 2. Create/refresh venv ────────────────────────────────────
$VenvDir = Join-Path $BuildDir "venv"
if (Test-Path $VenvDir) {
    Write-Host "[2] Removing existing build venv..."
    Remove-Item $VenvDir -Recurse -Force
}
Write-Host "[2] Creating venv at build\venv ..."
& $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { Write-Host "    ERROR: venv creation failed." -ForegroundColor Red; exit 1 }

# ── 3. Install packages ───────────────────────────────────────
Write-Host "[3] Installing packages (may take a few minutes)..."
$Pip = Join-Path $VenvDir "Scripts\pip.exe"
& $Pip install --upgrade pip --quiet
& $Pip install -r (Join-Path $RootDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "    ERROR: pip install failed." -ForegroundColor Red; exit 1 }
Write-Host "    Done."

# ── 4. Check portable MongoDB ─────────────────────────────────
$MongodExe = Join-Path $BuildDir "mongodb\bin\mongod.exe"
if (-not (Test-Path $MongodExe)) {
    Write-Host ""
    Write-Host "[4] Portable MongoDB missing!" -ForegroundColor Yellow
    Write-Host "    Expected: build\mongodb\bin\mongod.exe" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Steps:" -ForegroundColor Yellow
    Write-Host "    a) Go to https://www.mongodb.com/try/download/community" -ForegroundColor Yellow
    Write-Host "    b) Select: Version 7.x, Platform: Windows, Package: zip" -ForegroundColor Yellow
    Write-Host "    c) Extract the zip — you get a folder like mongodb-windows-x86_64-7.x.x\" -ForegroundColor Yellow
    Write-Host "    d) Copy that folder's contents into build\mongodb\" -ForegroundColor Yellow
    Write-Host "       so that build\mongodb\bin\mongod.exe exists." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Re-run build.bat after placing MongoDB." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[4] Portable MongoDB found."

# ── 5. Locate Inno Setup ──────────────────────────────────────
Write-Host "[5] Locating Inno Setup 6..."
$IssCompiler = $null
@(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | ForEach-Object {
    if (-not $IssCompiler -and (Test-Path $_)) { $IssCompiler = $_ }
}
if (-not $IssCompiler) {
    Write-Host "    ERROR: Inno Setup 6 not found." -ForegroundColor Red
    Write-Host "    Download from https://jrsoftware.org/isdl.php" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "    Found: $IssCompiler"

# ── 6. Compile installer ──────────────────────────────────────
Write-Host "[6] Compiling installer..."
$IssScript = Join-Path $BuildDir "Setup_TELMA.iss"
& $IssCompiler $IssScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "    ERROR: Inno Setup compilation failed." -ForegroundColor Red
    exit 1
}

# ── Done ──────────────────────────────────────────────────────
$OutExe = Join-Path $BuildDir "Output\Setup_TELMA.exe"
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Build complete!" -ForegroundColor Green
Write-Host "  Installer: $OutExe" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
