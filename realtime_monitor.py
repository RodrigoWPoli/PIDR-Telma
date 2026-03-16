"""
realtime_monitor.py
Watches MongoDB for new sensor readings and runs the inference pipeline
on each new document. Prints the inferred health state in real time.

Uses MongoDB change streams — fires instantly on new inserts,
no polling delay.

Usage:
    python3 realtime_monitor.py                  # monitor indefinitely
    python3 realtime_monitor.py --timeout 60     # stop after 60s of no new data
    python3 realtime_monitor.py --quiet          # only print state changes

Run alongside data_collection.py or simulate_data.py:
    Terminal 1: python3 realtime_monitor.py
    Terminal 2: python3 data_collection.py 120
"""

import argparse
import time
import pymongo
from datetime import datetime, timezone
from update_ontology import load_ontology, update_data_properties, infer_state


# ── Configuration ──────────────────────────────────────────────────────────────
MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"

# Variables extracted from each MongoDB document
WATCHED_VARIABLES = ["Otr_acc", "Rfrd_acc", "Ent_bob_cour", "Ent_bob_abou"]

# Visual indicators for each state
STATE_DISPLAY = {
    "Healthy": "🟢 HEALTHY",
    "Alert":   "🟡 ALERT  ",
    "Alarm":   "🔴 ALARM  ",
    "Faulty":  "⚫ FAULTY ",
    None:      "⬜ UNKNOWN",
}


# ── Document parsing ───────────────────────────────────────────────────────────
def extract_values_from_doc(doc: dict) -> dict:
    """Extract variable values from a MongoDB document."""
    values = {}
    for var in WATCHED_VARIABLES:
        if var in doc:
            values[var] = doc[var]["value"]
    return values


def merge_with_previous(new_values: dict, previous: dict) -> dict:
    """Merge new values with previously known values to get complete state."""
    merged = dict(previous)
    merged.update(new_values)
    return merged


# ── Display ────────────────────────────────────────────────────────────────────
def print_result(result: dict, doc_count: int, quiet: bool = False,
                 previous_state: str = None) -> None:
    """Print the inference result. In quiet mode, only print on state change."""
    state = result["state"]
    is_change = (state != previous_state)

    if quiet and not is_change:
        return

    ts  = datetime.now().strftime("%H:%M:%S")
    otr = result["sensor_values"].get("Otr_acc", "?")
    display = STATE_DISPLAY.get(state, "⬜ UNKNOWN")

    if is_change and previous_state is not None:
        print(f"\n  {'─'*50}")
        print(f"  ⚡ STATE CHANGE: {STATE_DISPLAY.get(previous_state)} → {display}")
        print(f"  {'─'*50}\n")

    print(f"  [{ts}] #{doc_count:04d}  {display}  "
          f"Otr_acc={otr:<6}  "
          f"CoilChanging={result['is_coil_changing']}", end="")

    if result["deviations"] and not quiet:
        dev_names = list(result["deviations"].values())
        print(f"\n            Deviations: {dev_names}", end="")

    if result["failure_states"]:
        print(f"\n            ⚠ Failures: {result['failure_states']}", end="")

    print()


