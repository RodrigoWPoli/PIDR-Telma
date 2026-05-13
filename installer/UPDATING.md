# Updating the PIDR executable

There is no auto-update channel. Each release is a fresh installer rebuild
that the user re-installs on top of the previous one. Inno Setup recognises
the existing install by `AppId` and upgrades in place — user data under
`%LOCALAPPDATA%\PIDR\` is preserved.

---

## 1. On the Windows build machine (per release)

### Step 1 — pull the new code
```powershell
cd C:\path\to\pidr
git pull
```

### Step 2 — bump the version
Edit `installer\pidr.iss`:
```
#define MyAppVersion "1.0.1"
```
**Do not change `AppId`** — the GUID in the `[Setup]` section is how Inno
Setup detects the existing install and upgrades it. Regenerating it would
turn the upgrade into a side-by-side second install.

### Step 3 — rebuild
```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```
The JRE, MongoDB MSI, and WebView2 bootstrapper are cached in
`launcher\jre\` and `installer\redist\`, so only PyInstaller + Inno Setup
re-run on subsequent builds (~2–5 minutes).

Output: `dist-installer\PIDR-Setup.exe`.

### Step 4 — ship
Hand `PIDR-Setup.exe` to the user (USB stick, network share, signed email,
whatever channel you use).

---

## 2. On the user's machine

1. Double-click the new `PIDR-Setup.exe`.
2. Same install directory, same shortcuts — Inno Setup overwrites the
   `app\` folder.
3. **Uncheck "Install MongoDB"** on the prerequisites page (it's already
   installed). Same for WebView2.
4. Click Install. Done. User data in `%LOCALAPPDATA%\PIDR\` is untouched.

---

## 3. Partial rebuilds (when something specific changes)

### A. Only Python source changed (dashboard, update_ontology, …)
Skip the downloads and the venv setup. Run just PyInstaller + Inno Setup:
```powershell
.buildenv\Scripts\python.exe -m PyInstaller --noconfirm launcher\pidr.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\pidr.iss
```

### B. Python dependency upgrade (streamlit, owlready2, …)
1. Bump the pin in `requirements.txt` (or `requirements-build.txt`).
2. Refresh the build venv:
   ```powershell
   .buildenv\Scripts\python.exe -m pip install -r requirements-build.txt --upgrade
   ```
   Or delete `.buildenv\` to force a clean venv on the next `build.ps1`.
3. Run `build.ps1`.

### C. JRE upgrade
1. Delete `launcher\jre\`.
2. Optionally update `$JreUrl` and `$JreName` defaults at the top of
   `build.ps1` to point at the new Temurin release.
3. Run `build.ps1` — it re-downloads and re-extracts the JRE.

### D. MongoDB upgrade
1. Delete `installer\redist\mongodb-windows-x86_64-*.msi`.
2. Update `$MongoMsiUrl` in `build.ps1` to the new MSI URL.
3. Update the MSI filename in **two places** in `installer\pidr.iss`:
   - the `[Files]` line that ships it,
   - the `[Run]` line that invokes `msiexec`.
4. Update the `binPath=` path in the `sc.exe create MongoDB` line if the
   MongoDB version directory changed (e.g. `Server\8.0\` → `Server\8.1\`).
5. Run `build.ps1`.

### E. WebView2 bootstrapper refresh
1. Delete `installer\redist\MicrosoftEdgeWebView2Setup.exe`.
2. Run `build.ps1` — the URL is the Microsoft "evergreen" redirect, so it
   always pulls the current bootstrapper.

---

## 4. Common mistakes to avoid

- **Changing `AppId` in `pidr.iss`.** Breaks in-place upgrades — the new
  installer will install side-by-side instead of replacing the old one.
- **Forgetting to bump `MyAppVersion`.** Inno Setup still upgrades, but
  "Add/Remove Programs" keeps showing the old version string.
- **Editing files inside `dist\pidr\` directly.** That folder is
  regenerated from scratch every PyInstaller run; edits are lost. Source
  of truth lives in `launcher\`, `dashboard.py`, `update_ontology.py`, etc.
- **Running `build.ps1` from anywhere other than the project root.** It
  derives paths from `$PSScriptRoot\..`; running it from a different
  working dir is fine, but invoking the inner commands manually from the
  wrong dir is not.
- **Skipping `git pull` before bumping the version.** You'll ship an
  installer with old source and a new version label.

---

## 5. Rollback

If a release is broken on the user's machine:

1. Find the previous `PIDR-Setup.exe` (keep the last 1–2 versions
   archived).
2. The user re-runs the old installer; it overwrites the broken `app\`
   folder. User data is untouched.
3. No special "downgrade" mode needed — Inno Setup happily installs an
   older version over a newer one because the `AppId` matches.
