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

import time
import pymongo
from datetime import datetime, timezone
from opcua import Client


# ── Configuration ──────────────────────────────────────────────────────────────
OPC_SERVER_URL  = "opc.tcp://100.65.63.65:4840"
MONGO_URI       = "mongodb://localhost:27017/"
DATABASE_NAME   = "telma"
COLLECTION_NAME = "data"

SAMPLING_INTERVAL = 1.0

# Variables to monitor — (name, node_id, type)
# Node IDs confirmed from PLC embedded server (GVL_OPC namespace)
MONITORED_VARIABLES = [
    # ── Core fault detection ───────────────────────────────────────────────────
    ("Otr_acc",       "ns=2;s=Application.GVL_OPC.Otr_acc",       "Int16"),
    ("Rfrd_acc",      "ns=2;s=Application.GVL_OPC.Rfrd_acc",       "Int16"),
    ("Ent_bob_cour",  "ns=2;s=Application.GVL_OPC.Ent_bob_cour",   "Boolean"),
    ("Ent_bob_abou",  "ns=2;s=Application.GVL_OPC.Ent_bob_abou",   "Boolean"),
    ("En_Production", "ns=2;s=Application.GVL_OPC.En_Production",  "Boolean"),
    # ── Accumulator motor diagnostics ─────────────────────────────────────────
    ("TempMoteur_acc","ns=2;s=Application.GVL_OPC.TempMoteur_acc", "Int16"),
    ("Lcr_acc",       "ns=2;s=Application.GVL_OPC.Lcr_acc",        "Float"),
    ("Uop_acc",       "ns=2;s=Application.GVL_OPC.Uop_acc",        "Int16"),
    ("Courroie_accu_tendue",   "ns=2;s=Application.GVL_OPC.Courroie_accu_tendue",   "Boolean"),
    ("Courroie_accu_detendue", "ns=2;s=Application.GVL_OPC.Courroie_accu_detendue", "Boolean"),
    # ── Advance motor (useful for Phase 5 belt wear scenario) ─────────────────
    ("Otr_av",        "ns=2;s=Application.GVL_OPC.Otr_av",         "Int16"),
    ("Rfrd_av",       "ns=2;s=Application.GVL_OPC.Rfrd_av",        "Int16"),
    ("TempMoteur_av", "ns=2;s=Application.GVL.TempAvance",          "Float"),
    ("Lcr_av",        "ns=2;s=Application.GVL_OPC.Lcr_av",         "Float"),
    ("Uop_av",        "ns=2;s=Application.GVL_OPC.Uop_av",         "Int16"),
    # ── Production counters ────────────────────────────────────────────────────
    ("Cpt_nb_piece",  "ns=2;s=Application.GVL_OPC.Cpt_nb_piece",   "Int16"),
    ("Cpt_nb_bobine", "ns=2;s=Application.GVL_OPC.Cpt_nb_bobine",  "Int16"),
    ("Nombre_tours",  "ns=2;s=Application.GVL_OPC.Nombre_tours",   "Int16"),
    ("Dim_piece",     "ns=2;s=Application.GVL_OPC.Dim_piece",       "Int16"),
    # ── Electrical (powertag) ─────────────────────────────────────────────────
    ("CourantA",      "ns=2;s=Application.GVL.CourantA",            "Float"),
    ("CourantB",      "ns=2;s=Application.GVL.CourantB",            "Float"),
    ("CourantC",      "ns=2;s=Application.GVL.CourantC",            "Float"),
    ("CourantTot",    "ns=2;s=Application.GVL_OPC.CourantTot",      "Float"),
    # ── Safety ────────────────────────────────────────────────────────────────
    ("Ent_au",        "ns=2;s=Application.GVL_OPC.Ent_au",          "Boolean"),
    # ── Raw drive values (scale factor verification) ──────────────────────────
    ("diActTorque",   "ns=2;s=Application.GVL_ATV320_Accu.diActTorque", "Int16"),
    ("diActlVelo",    "ns=2;s=Application.GVL_ATV320_Accu.diActlVelo",  "Int16"),
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


def is_connected(opc_client: Client) -> bool:
    """Check if the OPC-UA client connection is still alive."""
    try:
        opc_client.get_node("i=84").get_browse_name()
        return True
    except Exception:
        return False


def reconnect(opc_client: Client) -> Client:
    """Attempt to disconnect cleanly and create a fresh client."""
    try:
        opc_client.disconnect()
    except Exception:
        pass
    new_client = Client(OPC_SERVER_URL)
    new_client.session_timeout = 30000
    new_client.connect()
    return new_client


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
    Main collection loop. Reads variables every SAMPLING_INTERVAL seconds
    and stores changed values in MongoDB.

    Args:
        duration_seconds: how long to collect. None = run until Ctrl+C.
        csv_output:       deprecated — ignored. Use the Data Explorer tab
                          in the dashboard or MongoDB Compass to export data.
    """
    if csv_output is not None:
        import warnings
        warnings.warn(
            "csv_output is deprecated and ignored. Data is stored in MongoDB only. "
            "Use the dashboard Data Explorer tab or MongoDB Compass to export CSV.",
            DeprecationWarning, stacklevel=2
        )

    print(f"Connecting to OPC-UA server: {OPC_SERVER_URL}")
    print("(Make sure AIPL VPN is connected)\n")

    MAX_CONNECT_RETRIES = 5
    RETRY_DELAY         = 5

    # ── Connect with retry ─────────────────────────────────────────────────────
    opc_client = Client(OPC_SERVER_URL)
    opc_client.session_timeout = 30000

    for attempt in range(1, MAX_CONNECT_RETRIES + 1):
        try:
            opc_client.connect()
            print("✓ OPC-UA connected\n")
            break
        except Exception as e:
            if "BadTooManySessions" in str(e):
                print(f"  Server session limit reached (attempt {attempt}/{MAX_CONNECT_RETRIES}).")
                if attempt < MAX_CONNECT_RETRIES:
                    print(f"  Waiting {RETRY_DELAY}s for sessions to expire...")
                    time.sleep(RETRY_DELAY)
                    opc_client = Client(OPC_SERVER_URL)
                    opc_client.session_timeout = 30000
                else:
                    raise RuntimeError(
                        f"Could not connect after {MAX_CONNECT_RETRIES} attempts. "
                        "Wait ~30s for old sessions to expire, then try again."
                    ) from e
            else:
                raise

    # ── Main loop ──────────────────────────────────────────────────────────────
    try:
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

            # Check connection health and reconnect if needed
            if not is_connected(opc_client):
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] Connection lost — reconnecting...")
                try:
                    opc_client = reconnect(opc_client)
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] Reconnected.")
                except Exception as e:
                    print(f"  Reconnect failed: {e} — retrying in 5s...")
                    time.sleep(5)
                    continue

            current_values = read_all_variables(opc_client)
            changed        = has_changed(current_values, previous_values)

            if changed:
                store_in_mongodb(changed)
                previous_values.update(changed)
                changed_names = list(changed.keys())
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] Changed: {changed_names}")

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
        try:
            opc_client.disconnect()
            print("  OPC-UA disconnected.")
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Optional duration argument — if omitted, runs until Ctrl+C
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else None
    collect(duration_seconds=duration)