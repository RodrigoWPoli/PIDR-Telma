# TELMA Fault Detection — PIDR n°30

Real-time industrial fault detection for the TELMA platform at CRAN (Université de Lorraine), using OWL ontologies, Python, and MongoDB.

**Supervisors:** Chiara Franciosi, Alexandre Voisin, Sofia Zappa (Politecnico di Milano)
**Lab:** CRAN / MPSI — TELECOM Nancy 2nd year, 2025–2026

---

## Overview

The system detects bearing deterioration faults in the TELMA unwinding press by:

1. Reading sensor data from the OPC-UA server in real time
2. Storing values in MongoDB
3. Evaluating SWRL-based inference rules (implemented in Python) against the KARMA ontology
4. Outputting the inferred health state: **Healthy / Alert / Alarm / Faulty / Stopped**

The monitored component is the **AccumulatorMotor**. The primary indicator is `Otr_acc` (motor torque) — as bearing wear increases, torque rises above the alert and alarm thresholds.

```
OPC-UA server (TELMA PLC via VPN)
        │ opc.tcp://100.65.63.65:4840
        ▼
data_collection.py  ─►  MongoDB (telma.data)
                              │
                              ▼
                       dashboard.py
                              │
                              ▼
                    update_ontology.py
        (loads KARMA_v014.owl, evaluates SWRL rules S2–S10)
                              │
                              ▼
       Health State: Healthy / Alert / Alarm / Faulty / Stopped
```

---

## Project Structure

```
pidr/
├── ontology/KARMA_v014.owl       # KARMA ontology (v0.14)
├── OPCUA_variables.csv           # OPC-UA node IDs for all TELMA variables
├── data/                         # CSV exports and collections (auto-created)
│
├── data_collection.py            # OPC-UA reader → MongoDB writer
├── update_ontology.py            # Ontology loader + inference (SWRL in Python)
├── dashboard.py                  # Streamlit real-time dashboard
├── test_connections.py           # Environment / connectivity check
│
├── launcher/pidr_launcher.py     # PyInstaller entry point (windowed)
├── launcher/pidr.spec            # PyInstaller build spec
├── installer/build.ps1           # Windows build script (PyInstaller + Inno Setup)
├── installer/pidr.iss            # Inno Setup installer definition
│
├── requirements.txt
└── setup_mongodb.sh              # MongoDB installation for Fedora
```

---

## Setup (Linux development)

```bash
bash setup_mongodb.sh                  # 1. MongoDB (Fedora)
sudo dnf install java-17-openjdk       # 2. Java (only if running Pellet)
pip install -r requirements.txt        # 3. Python deps
python3 test_connections.py            # 4. Verify environment (all 6 checks must pass)
```

### Running

```bash
python3 data_collection.py 300         # collect 5 min from OPC-UA (VPN required)
python3 update_ontology.py --verbose   # one-shot inference on latest MongoDB value
streamlit run dashboard.py             # web dashboard at http://localhost:8501
```

---

## Dashboard

The Streamlit dashboard (`dashboard.py`) is the main UI. Three tabs, sidebar that adapts to the active tab.

### Tabs

#### Monitor — real-time health
- Large health-state card (Healthy / Alert / Alarm / Faulty / Stopped), color-coded, with hysteresis (state must persist 3 consecutive readings before Alert/Alarm is confirmed).
- AccumulatorMotor metrics: torque, speed, temperature, current.
- `Otr_acc` over time — Plotly bar chart, last 60 readings, color-coded by hysteresis state, with alert (21.73) and alarm (23.85) threshold lines.
- Failure chain (when Alert/Alarm): cause → failure mode → deviations → failure states.
- Signal status panel: `Ent_bob_cour`, `Ent_bob_abou`, coil-changing, belt tensioned/slack, `En_Production`.
- State history (last 8 transitions, rolling).
- Advance motor metrics, production counters, electrical (PowerTag) data.
- Auto-refreshes every 1–10 s (configurable).

