"""
update_ontology.py
Reads the latest sensor values from MongoDB, updates the KARMA ontology
data properties, evaluates the SWRL rules via the SWRLEngine, and returns
the inferred health state.

Rules are read directly from the OWL file at startup. When the researcher
modifies rules in Protégé and saves the file, restart this script (or the
monitor) to pick up the changes — no Python edits required.

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
from pathlib import Path
from owlready2 import get_ontology, World

from swrl_engine import SWRLEngine


# ── Configuration ──────────────────────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY_PATH  = os.path.abspath(os.path.join(SCRIPT_DIR, "ontology", "KARMA_v014.owl"))
ONTOLOGY_URL   = Path(ONTOLOGY_PATH).as_uri()

MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"

INDIVIDUAL_OTR_ACC      = "Otr_acc"
INDIVIDUAL_ENT_BOB_COUR = "Ent_bob_cour"
INDIVIDUAL_ENT_BOB_ABOU = "Ent_bob_abou"
INDIVIDUAL_MOTOR        = "AccumulatorMotor"

# Initialise the engine once — rules are parsed from the OWL file here.
_engine = SWRLEngine(ONTOLOGY_PATH)


# ── MongoDB ────────────────────────────────────────────────────────────────────
def get_latest_values() -> dict:
    """Retrieves the most recent value for each monitored variable from MongoDB."""
    client     = pymongo.MongoClient(MONGO_URI)
    db         = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]

    variables = [
        # Core fault detection
        "Otr_acc", "Rfrd_acc", "Ent_bob_cour", "Ent_bob_abou", "En_Production",
        # Accumulator motor diagnostics
        "TempMoteur_acc", "Lcr_acc", "Uop_acc",
        "Courroie_accu_tendue", "Courroie_accu_detendue",
        # Advance motor
        "Otr_av", "Rfrd_av", "TempMoteur_av", "Lcr_av", "Uop_av",
        # Production counters
        "Cpt_nb_piece", "Cpt_nb_bobine", "Nombre_tours", "Dim_piece",
        # Electrical
        "CourantA", "CourantB", "CourantC", "CourantTot",
        # Safety
        "Ent_au",
        # Drive verification
        "diActTorque", "diActlVelo",
    ]
    latest = {}
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


# ── Inference ──────────────────────────────────────────────────────────────────
def infer_state(values: dict, verbose: bool = False) -> dict:
    """
    Loads the ontology, sets sensor values, runs all SWRL rules via
    SWRLEngine, and returns the full inference result dict.

    The engine reads rules from the OWL file, so any change the researcher
    makes in Protégé is automatically reflected after a restart.
    """
    otr_value     = float(values.get("Otr_acc", 0))
    horizontal    = bool(values.get("Ent_bob_cour", False))
    vertical      = bool(values.get("Ent_bob_abou", False))
    in_production = bool(values.get("En_Production", True))

    onto, _ = load_ontology()
    update_data_properties(onto, values, verbose=verbose)

    inferred = _engine.evaluate(onto)

    motor       = inferred.get(INDIVIDUAL_MOTOR, {})
    state_set   = motor.get("hasState", set())
    state       = next(iter(state_set)) if state_set else None

    # Collect deviations: {flow_name: deviation_name}
    deviations = {}
    for ind, props in inferred.items():
        devs = props.get("hasDeviation", set())
        if devs:
            deviations[ind] = next(iter(devs))

    failure_states = list(motor.get("hasFailureState", set()))
    functions      = list(motor.get("hasFunction", set()))

    is_coil_changing = vertical and not horizontal

    if verbose:
        print(f"  Coil isChanging = {is_coil_changing} "
              f"(horizontal={horizontal}, vertical={vertical})")
        print(f"  En_Production   = {in_production}")
        print(f"  SWRL inferred   : {inferred}")

    return {
        "component":        INDIVIDUAL_MOTOR,
        "state":            state,
        "is_coil_changing": is_coil_changing,
        "in_production":    in_production,
        "deviations":       deviations,
        "failure_states":   failure_states,
        "functions":        functions,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "sensor_values": {
            "Otr_acc":       otr_value,
            "Ent_bob_cour":  horizontal,
            "Ent_bob_abou":  vertical,
            "En_Production": in_production,
        }
    }


# ── Pipeline ───────────────────────────────────────────────────────────────────
def run_pipeline(verbose: bool = False) -> dict:
    """
    Full pipeline:
      1. Read latest values from MongoDB
      2. Load ontology and update data properties
      3. Evaluate SWRL rules via SWRLEngine
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

    print(f"\n── Step 3: Evaluating SWRL rules ({len(_engine.rules)} rules) ──")
    result = infer_state(values, verbose=verbose)

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
