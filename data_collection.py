"""
data_collection.py
Connects to the TELMA OPC-UA server, reads sensor values every second,
filters for changes, and stores them in MongoDB and optionally a CSV file.

Node IDs sourced from OPCUA_variables.csv (confirmed against TELMA server).
Based on Julie Galopeau's internship report (2023).
Rebuilt for the 2025-2026 PIDR project.

Requirements:
    - AIPL VPN connected
    - MongoDB running locally
    - pip install opcua pymongo
"""

import csv
import time
import pymongo
from datetime import datetime, timezone
from opcua import Client


# ── Configuration ──────────────────────────────────────────────────────────────
OPC_SERVER_URL  = "opc.tcp://100.65.63.87:49152/OPCUAServerExpert"
MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"

# Sampling interval in seconds
SAMPLING_INTERVAL = 1.0

# Variables to monitor — (name, node_id, type)
# Only storing the 4 variables needed for ontology population + a few useful extras
MONITORED_VARIABLES = [
    # Core variables for failure detection
    ("Otr_acc",       "ns=2;s=0:TELMA!Otr_acc",       "Int16"),   # Motor torque (WORD, %MW1)
    ("Rfrd_acc",      "ns=2;s=0:TELMA!Rfrd_acc",       "Int16"),   # Motor speed rpm (WORD, %MW2)
    ("Ent_bob_cour",  "ns=2;s=0:TELMA!Ent_bob_cour",   "Boolean"), # Coil current position (%MX101.4)
    ("Ent_bob_abou",  "ns=2;s=0:TELMA!Ent_bob_abou",   "Boolean"), # Coil changing position (%MX101.5)
    # Production state — helps distinguish normal stop from fault
    ("En_Production", "ns=2;s=0:TELMA!En_Production",  "Boolean"), # Production cycle running (%MX102.6)
    # Useful extras for diagnostics
    ("TempMoteur_acc","ns=2;s=0:TELMA!TempMoteur_acc",  "Float"),   # Motor temperature (REAL, %MD500)
    ("Lcr_acc",       "ns=2;s=0:TELMA!Lcr_acc",         "Float"),   # Motor current (REAL, %MD505)
    ("Courroie_accu_tendue",   "ns=2;s=0:TELMA!Courroie_accu_tendue",   "Boolean"), # Belt tensioned (%MX101.1)
    ("Courroie_accu_detendue", "ns=2;s=0:TELMA!Courroie_accu_detendue", "Boolean"), # Belt slack (%MX101.2)
]

VARIABLE_NAMES = [v[0] for v in MONITORED_VARIABLES]


# ── MongoDB setup ──────────────────────────────────────────────────────────────
mongo_client = pymongo.MongoClient(MONGO_URI)
db           = mongo_client[DATABASE_NAME]
collection   = db[COLLECTION_NAME]


def cast_value(value, var_type: str):
    """Cast a raw OPC-UA value to the correct Python type."""
    if var_type == "Int16":
        return int(value)
    elif var_type == "Float":
        return float(value)
    elif var_type == "Boolean":
        return bool(value)
    return value


def read_all_variables(opc_client: Client) -> dict:
    """Read current values of all monitored variables from OPC-UA server."""
    readings = {}
    for name, node_id, var_type in MONITORED_VARIABLES:
        try:
            node  = opc_client.get_node(node_id)
            value = cast_value(node.get_value(), var_type)
            readings[name] = {
                "value":           value,
                "SourceTimestamp": datetime.now(timezone.utc)
            }
        except Exception as e:
            print(f"  Warning: could not read {name}: {e}")
    return readings


def has_changed(current: dict, previous: dict) -> dict:
    """Returns only the variables whose value changed since last reading."""
    changed = {}
    for name, data in current.items():
        if name not in previous or previous[name]["value"] != data["value"]:
            changed[name] = data
    return changed


def store_in_mongodb(changed_data: dict) -> None:
    """Stores changed variable values as a single MongoDB document."""
    if not changed_data:
        return
    doc = {}
    for name, data in changed_data.items():
        doc[name] = {
            "value":           data["value"],
            "SourceTimestamp": data["SourceTimestamp"]
        }
    collection.insert_one(doc)


def collect(duration_seconds: int = None, csv_output: str = None) -> None:
    """
    Main collection loop. Reads variables every SAMPLING_INTERVAL seconds,
    stores changed values in MongoDB, and optionally writes to CSV.

    Args:
        duration_seconds: how long to collect data. None = run until Ctrl+C.
        csv_output:       optional path to CSV file for parallel storage
    """
    print(f"Connecting to OPC-UA server: {OPC_SERVER_URL}")
    print("(Make sure AIPL VPN is connected)\n")

    opc_client = Client(OPC_SERVER_URL)

    csv_file   = None
    csv_writer = None

    # Ensure output directory exists
    if csv_output:
        import os
        os.makedirs(os.path.dirname(csv_output), exist_ok=True)

    try:
        opc_client.connect()
        print("✓ OPC-UA connected\n")

        # Set up CSV if requested
        if csv_output:
            csv_file   = open(csv_output, "w", newline="")
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["timestamp"] + VARIABLE_NAMES)
            print(f"Writing CSV to: {csv_output}\n")

        previous_values = {}
        start_time      = time.time()
        end_time        = (start_time + duration_seconds) if duration_seconds else None

        if duration_seconds:
            print(f"Collecting for {duration_seconds}s... (Ctrl+C to stop early)\n")
        else:
            print(f"Collecting until stopped... (Ctrl+C to stop)\n")

        while True:
            if end_time and time.time() >= end_time:
                break

            loop_start = time.time()

            current_values = read_all_variables(opc_client)
            changed        = has_changed(current_values, previous_values)

            if changed:
                store_in_mongodb(changed)
                previous_values.update(changed)

                # Also write to CSV (full row, not just changed)
                if csv_writer:
                    row = [datetime.now(timezone.utc).isoformat()]
                    for name in VARIABLE_NAMES:
                        val = current_values.get(name, {}).get("value", "")
                        row.append(val)
                    csv_writer.writerow(row)

                changed_names = list(changed.keys())
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] Changed: {changed_names}")

            # Sleep for remainder of interval
            elapsed    = time.time() - loop_start
            sleep_time = max(0, SAMPLING_INTERVAL - elapsed)
            time.sleep(sleep_time)

        elapsed_total = time.time() - start_time
        print(f"\n✓ Collection complete ({elapsed_total:.1f}s)")
        print(f"  Documents stored in MongoDB: {collection.count_documents({})}")

    except KeyboardInterrupt:
        print("\nCollection stopped by user.")

    except Exception as e:
        print(f"\n✗ Error during collection: {e}")
        raise

    finally:
        if csv_file:
            csv_file.close()
        try:
            opc_client.disconnect()
            print("  OPC-UA disconnected.")
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import os

    # Optional duration argument — if omitted, runs until Ctrl+C
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir   = os.path.join(script_dir, "data")
    csv_path   = os.path.join(data_dir, f"collection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    collect(duration_seconds=duration, csv_output=csv_path)