#### Data explorer
- Summary metrics: total documents, first/last reading timestamps (cached with 10 s TTL, uses `estimated_document_count` for speed).
- Filters: view mode (Last N — 50/100/250/500/1000 — or All capped at 5000), sort order, by variable, by inferred state.
- Color-coded state column, CSV export of the current view.

#### Replay
- Replays historical data (CSV files in `data/` or MongoDB documents) through the inference engine step-by-step.
- Source radio, interval slider (0–10 s), Start/Stop.
- Progress bar, replayed-state card, state-distribution percentages, `Otr_acc` chart of last 200 rows.
- Keeps a rolling buffer of 500 results.
- Optionally writes the live ontology and runs Pellet per tick when the sidebar toggles are on (off by default in this mode for performance).

### Sidebar (mode-aware)

The sidebar shows different sections depending on the active tab:

- **Monitor / Data explorer**: Network (VPN status), Data collection (Start/Stop subprocess), Monitor toggle, Ontology controls (when Monitor is active), Settings (refresh interval, Clear state history).
- **Replay**: Only Ontology controls (Auto-update, Pellet, Save snapshot) — VPN/data collection/monitor sections are hidden.

**Ontology controls:**
- *Auto-update ontology* (default off) — writes current data property values to `ontology/KARMA_v014_live.owl` on each tick.
- *Run Pellet reasoner on update* (default off) — launches Pellet in a background thread after each ontology update (~1–3 s, non-blocking).
- *Save ontology snapshot* — writes a timestamped `KARMA_v014_snapshot_YYYYMMDD_HHMMSS.owl` (in `USER_DATA_DIR/ontology/`).

The original `ontology/KARMA_v014.owl` is **never modified** — only live and snapshot files are written.

**Inspecting in Protégé:** open `ontology/KARMA_v014_live.owl` to see current values; `Reasoner > Pellet` re-runs the reasoner interactively.

---

## Health State Logic

Inference rules in `update_ontology.py` mirror the SWRL rules in the KARMA ontology:

| Rule | Condition | State |
|------|-----------|-------|
| S6 | `0 < Otr_acc ≤ 21.73` | 🟢 Healthy |
| S7 | `21.73 < Otr_acc ≤ 23.85` | 🟡 Alert |
| S8 | `Otr_acc > 23.85` | 🔴 Alarm |
| S9 | `Otr_acc = 0` AND coil changing | 🟢 Healthy |
| S10 | `Otr_acc = 0` AND coil NOT changing AND `En_Production = True` | ⚫ Faulty |
| — | `Otr_acc = 0` AND `En_Production = False` | ⬜ Stopped (normal) |

- **Coil changing** (S2–S5): `Ent_bob_abou = True` AND `Ent_bob_cour = False` → coil is changing; any other combination → not changing.
- **Deviations** (S1/S11): Alert or Alarm triggers `LessAccumulatorMotorShaftRotationalSpeed` and `MoreAccumulatorMotorTorque`.
- **Failure state**: Faulty triggers `BearingNotWorking`.
- `En_Production` (`%MX102.6`) distinguishes a genuine fault from a normal stop.

---

## Monitored Variables (26 total)

All node IDs use the PLC embedded server `opc.tcp://100.65.63.65:4840`. Most variables are in `Application.GVL_OPC`; the four marked **GVL** are in `Application.GVL`.

