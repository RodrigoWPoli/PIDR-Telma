"""
update_ontology.py
Reads the latest sensor values from MongoDB, updates the KARMA ontology
data properties, evaluates the SWRL rules in Python, and returns the
inferred health state.
 
The SWRL rules are reimplemented directly in Python because owlready2's
Pellet integration does not reliably pull inferred property values back
into the Python object model. The logic is identical to the ontology rules.
 
Based on Julie Galopeau's internship report (2023).
Rebuilt for the 2025-2026 PIDR project.
 
Usage:
    python3 update_ontology.py
    python3 update_ontology.py --verbose
"""
 
import os
import argparse
import pymongo
from datetime import datetime, timezone
from owlready2 import get_ontology, World
 
 
# ── Configuration ──────────────────────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY_PATH  = os.path.abspath(os.path.join(SCRIPT_DIR, "ontology", "KARMA_v014.owl"))
ONTOLOGY_URL   = f"file://{ONTOLOGY_PATH}"
 
MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"
 
INDIVIDUAL_OTR_ACC      = "Otr_acc"
INDIVIDUAL_ENT_BOB_COUR = "Ent_bob_cour"
INDIVIDUAL_ENT_BOB_ABOU = "Ent_bob_abou"
INDIVIDUAL_MOTOR        = "AccumulatorMotor"
 
ALERT_THRESHOLD = 21.73
ALARM_THRESHOLD = 23.85
 
 
# ── MongoDB ────────────────────────────────────────────────────────────────────
def get_latest_values() -> dict:
    """Retrieves the most recent value for each monitored variable from MongoDB."""
    client     = pymongo.MongoClient(MONGO_URI)
    db         = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]
 
    variables = ["Otr_acc", "Rfrd_acc", "Ent_bob_cour", "Ent_bob_abou"]
    latest    = {}
    for var in variables:
        doc = collection.find_one(
            {var: {"$exists": True}},
            sort=[(var + ".SourceTimestamp", pymongo.DESCENDING)]
        )
        if doc and var in doc:
            latest[var] = doc[var]["value"]
 
    client.close()
    return latest
 
 
# ── Ontology ───────────────────────────────────────────────────────────────────
def load_ontology():
    """Loads the KARMA ontology into a fresh world."""
    if not os.path.exists(ONTOLOGY_PATH):
        raise FileNotFoundError(f"Ontology not found at: {ONTOLOGY_PATH}")
    world = World()
    onto  = world.get_ontology(ONTOLOGY_URL).load()
    return onto, world
 
 
def update_data_properties(onto, values: dict, verbose: bool = False) -> None:
    """Updates ontology data properties with latest sensor values."""
    with onto:
        if "Otr_acc" in values:
            otr = onto.search_one(iri=f"*#{INDIVIDUAL_OTR_ACC}")
            if otr is not None:
                otr.hasCurrentValue = [float(values["Otr_acc"])]
                if verbose:
                    print(f"  Set Otr_acc.hasCurrentValue = {float(values['Otr_acc'])}")
 
        if "Ent_bob_cour" in values:
            bob_cour = onto.search_one(iri=f"*#{INDIVIDUAL_ENT_BOB_COUR}")
            if bob_cour is not None:
                bob_cour.hasHorizontalPosition = [bool(values["Ent_bob_cour"])]
                if verbose:
                    print(f"  Set Ent_bob_cour.hasHorizontalPosition = {bool(values['Ent_bob_cour'])}")
 
        if "Ent_bob_abou" in values:
            bob_abou = onto.search_one(iri=f"*#{INDIVIDUAL_ENT_BOB_ABOU}")
            if bob_abou is not None:
                bob_abou.hasVerticalPosition = [bool(values["Ent_bob_abou"])]
                if verbose:
                    print(f"  Set Ent_bob_abou.hasVerticalPosition = {bool(values['Ent_bob_abou'])}")
 
 
# ── Python-native SWRL rule evaluation ────────────────────────────────────────
def evaluate_coil_changing(horizontal: bool, vertical: bool) -> bool:
    """
    Rules S2/S3/S4/S5: infer whether the coil is currently changing.
    S2: horizontal=False AND vertical=True  → isChanging = True
    S3: horizontal=True  AND vertical=True  → isChanging = False
    S4: horizontal=True  AND vertical=False → isChanging = False
    S5: horizontal=False AND vertical=False → isChanging = False
    """
    return (not horizontal) and vertical
 
 
