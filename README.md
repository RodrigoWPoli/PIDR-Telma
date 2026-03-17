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
4. Outputting the inferred health state: **Healthy / Alert / Alarm / Faulty**

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
├── ontology_builder.py         # API for dynamically extending the ontology
├── test_ontology_builder.py    # Tests for ontology_builder.py
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

The dashboard auto-refreshes every 2 seconds and shows the current health state, torque chart, failure chain, signal status, and state history.

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

## Extending the Ontology

Use `ontology_builder.py` to add new components, failure chains, or sensors without editing the OWL file in Protégé:

```python
from ontology_builder import OntologyBuilder

ob = OntologyBuilder("ontology/KARMA_v014.owl")

# Add a new failure scenario
ob.add_failure_chain(
    cause_name            = "BeltWearByFriction",
    cause_class           = "PrimaryFailureCause",
    mode_name             = "BeltDeterioration",
    mode_class            = "MechanicalFailureMode",
    occurs_in             = "AccumulatorMotor",
    results_in_deviations = ["LessBeltTension", "MoreAdvanceMotorTorque"],
    deviation_classes     = ["Negative", "Positive"]
)

ob.add_sensor("SQ30", installed_on="AccumulatorMotor",
              measures_variable="Otr_av")

ob.save("ontology/KARMA_v014_updated.owl")
ob.summary()
```

---

## Known Issues & Notes

**Pellet reasoner not used in pipeline:** `sync_reasoner_pellet` from owlready2 does not reliably return SWRL-inferred property values in Python — `motor.hasState` remains empty after reasoning despite Pellet executing successfully. The SWRL rules are therefore reimplemented natively in `update_ontology.py` as Python if/elif logic. The ontology is still loaded and data properties are updated on every cycle (making it a live data store), but inference happens in Python. This is a known owlready2 limitation documented in its issue tracker. The Python rules are semantically identical to the SWRL rules in the ontology.

**MongoDB change streams:** The real-time monitor uses polling mode by default (`--polling` flag). Change streams require a MongoDB replica set, which is not configured in the local standalone setup.

**Machine availability:** The TELMA machine is not always on. Use `simulate_data.py` for offline development and testing.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Audit & Setup | ✅ Done | Environment, connections, end-to-end pipeline |
| 2 — Real-time loop | ✅ Done | MongoDB polling monitor with state transitions |
| 3 — Dynamic ontology | ✅ Done | `ontology_builder.py` API |
| 4 — Interface | ✅ Done | Streamlit dashboard |
| 5 — New failure scenario | ⏳ Stretch | Second failure scenario using Phase 3 API |

---

## References

- KARMA ontology: Dalena, A. et al. — CRAN / Politecnico di Milano
- Previous internship: Julie Galopeau, 2022–2023 (codebase reference)
- TELMA platform: https://www.cran.univ-lorraine.fr/plates-formes/telma/
- owlready2 documentation: https://owlready2.readthedocs.io/