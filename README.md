# TELMA Fault Detection — PIDR n°30

Real-time industrial fault detection for the TELMA platform at CRAN (Université de Lorraine), using OWL ontologies, Python, and MongoDB.

**Supervisors:** Chiara Franciosi, Alexandre Voisin, Sofia Zappa (Politecnico di Milano)  
**Lab:** CRAN / MPSI — TELECOM Nancy 2nd year, 2025–2026

---

## Overview

This project detects bearing deterioration faults in the TELMA unwinding press by:

1. Reading sensor data from the OPC-UA server in real time
2. Storing values in MongoDB
3. Evaluating SWRL-based inference rules (implemented in Python) against the KARMA ontology
4. Outputting the inferred health state: **Healthy / Alert / Alarm / Faulty / Stopped**

The monitored component is the **AccumulatorMotor**. The key indicator is `Otr_acc` (motor torque) — as bearing wear increases, torque rises above the alert and alarm thresholds.

---

## Project Structure

```
~/Projects/pidr/
├── ontology/
│   └── KARMA_v014.owl          # KARMA ontology (v0.14)
│
├── OPCUA_variables.csv         # OPC-UA node IDs for all TELMA variables
│
├── data/                       # Auto-created — CSV exports and collections
│
├── data_collection.py          # Reads OPC-UA server → stores in MongoDB
├── simulate_data.py            # Generates synthetic data for offline testing
├── update_ontology.py          # Loads ontology, evaluates rules, returns health state
├── realtime_monitor.py         # Watches MongoDB → runs inference on each new doc
├── dashboard.py                # Streamlit real-time dashboard

├── test_connections.py         # Environment / connectivity check
│
├── requirements.txt
└── setup_mongodb.sh            # MongoDB installation for Fedora
```

---

## Setup

### 1. Install MongoDB (Fedora)
```bash
bash setup_mongodb.sh
```

### 2. Install Java (required for Pellet reasoner, if used)
```bash
sudo dnf install java-17-openjdk
```

### 3. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 4. Verify environment
```bash
python3 test_connections.py
```
All 6 checks should show ✓ before proceeding.

---

## Usage

### Collect real machine data (VPN required)
```bash
# Connect AIPL VPN first, then:
python3 data_collection.py 300     # collect for 5 minutes
```

### Generate synthetic test data (offline)
```bash
python3 simulate_data.py --clear   # clears MongoDB and inserts 90 test documents
```

### Run a single inference (latest MongoDB value)
```bash
python3 update_ontology.py --verbose
```

### Run the real-time monitor (terminal)
```bash
# Terminal 1 — start monitor
python3 realtime_monitor.py --polling

# Terminal 2 — feed data (real or simulated)
python3 data_collection.py
# or
python3 simulate_data.py
```

### Run the dashboard
```bash
pip install streamlit plotly   # first time only
streamlit run dashboard.py     # opens http://localhost:8501
```

The dashboard has three tabs:

| Tab | Purpose |
|-----|---------|
| **Monitor** | Real-time health state, Otr_acc chart (hysteresis-colored), failure chain, signal status, state history, advance motor metrics, production counters, electrical data. Refreshes every 1–10 s (configurable). |
| **Data explorer** | Flat table of all MongoDB documents with inferred states, filters by variable/state, CSV export. |
| **Replay** | Replay CSV files or MongoDB documents through the reasoner — configurable interval, state distribution chart, Start/Stop controls. |

**Sidebar controls:**
- **VPN status** — shows whether the PLC is reachable
- **Data collection** — start/stop `data_collection.py` as a subprocess (VPN required for real data)
- **Monitor active** toggle — deactivate to run standalone data collection without inference overhead (Monitor tab shows a placeholder)
- **Auto-update ontology** toggle — writes current data property values to `ontology/KARMA_v014_live.owl` on each refresh
- **Run Pellet reasoner** toggle — launches Pellet in a background thread after each ontology update, materializing inferred axioms into the live file (~1–3 s, does not block UI)
- **Save ontology snapshot** button — writes a timestamped `ontology/KARMA_v014_snapshot_YYYYMMDD_HHMMSS.owl` for session history
- **Refresh interval** slider — 1–10 s
- **Clear state history** — resets the state transition log