# ── Main monitor loop ──────────────────────────────────────────────────────────
def monitor(timeout_seconds: int = None, quiet: bool = False) -> None:
    """
    Watches MongoDB for new documents and runs inference on each one.

    Args:
        timeout_seconds: stop if no new document arrives within this many seconds.
                         None means run indefinitely.
        quiet:           only print when health state changes.
    """
    client     = pymongo.MongoClient(MONGO_URI)
    db         = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]

    # Pre-load ontology once (reused across all documents)
    print("Loading ontology...")
    onto, _ = load_ontology()
    print("✓ Ontology loaded\n")

    # Get current state from latest MongoDB values as starting point
    previous_values = {}
    previous_state  = None
    doc_count       = 0

    # Seed with latest known values
    for var in WATCHED_VARIABLES:
        doc = collection.find_one(
            {var: {"$exists": True}},
            sort=[(var + ".SourceTimestamp", pymongo.DESCENDING)]
        )
        if doc and var in doc:
            previous_values[var] = doc[var]["value"]

    if previous_values:
        result = infer_state(previous_values)
        previous_state = result["state"]
        print(f"Initial state from existing data:")
        print_result(result, 0, quiet=False)
        print()

    print(f"Watching for new data... (Ctrl+C to stop)\n")
    print(f"  {'─'*60}")

    # Watch for new inserts using change streams
    pipeline = [{"$match": {"operationType": "insert"}}]

    try:
        with collection.watch(pipeline, full_document="updateLookup") as stream:
            last_event_time = time.time()

            for change in stream:
                doc = change.get("fullDocument", {})
                if not doc:
                    continue

                doc_count += 1
                new_values = extract_values_from_doc(doc)

                if not new_values:
                    continue

                # Merge with previously known values
                current_values = merge_with_previous(new_values, previous_values)
                previous_values = current_values

                # Update ontology data properties
                update_data_properties(onto, current_values)

                # Run inference
                result = infer_state(current_values)

                # Display
                print_result(result, doc_count, quiet=quiet,
                             previous_state=previous_state)

                previous_state  = result["state"]
                last_event_time = time.time()

                # Timeout check
                if timeout_seconds and (time.time() - last_event_time > timeout_seconds):
                    print(f"\nNo new data for {timeout_seconds}s — stopping.")
                    break

    except KeyboardInterrupt:
        print(f"\n\nMonitor stopped. Processed {doc_count} documents.")
        print(f"Final state: {STATE_DISPLAY.get(previous_state)}")

    except pymongo.errors.PyMongoError as e:
        print(f"\nMongoDB error: {e}")
        print("Note: Change streams require MongoDB replica set or Atlas.")
        print("Falling back to polling mode...")
        monitor_polling(onto, timeout_seconds, quiet)

    finally:
        client.close()


def monitor_polling(onto, timeout_seconds: int = None,
                    quiet: bool = False, interval: float = 1.0) -> None:
    """
    Fallback polling monitor if change streams are not available
    (e.g. standalone MongoDB without replica set).
    Checks for new documents every `interval` seconds.
    """
    client     = pymongo.MongoClient(MONGO_URI)
    db         = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]

    print(f"Polling every {interval}s for new data... (Ctrl+C to stop)\n")
    print(f"  {'─'*60}")

    previous_values = {}
    previous_state  = None
    last_id         = None
    doc_count       = 0

    # Find the current latest document ID as starting point
    latest = collection.find_one(sort=[("_id", pymongo.DESCENDING)])
    if latest:
        last_id = latest["_id"]

    try:
        while True:
            # Find all documents newer than last_id
            query = {"_id": {"$gt": last_id}} if last_id else {}
            new_docs = list(collection.find(query).sort("_id", pymongo.ASCENDING))

            for doc in new_docs:
                doc_count += 1
                last_id    = doc["_id"]

                new_values = extract_values_from_doc(doc)
                if not new_values:
                    continue

                current_values  = merge_with_previous(new_values, previous_values)
                previous_values = current_values

                update_data_properties(onto, current_values)
                result = infer_state(current_values)

                print_result(result, doc_count, quiet=quiet,
                             previous_state=previous_state)
                previous_state = result["state"]

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\nMonitor stopped. Processed {doc_count} documents.")
        print(f"Final state: {STATE_DISPLAY.get(previous_state)}")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Real-time TELMA fault detection monitor"
    )
    parser.add_argument("--timeout",  type=int, default=None,
                        help="Stop after N seconds of no new data")
    parser.add_argument("--quiet",    action="store_true",
                        help="Only print on state change")
    parser.add_argument("--polling",  action="store_true",
                        help="Force polling mode instead of change streams")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Polling interval in seconds (default: 1.0)")
    args = parser.parse_args()

    if args.polling:
        print("Loading ontology...")
        onto, _ = load_ontology()
        print("✓ Ontology loaded\n")
        monitor_polling(onto, args.timeout, args.quiet, args.interval)
    else:
        monitor(args.timeout, args.quiet)
