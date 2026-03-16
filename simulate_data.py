"""
simulate_data.py
Generates synthetic TELMA sensor data into MongoDB, mimicking what
data_collection.py would produce from the real OPC-UA server.

Simulates three scenarios in sequence:
  1. Healthy      — Otr_acc below alert threshold (21.73)
  2. Alert        — Otr_acc between alert and alarm (21.73 – 23.85)
  3. Alarm        — Otr_acc above alarm threshold (23.85)

Also simulates coil change events (Ent_bob_cour / Ent_bob_abou transitions).

Usage:
    python simulate_data.py              # runs full scenario
    python simulate_data.py --clear      # clears MongoDB first, then runs
"""

import argparse
import random
import time
import pymongo
from datetime import datetime, timezone, timedelta


# ── Config ─────────────────────────────────────────────────────────────────────
MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"

# Ontology thresholds (from KARMA ontology)
ALERT_THRESHOLD = 21.73
ALARM_THRESHOLD = 23.85

# NOTE on scaling: Otr_acc is Int16 on the OPC-UA server.
# Until confirmed against real data, we simulate values matching
# the ontology scale directly (i.e. the ontology thresholds are the real values).
# If real data shows e.g. 2173 instead of 21.73, update SCALE_FACTOR = 0.01
SCALE_FACTOR = 1.0  # update if needed once real machine data is observed


# ── MongoDB ─────────────────────────────────────────────────────────────────────
client     = pymongo.MongoClient(MONGO_URI)
db         = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]


