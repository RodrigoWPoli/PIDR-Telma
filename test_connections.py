"""
test_connections.py
Run this first to verify your environment is correctly set up.
Checks: MongoDB connection, OPC-UA server reachability, owlready2 + Java (Pellet).

Usage:
    python test_connections.py
"""

import sys

print("=" * 55)
print("TELMA Project — Connection & Environment Test")
print("=" * 55)

# ── 1. Python version ──────────────────────────────────────
print(f"\n[1] Python version: {sys.version}")

# ── 2. MongoDB ─────────────────────────────────────────────
print("\n[2] Testing MongoDB connection...")
try:
    import pymongo
    # TODO: replace with actual connection string if different
    client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=3000)
    client.server_info()
    print("    ✓ MongoDB connected")
    print(f"    Databases: {client.list_database_names()}")
except Exception as e:
    print(f"    ✗ MongoDB connection failed: {e}")
    print("    → Is MongoDB running? Try: sudo systemctl start mongod")
    print("    → Not installed? Run: bash setup_mongodb.sh")

# ── 3. OPC-UA server ping ───────────────────────────────────
print("\n[3] Testing OPC-UA server reachability (ping only)...")
import subprocess
result = subprocess.run(
    ["ping", "-c", "1", "-W", "2", "100.65.63.87"],
    capture_output=True
)
if result.returncode == 0:
    print("    ✓ OPC-UA server host reachable (100.65.63.87)")
    print("    → VPN appears to be connected")
else:
    print("    ✗ OPC-UA server host NOT reachable (100.65.63.87)")
    print("    → Connect the AIPL VPN first")

# ── 4. OPC-UA library ──────────────────────────────────────
print("\n[4] Testing opcua library...")
try:
    from opcua import Client
    print("    ✓ opcua library available")

    # Only attempt full connection if host was reachable
    if result.returncode == 0:
        print("    Attempting OPC-UA connection...")
        try:
            opc_client = Client("opc.tcp://100.65.63.87:49152/OPCUAServerExpert")
            opc_client.connect()
            print("    ✓ OPC-UA connected successfully")
            opc_client.disconnect()
        except Exception as e:
            print(f"    ✗ OPC-UA connection failed: {e}")
    else:
        print("    (skipped — host not reachable)")
except ImportError:
    print("    ✗ opcua not installed. Run: pip install opcua")

# ── 5. owlready2 ───────────────────────────────────────────
print("\n[5] Testing owlready2...")
try:
    import owlready2
    import importlib.metadata
    try:
        version = importlib.metadata.version("owlready2")
    except Exception:
        version = "unknown"
    print(f"    ✓ owlready2 installed (version: {version})")

    # Try loading the ontology
    try:
        import os
        _onto_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ontology", "KARMA_v014.owl")
        onto = owlready2.get_ontology(
            f"file://{_onto_path}"
        ).load()
        classes = list(onto.classes())
        individuals = list(onto.individuals())
        print(f"    ✓ Ontology loaded: {len(classes)} classes, {len(individuals)} individuals")
    except Exception as e:
        print(f"    ✗ Ontology load failed: {e}")

except ImportError:
    print("    ✗ owlready2 not installed. Run: pip install owlready2")

# ── 6. Java (needed for Pellet reasoner) ───────────────────
print("\n[6] Testing Java (required for Pellet reasoner)...")
java_result = subprocess.run(
    ["java", "-version"],
    capture_output=True, text=True
)
if java_result.returncode == 0:
    version_line = java_result.stderr.split("\n")[0]
    print(f"    ✓ Java found: {version_line}")
    if "64-Bit" in java_result.stderr:
        print("    ✓ 64-bit Java confirmed")
    else:
        print("    ⚠ Could not confirm 64-bit — Pellet requires 64-bit Java")
else:
    print("    ✗ Java not found")
    print("    → Install with: sudo dnf install java-17-openjdk")

# ── Summary ────────────────────────────────────────────────
print("\n" + "=" * 55)
print("Run this script again after fixing any ✗ items above.")
print("=" * 55)