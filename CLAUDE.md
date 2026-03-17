# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Real-time industrial fault detection for the **TELMA unwinding press** at CRAN (Université de Lorraine). The system monitors the **AccumulatorMotor** bearing health by reading `Otr_acc` (motor torque) from an OPC-UA server, storing readings in MongoDB, and evaluating SWRL-based rules against the **KARMA ontology** (OWL) to output one of five health states: Healthy / Alert / Alarm / Faulty / Stopped.

## Commands

### Environment setup
```bash
pip install -r requirements.txt           # owlready2, pymongo, opcua
python3 test_connections.py               # verify all 6 dependencies (MongoDB, OPC-UA, Java, etc.)
```

### Run inference
```bash
python3 update_ontology.py --verbose      # one-shot inference on latest MongoDB value
```

### Offline development (no VPN / no machine)
```bash
python3 simulate_data.py --clear          # clear MongoDB and insert ~90 synthetic documents
python3 realtime_monitor.py --polling     # start monitor in polling mode (required for standalone MongoDB)
```

### Real machine data (VPN required)
```bash
python3 data_collection.py 300            # collect for 5 minutes from OPC-UA server
```

### Tests
```bash
python3 test_ontology_builder.py          # tests OntologyBuilder API (self-cleaning, no pytest needed)
python3 test_connections.py               # environment / connectivity checks
```

## Architecture

The system is a pipeline of four stages:

```
OPC-UA server ──► data_collection.py ──► MongoDB (telma.data)
                                              │
                    simulate_data.py ─────────┘
                                              │
                                    realtime_monitor.py
                                              │
                                    update_ontology.py  ◄── ontology/KARMA_v014.owl
                                    (SWRL rules in Python)
                                              │
                                    health state output
```

**`update_ontology.py`** is the inference core. It:
1. Reads the latest per-variable values from MongoDB (each document stores only the variables that changed in that OPC-UA subscription cycle)
2. Loads `KARMA_v014.owl` into an owlready2 `World` and sets data properties on the `Otr_acc`, `Ent_bob_cour`, `Ent_bob_abou` individuals
3. Evaluates SWRL rules S2–S10 natively in Python (Pellet reasoner is not used for inference — see Known Issues)
4. Returns a result dict with `state`, `deviations`, `failure_states`, `functions`

**`realtime_monitor.py`** imports `infer_state`, `load_ontology`, `update_data_properties` from `update_ontology.py`. It loads the ontology once, then watches MongoDB for new inserts and runs inference on each document, merging partial updates with the previously known full state.

**`ontology_builder.py`** provides an API (`OntologyBuilder`) for programmatically extending the KARMA ontology — adding components, sensors, variables, failure causes, failure modes, and deviations — without editing the OWL file. The ontology is never modified in-place; `save()` writes a new file.

## Key Configuration

All thresholds and connection strings are constants at the top of each file:

| Constant | File | Value |
|---|---|---|
| `ALERT_THRESHOLD` | `update_ontology.py`, `simulate_data.py` | 21.73 |
| `ALARM_THRESHOLD` | `update_ontology.py`, `simulate_data.py` | 23.85 |
| `MONGO_URI` | all files | `mongodb://localhost:27017/` |
| `SCALE_FACTOR` | `simulate_data.py` | 1.0 (may need 0.01 once real data confirmed) |
| OPC-UA server | `data_collection.py` | `opc.tcp://100.65.63.87:49152/OPCUAServerExpert` (AIPL VPN required) |

## MongoDB Document Schema

Each document stores only the variables that changed in the OPC-UA subscription cycle:
```json
{
  "Otr_acc": { "value": 22, "SourceTimestamp": "2026-03-13T17:30:00+00:00" },
  "Ent_bob_cour": { "value": true, "SourceTimestamp": "2026-03-13T17:30:00+00:00" }
}
```
The monitor merges partial documents with the last known complete state before running inference.

## Known Issues

- **Pellet reasoner**: `sync_reasoner_pellet` does not reliably return inferred property values via owlready2. SWRL rules S2–S10 are reimplemented natively in `update_ontology.py`. The ontology is still loaded and updated to maintain the semantic layer.
- **Change streams**: Require a MongoDB replica set. The local setup is standalone, so `--polling` mode is the default for development. Change streams are attempted first; if they fail, the monitor falls back to polling.
- **`Otr_acc` scale factor**: The OPC-UA server returns `Int16`. Thresholds (21.73, 23.85) assume real-unit values. If the machine returns 2173 instead of 21.73, set `SCALE_FACTOR = 0.01` in `simulate_data.py` and divide accordingly in `update_ontology.py`.
- **Machine availability**: The TELMA machine is not always on — use `simulate_data.py` for all offline development.
