"""
diagnose_reasoner.py
Runs the full pipeline and then dumps everything owlready2 knows about
key individuals after reasoning — to understand what Pellet actually inferred
and how to access it.
 
Usage:
    python diagnose_reasoner.py
"""
 
import os
import pymongo
from owlready2 import get_ontology, sync_reasoner_pellet, World, default_world
 
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "ontology", "KARMA_v014.owl"))
ONTOLOGY_URL  = f"file://{ONTOLOGY_PATH}"
 
MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"
 
 
def get_latest_values():
    client     = pymongo.MongoClient(MONGO_URI)
    db         = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]
    variables  = ["Otr_acc", "Ent_bob_cour", "Ent_bob_abou"]
    latest     = {}
    for var in variables:
        doc = collection.find_one(
            {var: {"$exists": True}},
            sort=[(var + ".SourceTimestamp", pymongo.DESCENDING)]
        )
        if doc and var in doc:
            latest[var] = doc[var]["value"]
    client.close()
    return latest
 
 
def dump_individual(ind, onto, label=""):
    """Print everything owlready2 knows about an individual."""
    print(f"\n{'─'*55}")
    print(f"Individual: {ind.name}  ({label})")
    print(f"  IRI: {ind.iri}")
    print(f"  Classes: {[c.name for c in ind.is_a]}")
    print(f"  INDIRECT classes: {[c.name for c in ind.INDIRECT_is_a if hasattr(c, 'name')]}")
 
    # All object properties
    print(f"\n  Object properties:")
    for prop in ind.get_properties():
        values = list(prop[ind])
        if values:
            val_names = [v.name if hasattr(v, 'name') else str(v) for v in values]
            print(f"    {prop.name}: {val_names}")
 
    # All data properties
    print(f"\n  Data properties:")
    for prop in onto.world.data_properties():
        try:
            vals = list(prop[ind])
            if vals:
                print(f"    {prop.name}: {vals}")
        except Exception:
            pass
 
 
def main():
    print("Loading ontology...")
    # Use a fresh world to avoid caching issues from previous runs
    from owlready2 import World
    world = World()
    onto = world.get_ontology(ONTOLOGY_URL).load()
    print(f"  ✓ Loaded: {len(list(onto.classes()))} classes, {len(list(onto.individuals()))} individuals")
 
    # Update data properties with latest MongoDB values
    values = get_latest_values()
    print(f"Using values: {values}")
 
    with onto:
        otr = onto.search_one(iri="*#Otr_acc")
        if otr and "Otr_acc" in values:
            otr.hasCurrentValue = [float(values["Otr_acc"])]
 
        bob_cour = onto.search_one(iri="*#Ent_bob_cour")
        if bob_cour and "Ent_bob_cour" in values:
            bob_cour.hasHorizontalPosition = [bool(values["Ent_bob_cour"])]
 
        bob_abou = onto.search_one(iri="*#Ent_bob_abou")
        if bob_abou and "Ent_bob_abou" in values:
            bob_abou.hasVerticalPosition = [bool(values["Ent_bob_abou"])]
 
    print("\nRunning Pellet reasoner...")
    with onto:
        sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
    print("Reasoner done.\n")
 
    # ── Dump key individuals ───────────────────────────────────────────────────
    individuals_to_check = [
        ("AccumulatorMotor",   "Component being monitored"),
        ("Otr_acc",            "Torque variable"),
        ("Ent_bob_cour",       "Coil horizontal sensor"),
        ("Ent_bob_abou",       "Coil vertical sensor"),
        ("Coil",               "Product (coil)"),
        ("RotationalSpeedFlow","Flow with deviations"),
        ("TorqueFlow",         "Flow with deviations"),
        ("BearingNotWorking",  "StateOfFailure"),
    ]
 
    for name, label in individuals_to_check:
        ind = onto.search_one(iri=f"*#{name}")
        if ind:
            dump_individual(ind, onto, label)
        else:
            print(f"\n  (individual '{name}' not found)")
 
    # ── List ALL inferred triples involving AccumulatorMotor ──────────────────
    print(f"\n\n{'='*55}")
    print("All individuals and their hasState values (raw SPARQL-style):")
    motor = onto.search_one(iri="*#AccumulatorMotor")
    if motor:
        print(f"\n  hasState property object:")
        has_state_prop = onto.search_one(iri="*#hasState")
        if has_state_prop:
            print(f"  prop found: {has_state_prop}")
            # Try direct attribute access
            print(f"  motor.hasState = {motor.hasState}")
        else:
            print("  hasState property not found in ontology Python namespace")
 
        # Try searching for all properties defined on this individual
        print(f"\n  All properties via get_properties():")
        for prop in motor.get_properties():
            vals = list(prop[motor])
            if vals:
                print(f"    {prop.name}: {[v.name if hasattr(v,'name') else v for v in vals]}")
 
    # ── Check if Coil.isChanging was inferred ──────────────────────────────────
    print(f"\n{'='*55}")
    print("Coil.isChanging check:")
    coil = onto.search_one(iri="*#Coil")
    if coil:
        is_changing_prop = onto.search_one(iri="*#isChanging")
        print(f"  isChanging prop: {is_changing_prop}")
        print(f"  coil.isChanging: {coil.isChanging}")
 
    print(f"\n{'='*55}")
    print("ProcessState individuals (needed by SWRL rules):")
    for ps_label in ["HealthyPS", "FAlertPS", "FAlarmPS", "SBPS", "CoilCPS"]:
        ps = onto.search_one(hasLabel=ps_label)
        print(f"  {ps_label}: {ps}")
 
 
if __name__ == "__main__":
    main()
 