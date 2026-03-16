"""
test_ontology_builder.py
Tests the OntologyBuilder API by adding a second failure scenario
(belt wear on the advance motor) to the KARMA ontology.

This mirrors the structure of the existing bearing deterioration scenario
but for a different component — verifying the builder works generically.

Usage:
    python3 test_ontology_builder.py
"""

import os
from ontology_builder import OntologyBuilder, OntologyBuilderError


ONTOLOGY_INPUT  = "ontology/KARMA_v014.owl"
ONTOLOGY_OUTPUT = "ontology/KARMA_v014_extended.owl"


def test_add_belt_wear_scenario():
    print("=" * 55)
    print("Test: Adding belt wear failure scenario")
    print("=" * 55 + "\n")

    ob = OntologyBuilder(ONTOLOGY_INPUT)

    # ── 1. Add a new variable for the advance motor torque ────────────────────
    print("── Adding variable ──────────────────────────────────────")
    ob.add_variable(
        name            = "Otr_av",
        measure_of      = "AccumulatorMotor",   # reuse existing component for test
        alert_threshold = 19.5,
        alarm_threshold = 22.0,
        comment         = "Advance motor torque"
    )

    # ── 2. Add a complete failure chain in one call ───────────────────────────
    print("\n── Adding failure chain ─────────────────────────────────")
    ob.add_failure_chain(
        cause_name            = "BeltWearByFrictionAndFatigue",
        cause_class           = "PrimaryFailureCause",
        mode_name             = "BeltDeterioration",
        mode_class            = "MechanicalFailureMode",
        occurs_in             = "AccumulatorMotor",
        results_in_deviations = ["LessBeltTension", "MoreAdvanceMotorTorque"],
        deviation_classes     = ["Negative", "Positive"]
    )

    # ── 3. Add a sensor ───────────────────────────────────────────────────────
    print("\n── Adding sensor ────────────────────────────────────────")
    ob.add_sensor(
        name              = "SQ30",
        installed_on      = "AccumulatorMotor",
        measures_variable = "Otr_av",
        comment           = "Advance motor torque sensor"
    )

    # ── 4. Verify the new individuals exist ───────────────────────────────────
    print("\n── Verifying new individuals ────────────────────────────")
    checks = [
        ("Otr_av",                     "Variable added"),
        ("BeltWearByFrictionAndFatigue","PrimaryFailureCause added"),
        ("BeltDeterioration",           "FailureMode added"),
        ("LessBeltTension",             "Negative deviation added"),
        ("MoreAdvanceMotorTorque",       "Positive deviation added"),
        ("SQ30",                        "Sensor added"),
    ]
    all_ok = True
    for name, description in checks:
        try:
            ind = ob.get_individual(name)
            print(f"  ✓ {description}: {ind.name}")
        except OntologyBuilderError:
            print(f"  ✗ FAILED: {description} — '{name}' not found")
            all_ok = False

    # ── 5. Test validation (should raise errors) ──────────────────────────────
    print("\n── Testing input validation ─────────────────────────────")

    # Duplicate name
    try:
        ob.add_variable("Otr_av", "AccumulatorMotor", 10.0, 20.0)
        print("  ✗ Duplicate name check FAILED (should have raised error)")
        all_ok = False
    except OntologyBuilderError as e:
        print(f"  ✓ Duplicate name correctly rejected: {e}")

    # Invalid threshold order
    try:
        ob.add_variable("TestVar", "AccumulatorMotor",
                        alert_threshold=25.0, alarm_threshold=10.0)
        print("  ✗ Invalid threshold check FAILED (should have raised error)")
        all_ok = False
    except OntologyBuilderError as e:
        print(f"  ✓ Invalid thresholds correctly rejected: {e}")

    # Invalid failure mode class
    try:
        ob.add_failure_mode("TestMode", mode_class="InvalidClass")
        print("  ✗ Invalid class check FAILED (should have raised error)")
        all_ok = False
    except OntologyBuilderError as e:
        print(f"  ✓ Invalid class correctly rejected: {e}")

    # Non-existent individual reference
    try:
        ob.add_component("TestComp", part_of="NonExistentUnit", id_value="X1")
        print("  ✗ Non-existent reference check FAILED (should have raised error)")
        all_ok = False
    except OntologyBuilderError as e:
        print(f"  ✓ Non-existent reference correctly rejected: {e}")

    # ── 6. List existing components ───────────────────────────────────────────
    print("\n── Existing components in ontology ──────────────────────")
    components = ob.list_individuals("Component")
    for c in components:
        print(f"  - {c}")

    # ── 7. Save extended ontology ─────────────────────────────────────────────
    print("\n── Saving ───────────────────────────────────────────────")
    ob.save(ONTOLOGY_OUTPUT)
    ob.summary()

    # ── 8. Verify saved file loads correctly ──────────────────────────────────
    print("\n── Verifying saved file ─────────────────────────────────")
    ob2 = OntologyBuilder(ONTOLOGY_OUTPUT)
    try:
        ind = ob2.get_individual("BeltDeterioration")
        print(f"  ✓ Saved ontology loads correctly — BeltDeterioration found")
    except OntologyBuilderError:
        print(f"  ✗ Saved ontology missing BeltDeterioration")
        all_ok = False

    print(f"\n{'='*55}")
    if all_ok:
        print("✓ All tests passed")
    else:
        print("✗ Some tests failed — see output above")
    print(f"{'='*55}")

    # Clean up test output file
    if os.path.exists(ONTOLOGY_OUTPUT):
        os.remove(ONTOLOGY_OUTPUT)
        print(f"\n(Test output file {ONTOLOGY_OUTPUT} removed)")


if __name__ == "__main__":
    test_add_belt_wear_scenario()