def evaluate_health_state(otr_value: float,
                           is_coil_changing: bool,
                           verbose: bool = False) -> str:
    """
    Rules S6/S7/S8/S9/S10: infer the health state of the AccumulatorMotor.
    Returns one of: "Healthy", "Alert", "Alarm", "Faulty"
    """
    if otr_value == 0:
        if is_coil_changing:
            if verbose: print(f"  Rule S9: Otr=0 + coil changing → Healthy")
            return "Healthy"
        else:
            if verbose: print(f"  Rule S10: Otr=0 + coil NOT changing → Faulty")
            return "Faulty"
    elif 0 < otr_value <= ALERT_THRESHOLD:
        if verbose: print(f"  Rule S6: 0 < {otr_value} <= {ALERT_THRESHOLD} → Healthy")
        return "Healthy"
    elif ALERT_THRESHOLD < otr_value <= ALARM_THRESHOLD:
        if verbose: print(f"  Rule S7: {otr_value} in alert range → Alert")
        return "Alert"
    else:
        if verbose: print(f"  Rule S8: {otr_value} > {ALARM_THRESHOLD} → Alarm")
        return "Alarm"
 
 
def evaluate_deviations(state: str) -> dict:
    """Rules S1/S11: infer flow deviations when Alert or Alarm."""
    if state in ("Alert", "Alarm"):
        return {
            "RotationalSpeedFlow": "LessAccumulatorMotorShaftRotationalSpeed",
            "TorqueFlow":          "MoreAccumulatorMotorTorque",
        }
    return {}
 
 
def evaluate_failure_state(state: str) -> list:
    """Rule S10 head: Faulty → hasFailureState BearingNotWorking."""
    return ["BearingNotWorking"] if state == "Faulty" else []
 
 
def evaluate_functions(state: str) -> list:
    """Rule S6 head: Healthy → hasFunction motor function."""
    return ["AccumulatorMotorProvidesAdequateMechanicalRotationForBandAccumulation"] \
        if state == "Healthy" else []
 
 
def infer_state(values: dict, verbose: bool = False) -> dict:
    """Runs all Python-native SWRL rules and returns the full inference result."""
    otr_value  = float(values.get("Otr_acc", 0))
    horizontal = bool(values.get("Ent_bob_cour", False))
    vertical   = bool(values.get("Ent_bob_abou", False))
 
    is_coil_changing = evaluate_coil_changing(horizontal, vertical)
    if verbose:
        print(f"  Coil isChanging = {is_coil_changing} "
              f"(horizontal={horizontal}, vertical={vertical})")
 
    state          = evaluate_health_state(otr_value, is_coil_changing, verbose)
    deviations     = evaluate_deviations(state)
    failure_states = evaluate_failure_state(state)
    functions      = evaluate_functions(state)
 
    return {
        "component":        INDIVIDUAL_MOTOR,
        "state":            state,
        "is_coil_changing": is_coil_changing,
        "deviations":       deviations,
        "failure_states":   failure_states,
        "functions":        functions,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "sensor_values": {
            "Otr_acc":      otr_value,
            "Ent_bob_cour": horizontal,
            "Ent_bob_abou": vertical,
        }
    }
 
 
# ── Pipeline ───────────────────────────────────────────────────────────────────
def run_pipeline(verbose: bool = False) -> dict:
    """
    Full pipeline:
      1. Read latest values from MongoDB
      2. Load ontology and update data properties
      3. Evaluate SWRL rules in Python
      4. Return inference result
    """
    print("\n── Step 1: Reading latest values from MongoDB ───────────")
    values = get_latest_values()
    if not values:
        print("  ✗ No data found in MongoDB. Run simulate_data.py first.")
        return {}
    for k, v in values.items():
        print(f"  {k}: {v}")
 
    print("\n── Step 2: Loading ontology and updating data properties ─")
    onto, _ = load_ontology()
    print(f"  ✓ Loaded: {len(list(onto.classes()))} classes, "
          f"{len(list(onto.individuals()))} individuals")
    update_data_properties(onto, values, verbose=True)
 
    print("\n── Step 3: Evaluating rules (Python-native) ─────────────")
    result = infer_state(values, verbose=True)
 
    print("\n── Result ───────────────────────────────────────────────")
    print(f"  Component   : {result['component']}")
    print(f"  State       : {result['state']}")
    print(f"  CoilChanging: {result['is_coil_changing']}")
    print(f"  Deviations  : {result['deviations']}")
    print(f"  Failures    : {result['failure_states']}")
    print(f"  Functions   : {result['functions']}")
    print(f"  Timestamp   : {result['timestamp']}")
    print(f"  Values      : {result['sensor_values']}")
    print("─" * 55)
 
    return result
 
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_pipeline(verbose=args.verbose)
 