---

## Ontology Live File & Protégé

When **Auto-update ontology** is enabled in the dashboard, the live ontology state is saved to `ontology/KARMA_v014_live.owl` on each refresh. This file contains the current data property values (`hasCurrentValue`, `hasHorizontalPosition`, `hasVerticalPosition`) set on the ontology individuals.

If **Run Pellet reasoner** is also enabled, Pellet runs in a background thread on the live file after each update, materializing all inferred axioms (classifications, property assertions, SWRL rule results) into the same file.

**Inspecting in Protégé:**
- Open `ontology/KARMA_v014_live.owl` in Protégé to see the current live values
- Run `Reasoner > Pellet` to re-run the reasoner interactively
- Use `ontology/KARMA_v014_snapshot_*.owl` files to inspect a past session state

The original `ontology/KARMA_v014.owl` is **never modified** by the dashboard — only the live and snapshot files are written.

---

## Health State Logic

The inference rules are implemented in Python in `update_ontology.py`, mirroring the SWRL rules in the KARMA ontology:

| Rule | Condition | State |
|------|-----------|-------|
| S6 | `0 < Otr_acc ≤ 21.73` | 🟢 Healthy |
| S7 | `21.73 < Otr_acc ≤ 23.85` | 🟡 Alert |
| S8 | `Otr_acc > 23.85` | 🔴 Alarm |
| S9 | `Otr_acc = 0` AND coil changing | 🟢 Healthy |
| S10 | `Otr_acc = 0` AND coil NOT changing AND `En_Production = True` | ⚫ Faulty |
| — | `Otr_acc = 0` AND `En_Production = False` | ⬜ Stopped (normal) |

`En_Production` (`%MX102.6`) distinguishes a genuine fault (motor stopped during production) from a normal machine stop.

Coil changing is inferred from sensor signals:
- `Ent_bob_abou = True` AND `Ent_bob_cour = False` → coil is changing (S2)
- Any other combination → coil is not changing (S3/S4/S5)

When Alert or Alarm:
- `RotationalSpeedFlow` → deviation: `LessAccumulatorMotorShaftRotationalSpeed`
- `TorqueFlow` → deviation: `MoreAccumulatorMotorTorque`

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

Each document stores one or more changed variables:

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

---

## Known Issues & Notes

**Pellet reasoner:** `sync_reasoner_pellet` from owlready2 does not reliably return SWRL-inferred property values in Python — `motor.hasState` remains empty after reasoning despite Pellet executing successfully. The SWRL rules are therefore reimplemented natively in `update_ontology.py` as Python if/elif logic. Pellet is optionally used in the dashboard (toggle in sidebar) to reason the live ontology file in a background thread; results are saved to disk for inspection in Protégé.

**MongoDB change streams:** The real-time monitor uses polling mode by default (`--polling` flag). Change streams require a MongoDB replica set, which is not configured in the local standalone setup.

**Machine availability:** The TELMA machine is not always on. Use `simulate_data.py` for offline development and testing.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Audit & Setup | ✅ Done | Environment, connections, end-to-end pipeline |
| 2 — Real-time loop | ✅ Done | MongoDB polling monitor with state transitions |
| 4 — Interface | ✅ Done | Streamlit dashboard with live ontology and Pellet reasoning |

---

## References

- KARMA ontology: Dalena, A. et al. — CRAN / Politecnico di Milano
- Previous internship: Julie Galopeau, 2022–2023 (codebase reference)
- TELMA platform: https://www.cran.univ-lorraine.fr/plates-formes/telma/
- owlready2 documentation: https://owlready2.readthedocs.io/