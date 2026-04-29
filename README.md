# TELMA Fault Detection — PIDR n°30

Real-time industrial fault detection for the TELMA platform at CRAN (Université de Lorraine), using OWL ontologies, Python, and MongoDB.

**Supervisors:** Chiara Franciosi, Alexandre Voisin, Sofia Zappa (Politecnico di Milano)  
**Lab:** CRAN / MPSI — TELECOM Nancy 2nd year, 2025–2026

---

## Overview

This project detects bearing deterioration faults in the TELMA unwinding press by:

1. Reading sensor data from the OPC-UA server in real time
2. Storing values in MongoDB
3. Evaluating the SWRL rules defined in the KARMA ontology dynamically
4. Outputting the inferred health state: **Healthy / Alert / Alarm / Faulty / Stopped**

The monitored component is the **AccumulatorMotor**. The key indicator is `Otr_acc` (motor torque) — as bearing wear increases, torque rises above the alert and alarm thresholds.

---

## Project Structure

```
PIDR-Telma/
├── ontology/
│   └── KARMA_v014.owl          # KARMA ontology with SWRL rules (S1–S11)
│
├── data/                       # Auto-created — CSV exports
│
├── build/                      # Windows installer build system
│   ├── build.bat               # Double-click to build installer
│   ├── build.ps1               # PowerShell build automation
│   └── Setup_TELMA.iss         # Inno Setup 6 script
│
├── app.py                      # Desktop launcher (PyWebView window)
├── dashboard.py                # Streamlit real-time dashboard
├── swrl_engine.py              # Dynamic SWRL rule evaluator (reads rules from OWL)
├── update_ontology.py          # Loads ontology, runs SWRL engine, returns health state
├── realtime_monitor.py         # Watches MongoDB → runs inference on each new doc
├── data_collection.py          # Reads OPC-UA server → stores in MongoDB
├── ontology_builder.py         # API for programmatically extending the ontology
│
├── test_ontology_builder.py    # Tests for ontology_builder.py
├── test_connections.py         # Environment / connectivity check
│
├── requirements.txt
└── setup_mongodb.sh            # MongoDB installation script (Fedora/RHEL)
```

---

## Setup (Linux / development)

### 1. Install MongoDB
```bash
bash setup_mongodb.sh
sudo systemctl start mongod
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. Verify environment
```bash
python3 test_connections.py
```
All checks should show ✓ before proceeding.

---

## Running the dashboard

### Native desktop window
```bash
python3 app.py
```
Opens a self-contained native window (PyWebView). No browser tab needed. The window starts Streamlit internally and shuts everything down when closed.

### Browser (alternative)
```bash
streamlit run dashboard.py
```
Opens at `http://localhost:8501`. The dashboard auto-refreshes every 2 seconds without full-page reloads.

---

## Usage

### Offline development (no VPN / no machine)
```bash
python3 simulate_data.py --clear   # clear MongoDB, insert ~90 synthetic documents
python3 app.py                     # launch dashboard
```

### Real machine data (AIPL VPN required)
```bash
python3 data_collection.py 300     # collect for 5 minutes
```

### One-shot inference
```bash
python3 update_ontology.py --verbose   # run inference on latest MongoDB value
```

---

## Windows Installation

The project ships as a one-click Windows installer that bundles Python, all dependencies, and a portable MongoDB — no manual setup required.

### For end users

1. Download `Setup_TELMA.exe` (from the project maintainer)
2. Double-click and follow the wizard
3. Click the **TELMA Dashboard** desktop shortcut