| Variable | NS | Type | Description |
|----------|-----|------|-------------|
| `Otr_acc` | GVL_OPC | Int16 | Accumulator motor torque (Nm) — **primary fault indicator** |
| `Rfrd_acc` | GVL_OPC | Int16 | Accumulator motor speed (rpm) |
| `Ent_bob_cour` | GVL_OPC | Bool | Coil in current position |
| `Ent_bob_abou` | GVL_OPC | Bool | Coil in changing position |
| `En_Production` | GVL_OPC | Bool | Production cycle active |
| `TempMoteur_acc` | GVL_OPC | Int16 | Accumulator motor temperature (°C) |
| `Lcr_acc` | GVL_OPC | Float | Accumulator motor current (A) |
| `Uop_acc` | GVL_OPC | Int16 | Accumulator motor voltage (V) |
| `Courroie_accu_tendue` | GVL_OPC | Bool | Belt tensioned |
| `Courroie_accu_detendue` | GVL_OPC | Bool | Belt slack |
| `Otr_av` | GVL_OPC | Int16 | Advance motor torque (Nm) |
| `Rfrd_av` | GVL_OPC | Int16 | Advance motor speed (rpm) |
| `TempMoteur_av` | **GVL** | Float | Advance motor temperature (°C) |
| `Lcr_av` | GVL_OPC | Float | Advance motor current (A) |
| `Uop_av` | GVL_OPC | Int16 | Advance motor voltage (V) |
| `Cpt_nb_piece` | GVL_OPC | Int16 | Piece count |
| `Cpt_nb_bobine` | GVL_OPC | Int16 | Coil count |
| `Nombre_tours` | GVL_OPC | Int16 | Current turn count |
| `Dim_piece` | GVL_OPC | Int16 | Piece dimension |
| `CourantA` | **GVL** | Float | Phase A current (A) |
| `CourantB` | **GVL** | Float | Phase B current (A) |
| `CourantC` | **GVL** | Float | Phase C current (A) |
| `CourantTot` | GVL_OPC | Float | Total current A+B+C (A) |
| `Ent_au` | GVL_OPC | Bool | Emergency stop input |
| `diActTorque` | GVL_ATV320_Accu | Int16 | Raw drive torque (verification) |
| `diActlVelo` | GVL_ATV320_Accu | Int16 | Raw drive speed (verification) |

---

## MongoDB Schema

Each document stores only the variables that changed in that OPC-UA cycle:

```json
{
  "Otr_acc":      { "value": 22,   "SourceTimestamp": "2026-03-13T17:30:00+00:00" },
  "Ent_bob_cour": { "value": true, "SourceTimestamp": "2026-03-13T17:30:00+00:00" }
}
```

The monitor merges partial documents with the last known complete state before running inference.

Connection: `mongodb://localhost:27017/` — database `telma`, collection `data`.

---

## Key Configuration

| Parameter | Value | Location |
|-----------|-------|----------|
| Alert threshold | 21.73 Nm | `update_ontology.py`, `dashboard.py` |
| Alarm threshold | 23.85 Nm | `update_ontology.py`, `dashboard.py` |
| Hysteresis count | 3 consecutive readings | `dashboard.py` |
| Sampling interval | 1.0 s | `data_collection.py` |
| Dashboard refresh | 2 s (configurable 1–10) | `dashboard.py` |
| History points (chart) | 60 readings | `dashboard.py` |
| Max state history | 20 entries | `dashboard.py` |
| Replay buffer | 500 rows max | `dashboard.py` |
| MongoDB URI | `mongodb://localhost:27017/` | All files |
| OPC-UA server | `opc.tcp://100.65.63.65:4840` | `data_collection.py` |

---

## Windows Installer

The deliverable is `dist-installer\PIDR-Setup.exe` — a single double-clickable installer that bundles Python, the dashboard, the KARMA ontology, a portable JRE for Pellet, and the MongoDB 8.0 MSI.

### Build prerequisites (Windows 10/11 x64)

