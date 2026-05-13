<#
.SYNOPSIS
    Build the PIDR Windows installer.

.DESCRIPTION
    Run from the project root on a Windows machine that has:
      - Python 3.11+ on PATH
      - Inno Setup 6 (iscc.exe) on PATH or at the default install location
      - Internet access (to download JRE, MongoDB MSI, WebView2 bootstrapper)

    Steps:
      1. Download Eclipse Temurin 21 JRE, extract to launcher/jre/
      2. Download the MongoDB 8.0 MSI and the WebView2 evergreen bootstrapper
         into installer/redist/
      3. Create a Python venv and install requirements-build.txt
      4. Run PyInstaller against launcher/pidr.spec
      5. Run Inno Setup to produce dist-installer/PIDR-Setup.exe

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build.ps1
#>

[CmdletBinding()]
param(
    [string]$JreUrl = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.4%2B7/OpenJDK21U-jre_x64_windows_hotspot_21.0.4_7.zip",
    [string]$JreName = "jdk-21.0.4+7-jre",
    [string]$MongoMsiUrl = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.4-signed.msi",
    [string]$WebView2Url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- 1. JRE ----------------------------------------------------------------
$JreTarget = Join-Path $ProjectRoot "launcher\jre"
if (-not (Test-Path "$JreTarget\bin\java.exe")) {
    Step "Downloading Temurin 21 JRE..."
    $JreZip = Join-Path $env:TEMP "temurin-jre.zip"
    Invoke-WebRequest -Uri $JreUrl -OutFile $JreZip -UseBasicParsing

    Step "Extracting JRE to launcher/jre ..."
    $Extract = Join-Path $env:TEMP "temurin-jre-extract"
    if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
    Expand-Archive -Path $JreZip -DestinationPath $Extract -Force
    $Inner = Get-ChildItem -Path $Extract -Directory | Select-Object -First 1
    if (Test-Path $JreTarget) { Remove-Item -Recurse -Force $JreTarget }
    Move-Item -Path $Inner.FullName -Destination $JreTarget
    Remove-Item -Recurse -Force $Extract
    Remove-Item -Force $JreZip
} else {
    Step "JRE already present at $JreTarget"
}

# --- 2. Redistributables ---------------------------------------------------
$Redist = Join-Path $ProjectRoot "installer\redist"
New-Item -ItemType Directory -Force -Path $Redist | Out-Null

$MongoMsi = Join-Path $Redist "mongodb-windows-x86_64-8.0.4-signed.msi"
if (-not (Test-Path $MongoMsi)) {
    Step "Downloading MongoDB 8.0 MSI..."
    Invoke-WebRequest -Uri $MongoMsiUrl -OutFile $MongoMsi -UseBasicParsing
}

$WebView2 = Join-Path $Redist "MicrosoftEdgeWebView2Setup.exe"
if (-not (Test-Path $WebView2)) {
    Step "Downloading Edge WebView2 evergreen bootstrapper..."
    Invoke-WebRequest -Uri $WebView2Url -OutFile $WebView2 -UseBasicParsing
}

# --- 3. Build venv ---------------------------------------------------------
$Venv = Join-Path $ProjectRoot ".buildenv"
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    Step "Creating Python build venv at .buildenv ..."
    python -m venv $Venv
}
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements-build.txt

# --- 4. PyInstaller --------------------------------------------------------
Step "Running PyInstaller..."
Remove-Item -Recurse -Force "$ProjectRoot\build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$ProjectRoot\dist" -ErrorAction SilentlyContinue
& $Py -m PyInstaller --noconfirm launcher\pidr.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

# --- 5. Inno Setup ---------------------------------------------------------
Step "Running Inno Setup..."
$Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue)?.Source
if (-not $Iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "iscc.exe not found. Install Inno Setup 6." }

& $Iscc "$ProjectRoot\installer\pidr.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }

$Installer = Join-Path $ProjectRoot "dist-installer\PIDR-Setup.exe"
Step "Done. Installer: $Installer"
