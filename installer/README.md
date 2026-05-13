# Building the PIDR Windows installer

The deliverable is `dist-installer\PIDR-Setup.exe` — a single double-clickable
installer that bundles Python, the dashboard, the KARMA ontology, a portable
JRE for Pellet, and the MongoDB 8.0 MSI.

## Prerequisites (build machine — Windows 10/11 x64)

1. **Python 3.11+** on `PATH` (`python --version` should work).
2. **Inno Setup 6** — install from <https://jrsoftware.org/isinfo.php>.
   `ISCC.exe` ends up at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`;
   the build script finds it there automatically.
3. **Internet access** during the first build (to download the JRE, MongoDB
   MSI, and the WebView2 bootstrapper into `installer\redist\`).

Cross-building from Linux/macOS is **not supported** — PyInstaller produces
Windows `.exe` only on Windows.

## Build

From the project root, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

What this does:

1. Downloads Eclipse Temurin 21 JRE and extracts it to `launcher\jre\`.
2. Downloads the MongoDB 8.0 MSI and the Edge WebView2 bootstrapper into
   `installer\redist\`.
3. Creates a Python venv at `.buildenv\` and installs
   `requirements-build.txt`.
4. Runs `pyinstaller launcher\pidr.spec` → `dist\pidr\` (onedir bundle).
5. Runs `iscc installer\pidr.iss` → `dist-installer\PIDR-Setup.exe`.

Subsequent runs skip the downloads if the files already exist.

## Test the installer

On a clean Windows VM (no Python, no MongoDB, no Java):

1. Run `PIDR-Setup.exe`. Accept defaults; keep **Install MongoDB** ticked.
2. After install, the desktop shortcut **PIDR** should appear.
3. Double-click it. Within ~5 s a native window titled
   "PIDR — TELMA Fault Detection" opens with the dashboard inside.
4. In the dashboard sidebar, toggle the Pellet reasoner to confirm Java
   is wired in (no Java-not-found error in
   `%LOCALAPPDATA%\PIDR\launcher.log`).
5. Close the window. The launcher exits cleanly; MongoDB keeps running as
   a Windows service.

## File layout after install

```
C:\Program Files\PIDR\
└── app\
    ├── pidr-launcher.exe       ← the desktop shortcut points here
    ├── dashboard.py
    ├── update_ontology.py
    ├── ontology\KARMA_v014.owl
    ├── jre\bin\java.exe        ← used by owlready2 / Pellet
    └── _internal\              ← Python runtime + libs (PyInstaller)
```

User-writable state (live ontology, replay CSVs) lives in
`%LOCALAPPDATA%\PIDR\`.

## Known follow-ups

- **Code signing** — the unsigned `.exe` triggers SmartScreen. For
  distribution outside the lab, sign with an Authenticode certificate.
- **Auto-update** — none yet. Ship a new installer per release.
- **VPN** — OPC-UA access still requires the AIPL VPN client; the
  installer does not configure it.