def insert_reading(values: dict, timestamp: datetime = None) -> None:
    """Insert a simulated sensor reading into MongoDB."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    # Always include En_Production — default True (machine running)
    if "En_Production" not in values:
        values["En_Production"] = True
    doc = {}
    for name, value in values.items():
        doc[name] = {
            "value":           value,
            "SourceTimestamp": timestamp
        }
    collection.insert_one(doc)


def simulate_scenario(
    label: str,
    otr_range: tuple,
    rfrd_value: int,
    n_points: int,
    start_time: datetime,
    interval_seconds: float = 1.0
) -> datetime:
    """
    Simulates n_points readings for a given health state.
    Returns the timestamp after the last point.
    """
    print(f"\n  [{label}] Simulating {n_points} readings "
          f"(Otr_acc in {otr_range[0]:.2f}–{otr_range[1]:.2f})...")

    current_time = start_time
    for i in range(n_points):
        otr_value = round(random.uniform(*otr_range) / SCALE_FACTOR)

        values = {
            "Otr_acc":        int(otr_value),
            "Rfrd_acc":       rfrd_value,
            "Ent_bob_cour":   True,
            "Ent_bob_abou":   False,
            "En_Production":  True,
            "TempMoteur_acc": round(random.uniform(35.0, 45.0), 1),
            "Lcr_acc":        round(random.uniform(1.5, 2.5), 2),
        }
        insert_reading(values, current_time)
        current_time += timedelta(seconds=interval_seconds)

    print(f"    ✓ {n_points} documents inserted")
    return current_time


def simulate_coil_change(start_time: datetime, interval_seconds: float = 1.0) -> datetime:
    """
    Simulates a coil change event:
      - Machine stops (Otr_acc = 0, Rfrd_acc = 0)
      - Coil goes to changing position (Ent_bob_abou = True, Ent_bob_cour = False)
      - Then returns to normal (Ent_bob_cour = True, Ent_bob_abou = False)
    """
    print("\n  [CoilChange] Simulating coil change event (5 readings)...")
    current_time = start_time

    steps = [
        # Machine stopping
        {"Otr_acc": 0, "Rfrd_acc": 0, "Ent_bob_cour": True,  "Ent_bob_abou": False},
        # Coil rotating to change position
        {"Otr_acc": 0, "Rfrd_acc": 0, "Ent_bob_cour": False, "Ent_bob_abou": False},
        # Coil in change position (vertical)
        {"Otr_acc": 0, "Rfrd_acc": 0, "Ent_bob_cour": False, "Ent_bob_abou": True},
        # New coil loaded, returning
        {"Otr_acc": 0, "Rfrd_acc": 0, "Ent_bob_cour": False, "Ent_bob_abou": False},
        # Back to normal position
        {"Otr_acc": 0, "Rfrd_acc": 0, "Ent_bob_cour": True,  "Ent_bob_abou": False},
    ]

    for step in steps:
        step["En_Production"]  = True
        step["TempMoteur_acc"] = 38.0
        step["Lcr_acc"]        = 0.0
        insert_reading(step, current_time)
        current_time += timedelta(seconds=interval_seconds)

    print("    ✓ Coil change event inserted")
    return current_time


def run_full_simulation(clear_first: bool = False) -> None:
    """Runs the full bearing deterioration scenario simulation."""

    if clear_first:
        collection.drop()
        print("✓ MongoDB collection cleared")

    print("\n" + "=" * 55)
    print("TELMA Data Simulator — Bearing Deterioration Scenario")
    print("=" * 55)
    print(f"\nThresholds: Alert={ALERT_THRESHOLD}, Alarm={ALARM_THRESHOLD}")
    print(f"Scale factor: {SCALE_FACTOR}")
    print(f"Target collection: {DATABASE_NAME}.{COLLECTION_NAME}\n")

    # Start 1 hour ago so data looks historical
    start = datetime.now(timezone.utc) - timedelta(hours=1)

    # ── Phase 1: Healthy (30 readings, ~30 seconds of machine time) ────────────
    t = simulate_scenario(
        label      = "Healthy",
        otr_range  = (10.0, 19.0),
        rfrd_value = 1450,
        n_points   = 30,
        start_time = start
    )

    # ── Coil change during healthy phase ───────────────────────────────────────
    t = simulate_coil_change(t)

    # ── More healthy operation ─────────────────────────────────────────────────
    t = simulate_scenario(
        label      = "Healthy (continued)",
        otr_range  = (12.0, 20.0),
        rfrd_value = 1450,
        n_points   = 20,
        start_time = t
    )

    # ── Phase 2: Alert (bearing starting to deteriorate) ──────────────────────
    t = simulate_scenario(
        label      = "Alert",
        otr_range  = (21.73, 23.85),
        rfrd_value = 1450,
        n_points   = 20,
        start_time = t
    )

    # ── Phase 3: Alarm (significant bearing deterioration) ────────────────────
    t = simulate_scenario(
        label      = "Alarm",
        otr_range  = (23.85, 28.0),
        rfrd_value = 1450,
        n_points   = 10,
        start_time = t
    )

    # ── Phase 4: Zero reading while NOT changing coil → Faulty ────────────────
    print("\n  [Faulty] Simulating stopped motor during production (Otr_acc=0, coil not changing)...")
    for i in range(5):
        insert_reading({
            "Otr_acc":        0,
            "Rfrd_acc":       0,
            "Ent_bob_cour":   True,
            "Ent_bob_abou":   False,
            "En_Production":  True,   # still in production → Faulty
            "TempMoteur_acc": 55.0,
            "Lcr_acc":        0.0,
        }, t + timedelta(seconds=i))
    t += timedelta(seconds=5)
    print("    ✓ 5 faulty readings inserted")

    # ── Phase 5: Machine stopped normally → Stopped (not a fault) ─────────────
    print("\n  [Stopped] Simulating normal machine stop (En_Production=False)...")
    for i in range(5):
        insert_reading({
            "Otr_acc":        0,
            "Rfrd_acc":       0,
            "Ent_bob_cour":   True,
            "Ent_bob_abou":   False,
            "En_Production":  False,  # machine off → Stopped (normal)
            "TempMoteur_acc": 35.0,
            "Lcr_acc":        0.0,
        }, t + timedelta(seconds=i))
    print("    ✓ 5 stopped readings inserted")

    # ── Summary ────────────────────────────────────────────────────────────────
    total = collection.count_documents({})
    print(f"\n{'='*55}")
    print(f"✓ Simulation complete — {total} total documents in MongoDB")
    print(f"\nExpected ontology states in the data:")
    print(f"  Healthy  — Otr_acc in (0, {ALERT_THRESHOLD}]")
    print(f"  Alert    — Otr_acc in ({ALERT_THRESHOLD}, {ALARM_THRESHOLD}]")
    print(f"  Alarm    — Otr_acc > {ALARM_THRESHOLD}")
    print(f"  Faulty   — Otr_acc = 0 AND coil NOT changing AND En_Production = True")
    print(f"  Healthy  — Otr_acc = 0 AND coil IS changing (coil change event)")
    print(f"  Stopped  — Otr_acc = 0 AND En_Production = False (normal stop)")
    print(f"\nNext step: run realtime_monitor.py --polling in one terminal,")
    print(f"           then simulate_data.py --clear in another")
    print(f"{'='*55}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true",
                        help="Clear MongoDB collection before simulating")
    args = parser.parse_args()
    run_full_simulation(clear_first=args.clear)