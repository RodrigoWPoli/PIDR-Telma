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
├── data/                       # Auto-created — CSV exports and collections
│
├── data_collection.py          # Reads OPC-UA server → stores in MongoDB
├── simulate_data.py            # Generates synthetic data for offline testing
├── update_ontology.py          # Loads ontology, evaluates rules, returns health state
├── realtime_monitor.py         # Watches MongoDB → runs inference on each new doc
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

### Run the real-time monitor
```bash
# Terminal 1 — start monitor
python3 realtime_monitor.py --polling

# Terminal 2 — feed data (real or simulated)
python3 data_collection.py 120
# or
python3 simulate_data.py
```

---

## Health State Logic

The inference rules are implemented in Python in `update_ontology.py`, mirroring the SWRL rules in the KARMA ontology:

| Rule | Condition | State |
|------|-----------|-------|
| S6 | `0 < Otr_acc ≤ 21.73` | 🟢 Healthy |
| S7 | `21.73 < Otr_acc ≤ 23.85` | 🟡 Alert |
| S8 | `Otr_acc > 23.85` | 🔴 Alarm |
| S9 | `Otr_acc = 0` AND coil changing | 🟢 Healthy |
| S10 | `Otr_acc = 0` AND coil NOT changing | ⚫ Faulty |

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

All variable node IDs follow the pattern `ns=2;s=0:TELMA!<VariableName>`.  
Full variable list: see `OPCUA_variables.csv` (ask supervisors for file location).

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

**Otr_acc scale factor:** The OPC-UA server returns `Otr_acc` as `Int16`. The ontology thresholds (21.73, 23.85) assume real-unit values. If the machine returns scaled integers (e.g. 2173 instead of 21.73), set `SCALE_FACTOR = 0.01` in `update_ontology.py`. Confirm with first real machine data collection.

**Pellet reasoner:** `sync_reasoner_pellet` from owlready2 does not reliably return inferred property values in Python. The SWRL rules are therefore reimplemented natively in `update_ontology.py`. The ontology is still loaded and data properties updated to maintain the semantic layer.

**MongoDB change streams:** The real-time monitor uses polling mode by default (`--polling` flag). Change streams require a MongoDB replica set, which is not configured in the local standalone setup.

**Machine availability:** The TELMA machine is not always on. Use `simulate_data.py` for offline development and testing.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Audit & Setup | ✅ Done | Environment, connections, end-to-end pipeline |
| 2 — Real-time loop | ✅ Done | MongoDB polling monitor with state transitions |
| 3 — Dynamic ontology | 🔄 In progress | `ontology_builder.py` API |
| 4 — Interface | ⏳ Planned | Streamlit dashboard |
| 5 — New failure scenario | ⏳ Stretch | Second failure scenario using Phase 3 API |

---

## References

- KARMA ontology: Dalena, A. et al. — CRAN / Politecnico di Milano
- Previous internship: Julie Galopeau, 2022–2023 (codebase reference)
- TELMA platform: https://www.cran.univ-lorraine.fr/plates-formes/telma/
- owlready2 documentation: https://owlready2.readthedocs.io/