1. **Python 3.11+** on `PATH`.
2. **Inno Setup 6** — install from <https://jrsoftware.org/isinfo.php>. `ISCC.exe` ends up at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`; the build script finds it automatically.
3. **Internet access** during the first build (downloads JRE, MongoDB MSI, WebView2 bootstrapper into `installer\redist\`).

Cross-building from Linux/macOS is **not supported** — PyInstaller produces Windows `.exe` only on Windows.

### Build

From the project root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

What it does:
1. Downloads Eclipse Temurin 21 JRE → `launcher\jre\`.
2. Downloads MongoDB 8.0 MSI + WebView2 bootstrapper → `installer\redist\`.
3. Creates a Python venv at `.buildenv\` and installs `requirements-build.txt`.
4. Runs `pyinstaller launcher\pidr.spec` → `dist\pidr\`.
5. Runs `iscc installer\pidr.iss` → `dist-installer\PIDR-Setup.exe`.

Subsequent runs skip the downloads.

### Test the installer

On a clean Windows VM (no Python, no MongoDB, no Java):

1. Run `PIDR-Setup.exe`. Accept defaults; keep **Install MongoDB** ticked.
2. The desktop shortcut **PIDR** appears after install.
3. Double-click it — a native window titled "PIDR — TELMA Fault Detection" opens with the dashboard inside (~5 s).
4. Toggle the Pellet reasoner in the sidebar to confirm Java is wired in (no Java-not-found error in `%LOCALAPPDATA%\PIDR\launcher.log`).

### File layout after install

```
C:\Program Files\PIDR\
└── app\
    ├── pidr-launcher.exe       ← desktop shortcut target
    ├── dashboard.py
    ├── update_ontology.py
    ├── ontology\KARMA_v014.owl
    ├── jre\bin\java.exe         ← used by owlready2 / Pellet
    └── _internal\               ← Python runtime + libs (PyInstaller)
```

User-writable state (live ontology, snapshots, replay CSVs) lives in `%LOCALAPPDATA%\PIDR\`.

### Updating

There is no auto-update channel. Each release is a fresh installer rebuild; the user re-installs on top of the previous one. Inno Setup recognises the existing install by `AppId` and upgrades in place — user data under `%LOCALAPPDATA%\PIDR\` is preserved.

Per release:

```powershell
cd C:\path\to\pidr
git pull
# Bump #define MyAppVersion "x.y.z" in installer\pidr.iss
#   — do NOT change AppId (the GUID), or the upgrade becomes a side-by-side install.
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Ship the resulting `dist-installer\PIDR-Setup.exe`. On the user's machine: double-click; uncheck "Install MongoDB" and WebView2 on the prerequisites page (already installed); click Install.

**Partial rebuilds** (when only source changes, skip downloads):

```powershell
.buildenv\Scripts\python.exe -m PyInstaller --noconfirm launcher\pidr.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\pidr.iss
```

For dependency / JRE / MongoDB / WebView2 upgrades, see comments in `installer\build.ps1`.

### Rollback

Keep the last 1–2 installer versions archived. To roll back, re-run the old `PIDR-Setup.exe` — Inno Setup happily installs an older version over a newer one because the `AppId` matches. User data is untouched.

### Known follow-ups

- **Code signing** — the unsigned `.exe` triggers SmartScreen. For distribution outside the lab, sign with an Authenticode certificate.
- **VPN** — OPC-UA access still requires the AIPL VPN client; the installer does not configure it.

---

## Known Issues

- **Pellet reasoner**: `sync_reasoner_pellet` from owlready2 does not reliably return SWRL-inferred property values in Python — `motor.hasState` remains empty after reasoning despite Pellet executing successfully. SWRL rules are reimplemented natively in `update_ontology.py`. Pellet is optionally used in the dashboard to reason the live ontology file in a background thread; results are saved for inspection in Protégé.
- **MongoDB change streams**: Require a replica set. The local standalone setup uses polling mode by default; change streams are attempted first and fall back to polling.
- **`Otr_acc` scale factor**: The OPC-UA server returns `Int16`. Thresholds (21.73, 23.85) assume real-unit values. If the machine returns `2173` instead of `21.73`, adjust the scale factor in `update_ontology.py` and `dashboard.py`.
- **Machine availability**: The TELMA machine is not always on — use the Replay tab with CSV files in `data/` for offline development.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Audit & Setup | ✅ Done | Environment, connections, end-to-end pipeline |
| 2 — Real-time loop | ✅ Done | MongoDB polling monitor with state transitions |
| 3 — Interface | ✅ Done | Streamlit dashboard with live ontology and Pellet reasoning |
| 4 — Packaging | ✅ Done | Windows installer (PyInstaller + Inno Setup) bundling MongoDB and JRE |

---

## References

- KARMA ontology: Dalena, A. et al. — CRAN / Politecnico di Milano
- Previous internship: Julie Galopeau, 2022–2023 (codebase reference)
- TELMA platform: <https://www.cran.univ-lorraine.fr/plates-formes/telma/>
- owlready2 documentation: <https://owlready2.readthedocs.io/>