The installer places everything under `C:\Program Files\TELMA\`. MongoDB data is stored in `%LOCALAPPDATA%\TELMA\mongodb\data` (user-writable). On launch, the app automatically starts MongoDB if it is not already running, then starts Streamlit and opens the native window.

### Building the installer (developer)

Prerequisites — install once on Windows:
- Python 3.11+ from [python.org](https://python.org) (tick "Add to PATH")
- [Inno Setup 6](https://jrsoftware.org/isdl.php)
- Portable MongoDB 7 zip from [mongodb.com/try/download/community](https://www.mongodb.com/try/download/community)
  - Select: Version 7.x · Platform: Windows · Package: **zip**
  - Extract and copy contents into `build\mongodb\` so that `build\mongodb\bin\mongod.exe` exists

Then build:
```
build\build.bat   ← double-click this
```

The script creates a fresh venv, installs all packages, and compiles `build\Output\Setup_TELMA.exe`.

---

## SWRL Rule Engine

Rules are read directly from the OWL file at startup — no hardcoded Python logic. This means a researcher can edit rules in Protégé and the updated logic takes effect on next run without touching any Python code.

### How it works

`swrl_engine.py` implements a forward-chaining SWRL evaluator:

1. **Parse** — `parse_rules()` reads `DLSafeRule` elements from the OWL XML using `xml.etree.ElementTree`. owlready2 does not expose these through its API, so raw XML parsing is used.
2. **FactBase** — builds an in-memory triple store `{individual → {property → [values]}}` from owlready2 individuals.
3. **Evaluate** — for each rule, atoms in the body are topologically sorted (class membership and data-property binding atoms first, built-in comparisons last) and evaluated via recursive variable binding. Two passes are run to handle rule chaining (S2–S5 produce facts consumed by S9/S10).
4. **Apply** — inferred head assertions are written back to the FactBase and returned as a result dict consumed by `update_ontology.py`.

### Why not Pellet?

`sync_reasoner_pellet` (owlready2's built-in bridge) was tested. Two problems make it unusable here:

- The `pellet realize` command outputs only ABox class memberships, not SWRL-inferred object property assertions (`hasState`, `hasDeviation`, etc.) — so `motor.hasState` is always empty after reasoning.
- owlready2's SQLite triplestore does not store `DLSafeRule` elements at all — `onto.rules()` returns 0 even for an ontology with 11 rules.

The custom SWRL engine resolves both issues by working directly with the OWL XML.

---

## Health State Logic

The KARMA ontology defines eleven SWRL rules (S1–S11). The key ones for health state output:

| Rule | Condition | Output |
|------|-----------|--------|
| S2 | `Ent_bob_abou = True` AND `Ent_bob_cour = False` | Coil changing |
| S3–S5 | Any other combination | Coil not changing |
| S6 | `0 < Otr_acc ≤ 21.73` | 🟢 Healthy |
| S7 | `21.73 < Otr_acc ≤ 23.85` | 🟡 Alert |
| S8 | `Otr_acc > 23.85` | 🔴 Alarm |
| S9 | `Otr_acc = 0` AND coil changing | 🟢 Healthy (normal coil change) |
| S10 | `Otr_acc = 0` AND coil NOT changing AND `En_Production = True` | ⚫ Faulty |
| — | `Otr_acc = 0` AND `En_Production = False` | ⬜ Stopped |

When Alert or Alarm, two deviations are also inferred:
- `LessAccumulatorMotorShaftRotationalSpeed` (via `RotationalSpeedFlow`)
- `MoreAccumulatorMotorTorque` (via `TorqueFlow`)

---

## OPC-UA Connection

| Parameter | Value |
|-----------|-------|
| Server URL | `opc.tcp://100.65.63.87:49152/OPCUAServerExpert` |
| VPN required | AIPL VPN |
| Key variables | `Otr_acc`, `Rfrd_acc`, `Ent_bob_cour`, `Ent_bob_abou` |

All variable node IDs use the PLC embedded server (`opc.tcp://100.65.63.65:4840`). Most variables are in the `Application.GVL_OPC` namespace; four exceptions are in `Application.GVL`:

| Variable | Namespace | Type | Description |
|----------|-----------|------|-------------|
| `Otr_acc` | GVL_OPC | Int16 | Accumulator motor torque (Nm) |
| `Rfrd_acc` | GVL_OPC | Int16 | Accumulator motor speed (rpm) |
| `Ent_bob_cour` | GVL_OPC | Boolean | Coil in current position |
| `Ent_bob_abou` | GVL_OPC | Boolean | Coil in changing position |
| `En_Production` | GVL_OPC | Boolean | Production cycle active |
| `TempMoteur_acc` | GVL_OPC | Int16 | Accumulator motor temperature (°C) |
| `Lcr_acc` | GVL_OPC | Float | Accumulator motor current (A) |
| `Uop_acc` | GVL_OPC | Int16 | Accumulator motor voltage (V) |
| `Courroie_accu_tendue` | GVL_OPC | Boolean | Belt tensioned |
| `Courroie_accu_detendue` | GVL_OPC | Boolean | Belt slack |
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
| `Ent_au` | GVL_OPC | Boolean | Emergency stop input |
| `diActTorque` | GVL_ATV320_Accu | Int16 | Raw drive torque (verification) |
| `diActlVelo` | GVL_ATV320_Accu | Int16 | Raw drive speed (verification) |

---

## MongoDB Schema

Each document stores only the variables that changed in the OPC-UA subscription cycle:

```json
{
  "Otr_acc": {
    "value": 22,
    "SourceTimestamp": "2026-03-13T17:30:00+00:00"
  },
  "Ent_bob_cour": {
    "value": true,
    "SourceTimestamp": "2026-03-13T17:30:00+00:00"
  }
}
```

Connection: `mongodb://localhost:27017/` — database `telma`, collection `data`.

The monitor merges partial documents with the last known complete state before running inference.

---

## Extending the Ontology

Use `ontology_builder.py` to add new components, failure chains, or sensors without editing the OWL file directly. Because inference reads rules from the OWL at startup, new SWRL rules added in Protégé are also picked up automatically.

```python
from ontology_builder import OntologyBuilder

ob = OntologyBuilder("ontology/KARMA_v014.owl")

ob.add_failure_chain(
    cause_name            = "BeltWearByFriction",
    cause_class           = "PrimaryFailureCause",
    mode_name             = "BeltDeterioration",
    mode_class            = "MechanicalFailureMode",
    occurs_in             = "AccumulatorMotor",
    results_in_deviations = ["LessBeltTension", "MoreAdvanceMotorTorque"],
    deviation_classes     = ["Negative", "Positive"]
)

ob.save("ontology/KARMA_v014_updated.owl")
ob.summary()
```

---

## Known Issues

**MongoDB change streams:** The real-time monitor uses polling mode by default (`--polling` flag). Change streams require a MongoDB replica set, which is not configured in the local standalone setup.

**`Otr_acc` scale factor:** The OPC-UA server returns `Int16`. Thresholds (21.73, 23.85) assume real-unit values. If the machine returns 2173 instead of 21.73, set `SCALE_FACTOR = 0.01` in `simulate_data.py` and divide in `update_ontology.py`.

**Machine availability:** The TELMA machine is not always on. Use `simulate_data.py` for offline development.

**PyWebView on Linux:** Requires GTK WebKit system libraries. If unavailable (e.g. on WSL), `app.py` falls back to opening the system browser automatically.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Audit & Setup | ✅ Done | Environment, connections, end-to-end pipeline |
| 2 — Real-time loop | ✅ Done | MongoDB polling monitor with state transitions |
| 3 — Dynamic ontology | ✅ Done | `ontology_builder.py` API |
| 4 — Interface | ✅ Done | Streamlit dashboard in native desktop window |
| 5 — Dynamic SWRL engine | ✅ Done | Rules read from OWL at runtime via `swrl_engine.py` |
| 6 — Windows installer | ✅ Done | One-click `Setup_TELMA.exe` via Inno Setup |
| 7 — New failure scenario | ⏳ Stretch | Second failure scenario using Phase 3 API |

---

## References

- KARMA ontology: Dalena, A. et al. — CRAN / Politecnico di Milano
- Previous internship: Julie Galopeau, 2022–2023 (codebase reference)
- TELMA platform: https://www.cran.univ-lorraine.fr/plates-formes/telma/
- owlready2 documentation: https://owlready2.readthedocs.io/
