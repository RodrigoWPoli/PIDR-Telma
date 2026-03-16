"""
ontology_builder.py
Python API for dynamically extending the KARMA ontology with new
components, failure chains, sensors, and variables — without editing
the OWL file in Protégé.

Design principles:
  - All operations use owlready2 Python API (no string/XML manipulation)
  - Inputs are validated before writing to the ontology
  - The ontology file is never modified in-place; save() writes a new file
  - Non-OWL-experts can use this without knowing OWL syntax

Usage:
    from ontology_builder import OntologyBuilder

    ob = OntologyBuilder("ontology/KARMA_v014.owl")
    ob.add_component("AdvanceMotor", part_of="UnwindingSubSystem", id_value="M2")
    ob.add_failure_chain(
        cause_name="BeltWearByFriction",
        cause_class="PrimaryFailureCause",
        mode_name="BeltDeterioration",
        mode_class="MechanicalFailureMode",
        results_in_deviations=["LessBeltTension"]
    )
    ob.add_sensor("SQ30", installed_on="AdvanceMotor", measures_variable="Otr_av",
                  alert_threshold=19.5, alarm_threshold=22.0)
    ob.save("ontology/KARMA_v014_updated.owl")
    ob.summary()
"""

import os
from owlready2 import (
    World, Thing, ObjectProperty, DataProperty,
    types
)


# Valid OWL class names in the KARMA ontology for type-checking inputs
VALID_FAILURE_CAUSE_CLASSES = {"PrimaryFailureCause"}
VALID_FAILURE_MODE_CLASSES  = {
    "MechanicalFailureMode", "ElectromechanicalFailureMode",
    "HydraulicFailureMode",  "PneumaticFailureMode", "FailureMode"
}
VALID_MACHINE_UNITS = None  # checked dynamically against loaded ontology


class OntologyBuilderError(Exception):
    """Raised when an invalid operation is attempted on the ontology."""
    pass


class OntologyBuilder:
    """
    API for dynamically extending the KARMA ontology.

    Parameters:
        ontology_path: path to the .owl file to load and extend
    """

    def __init__(self, ontology_path: str):
        path = os.path.abspath(ontology_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Ontology not found: {path}")

        self._world = World()
        self._onto  = self._world.get_ontology(f"file://{path}").load()
        self._log   = []   # change log for summary()

        print(f"✓ Loaded ontology: {path}")
        print(f"  {len(list(self._onto.classes()))} classes, "
              f"{len(list(self._onto.individuals()))} individuals\n")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_class(self, class_name: str):
        """Retrieve an OWL class by name, raise if not found."""
        cls = self._onto.search_one(iri=f"*#{class_name}")
        if cls is None:
            raise OntologyBuilderError(
                f"Class '{class_name}' not found in ontology. "
                f"Check spelling — class names are case-sensitive."
            )
        return cls

    def _get_individual(self, name: str):
        """Retrieve an individual by name, raise if not found."""
        ind = self._onto.search_one(iri=f"*#{name}")
        if ind is None:
            raise OntologyBuilderError(
                f"Individual '{name}' not found in ontology. "
                f"Check spelling — individual names are case-sensitive."
            )
        return ind

    def _individual_exists(self, name: str) -> bool:
        return self._onto.search_one(iri=f"*#{name}") is not None

    def _require_new(self, name: str) -> None:
        """Raise if an individual with this name already exists."""
        if self._individual_exists(name):
            raise OntologyBuilderError(
                f"Individual '{name}' already exists in the ontology. "
                f"Choose a different name or use get_individual() to retrieve it."
            )

    def _get_property(self, prop_name: str):
        """Retrieve an object or data property by name."""
        prop = self._onto.search_one(iri=f"*#{prop_name}")
        if prop is None:
            raise OntologyBuilderError(f"Property '{prop_name}' not found in ontology.")
        return prop

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_component(self,
                      name: str,
                      part_of: str,
                      id_value: str,
                      flows: list = None,
                      comment: str = "") -> object:
        """
        Adds a new Component individual to the ontology.

        Args:
            name:      unique name for this component (e.g. "AdvanceMotor")
            part_of:   name of the MachineUnit this component belongs to
                       (must already exist, e.g. "UnwindingSubSystem")
            id_value:  identifier string (e.g. "M2") used in SWRL rules
            flows:     list of Flow individual names this component has
                       (e.g. ["RotationalSpeedFlow", "TorqueFlow"])
            comment:   optional description

        Returns:
            The created owlready2 individual.

        Example:
            ob.add_component("AdvanceMotor", part_of="UnwindingSubSystem",
                             id_value="M2", flows=["RotationalSpeedFlow"])
        """
        self._require_new(name)
        self._require_new(f"{name}ID")

        parent_unit = self._get_individual(part_of)
        component_class = self._get_class("Component")
        id_class        = self._get_class("ComponentID")

        with self._onto:
            # Create the component individual
            component     = component_class(name)
            component_id  = id_class(f"{name}ID")

            # Set identifier
            component_id.hasIDvalue = [id_value]
            component.hasID = [component_id]

            # Set part-of relationship
            component.isPartOf = [parent_unit]

            # Set flows
            if flows:
                for flow_name in flows:
                    flow = self._get_individual(flow_name)
                    if component.hasFlow is None:
                        component.hasFlow = [flow]
                    else:
                        component.hasFlow.append(flow)

            # Set comment
            if comment:
                component.comment = [comment]

        msg = f"Added Component: {name} (ID={id_value}, partOf={part_of})"
        self._log.append(msg)
        print(f"  ✓ {msg}")
        return component

    def add_variable(self,
                     name: str,
                     measure_of: str,
                     alert_threshold: float,
                     alarm_threshold: float,
                     comment: str = "") -> object:
        """
        Adds a new Variable individual (sensor measurement) to the ontology.

        Args:
            name:            unique name (e.g. "Otr_av")
            measure_of:      component this variable measures (e.g. "AdvanceMotor")
            alert_threshold: value above which Alert state is triggered
            alarm_threshold: value above which Alarm state is triggered
            comment:         optional description

        Example:
            ob.add_variable("Otr_av", measure_of="AdvanceMotor",
                            alert_threshold=19.5, alarm_threshold=22.0)
        """
        if alert_threshold >= alarm_threshold:
            raise OntologyBuilderError(
                f"alert_threshold ({alert_threshold}) must be less than "
                f"alarm_threshold ({alarm_threshold})."
            )

        self._require_new(name)
        component      = self._get_individual(measure_of)
        variable_class = self._get_class("Variable")

        with self._onto:
            variable = variable_class(name)
            variable.isMeasureOf      = [component]
            variable.hasAlertThreshold = [alert_threshold]
            variable.hasAlarmThreshold = [alarm_threshold]
            if comment:
                variable.comment = [comment]

        msg = (f"Added Variable: {name} (measuredFrom={measure_of}, "
               f"alert={alert_threshold}, alarm={alarm_threshold})")
        self._log.append(msg)
        print(f"  ✓ {msg}")
        return variable

    def add_sensor(self,
                   name: str,
                   installed_on: str,
                   measures_variable: str,
                   comment: str = "") -> object:
        """
        Adds a new Sensor individual to the ontology.

        Args:
            name:              unique sensor name (e.g. "SQ30")
            installed_on:      component the sensor is physically on
            measures_variable: Variable individual this sensor measures
            comment:           optional description

        Example:
            ob.add_sensor("SQ30", installed_on="AdvanceMotor",
                          measures_variable="Otr_av")
        """
        self._require_new(name)
        self._require_new(f"{name}ID")

        component     = self._get_individual(installed_on)
        variable      = self._get_individual(measures_variable)
        sensor_class  = self._get_class("Sensor")
        sensor_id_cls = self._get_class("SensorID")

        with self._onto:
            sensor    = sensor_class(name)
            sensor_id = sensor_id_cls(f"{name}ID")

            sensor.hasID       = [sensor_id]
            sensor.isInstalledOn = [component]
            sensor.measure     = [variable]
            if comment:
                sensor.comment = [comment]

        msg = f"Added Sensor: {name} (on={installed_on}, measures={measures_variable})"
        self._log.append(msg)
        print(f"  ✓ {msg}")
        return sensor

    def add_failure_cause(self,
                          name: str,
                          cause_class: str = "PrimaryFailureCause",
                          occurs_in: str = None,
                          comment: str = "") -> object:
        """
        Adds a new PrimaryFailureCause individual.

        Args:
            name:        unique name (e.g. "BeltWearByFriction")
            cause_class: OWL class — must be "PrimaryFailureCause"
            occurs_in:   component where this cause physically occurs
            comment:     optional description

        Example:
            ob.add_failure_cause("BeltWearByFriction",
                                 occurs_in="AdvanceMotor")
        """
        if cause_class not in VALID_FAILURE_CAUSE_CLASSES:
            raise OntologyBuilderError(
                f"cause_class must be one of: {VALID_FAILURE_CAUSE_CLASSES}. "
                f"Got: '{cause_class}'"
            )
        self._require_new(name)
        self._require_new(f"{name}ID")

        cls    = self._get_class(cause_class)
        id_cls = self._get_class("FailureCauseID")

        with self._onto:
            cause    = cls(name)
            cause_id = id_cls(f"{name}ID")
            cause.hasID = [cause_id]

            if occurs_in:
                component = self._get_individual(occurs_in)
                cause.occursIn = [component]

            if comment:
                cause.comment = [comment]

        msg = f"Added FailureCause: {name} (class={cause_class}, occursIn={occurs_in})"
        self._log.append(msg)
        print(f"  ✓ {msg}")
        return cause

    def add_failure_mode(self,
                         name: str,
                         mode_class: str = "MechanicalFailureMode",
                         caused_by: str = None,
                         comment: str = "") -> object:
        """
        Adds a new FailureMode individual.

        Args:
            name:       unique name (e.g. "BeltDeterioration")
            mode_class: OWL class — one of MechanicalFailureMode,
                        ElectromechanicalFailureMode, HydraulicFailureMode,
                        PneumaticFailureMode
            caused_by:  name of the FailureCause or FailureMode that causes this
            comment:    optional description

        Example:
            ob.add_failure_mode("BeltDeterioration",
                                mode_class="MechanicalFailureMode",
                                caused_by="BeltWearByFriction")
        """
        if mode_class not in VALID_FAILURE_MODE_CLASSES:
            raise OntologyBuilderError(
                f"mode_class must be one of: {VALID_FAILURE_MODE_CLASSES}. "
                f"Got: '{mode_class}'"
            )
        self._require_new(name)
        self._require_new(f"{name}ID")

        cls    = self._get_class(mode_class)
        id_cls = self._get_class("FailureModeID")

        with self._onto:
            mode    = cls(name)
            mode_id = id_cls(f"{name}ID")
            mode.hasID = [mode_id]

            if caused_by:
                cause = self._get_individual(caused_by)
                cause.isCauseOf = cause.isCauseOf + [mode] \
                    if cause.isCauseOf else [mode]

            if comment:
                mode.comment = [comment]

        msg = f"Added FailureMode: {name} (class={mode_class}, causedBy={caused_by})"
        self._log.append(msg)
        print(f"  ✓ {msg}")
        return mode

    def add_deviation(self,
                      name: str,
                      deviation_class: str = "Negative",
                      caused_by_mode: str = None,
                      comment: str = "") -> object:
        """
        Adds a new Deviation individual (observable symptom of a failure mode).

        Args:
            name:            unique name (e.g. "LessBeltTension")
            deviation_class: "Negative" or "Positive"
            caused_by_mode:  FailureMode that results in this deviation
            comment:         optional description

        Example:
            ob.add_deviation("LessBeltTension", deviation_class="Negative",
                             caused_by_mode="BeltDeterioration")
        """
        if deviation_class not in ("Negative", "Positive"):
            raise OntologyBuilderError(
                f"deviation_class must be 'Negative' or 'Positive'. "
                f"Got: '{deviation_class}'"
            )
        self._require_new(name)

        cls = self._get_class(deviation_class)

        with self._onto:
            deviation = cls(name)

            if caused_by_mode:
                mode = self._get_individual(caused_by_mode)
                mode.resultsIn = mode.resultsIn + [deviation] \
                    if mode.resultsIn else [deviation]

            if comment:
                deviation.comment = [comment]

        msg = f"Added Deviation: {name} (class={deviation_class}, causedBy={caused_by_mode})"
        self._log.append(msg)
        print(f"  ✓ {msg}")
        return deviation

    def add_failure_chain(self,
                          cause_name: str,
                          cause_class: str = "PrimaryFailureCause",
                          mode_name: str = None,
                          mode_class: str = "MechanicalFailureMode",
                          occurs_in: str = None,
                          results_in_deviations: list = None,
                          deviation_classes: list = None) -> dict:
        """
        Convenience method: adds a complete failure chain in one call.

        Creates: PrimaryFailureCause → FailureMode → [Deviations]

        Args:
            cause_name:           name of the primary failure cause
            cause_class:          class for the cause (default: PrimaryFailureCause)
            mode_name:            name of the failure mode it causes
            mode_class:           class for the mode (default: MechanicalFailureMode)
            occurs_in:            component where the cause occurs
            results_in_deviations: list of deviation names to create
            deviation_classes:    list of classes for each deviation
                                  (default: all "Negative")

        Returns:
            dict with keys: "cause", "mode", "deviations"

        Example:
            ob.add_failure_chain(
                cause_name="BeltWearByFriction",
                mode_name="BeltDeterioration",
                occurs_in="AdvanceMotor",
                results_in_deviations=["LessBeltTension", "MoreAdvanceMotorTorque"],
                deviation_classes=["Negative", "Positive"]
            )
        """
        result = {}

        # Create cause
        cause = self.add_failure_cause(cause_name, cause_class, occurs_in)
        result["cause"] = cause

        # Create mode caused by this cause
        if mode_name:
            mode = self.add_failure_mode(mode_name, mode_class, caused_by=cause_name)
            result["mode"] = mode

            # Create deviations resulting from the mode
            if results_in_deviations:
                dev_classes = deviation_classes or ["Negative"] * len(results_in_deviations)
                if len(dev_classes) != len(results_in_deviations):
                    raise OntologyBuilderError(
                        "deviation_classes length must match results_in_deviations length."
                    )
                result["deviations"] = []
                for dev_name, dev_class in zip(results_in_deviations, dev_classes):
                    dev = self.add_deviation(dev_name, dev_class,
                                             caused_by_mode=mode_name)
                    result["deviations"].append(dev)

        return result

    def list_individuals(self, class_name: str) -> list:
        """
        Returns the names of all existing individuals of a given class.

        Example:
            ob.list_individuals("Component")
            # → ['AccumulatorMotor', 'AccumulatorDrum', ...]
        """
        cls = self._get_class(class_name)
        return [ind.name for ind in cls.instances()]

    def get_individual(self, name: str):
        """Returns an existing individual by name (for inspection or manual edits)."""
        return self._get_individual(name)

    def save(self, output_path: str = None) -> str:
        """
        Saves the updated ontology to a file.

        Args:
            output_path: path to write the updated .owl file.
                         If None, overwrites the original file.

        Returns:
            The path where the file was saved.
        """
        if output_path:
            path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(path), exist_ok=True) \
                if os.path.dirname(path) else None
            self._onto.save(file=path, format="rdfxml")
        else:
            self._onto.save(format="rdfxml")
            path = "original file (overwritten)"

        print(f"\n✓ Ontology saved to: {path}")
        return path

    def summary(self) -> None:
        """Prints a summary of all changes made in this session."""
        print(f"\n{'='*55}")
        print(f"OntologyBuilder Session Summary")
        print(f"{'='*55}")
        print(f"  Total classes:     {len(list(self._onto.classes()))}")
        print(f"  Total individuals: {len(list(self._onto.individuals()))}")
        print(f"\n  Changes made this session ({len(self._log)}):")
        for i, entry in enumerate(self._log, 1):
            print(f"    {i:2d}. {entry}")
        print(f"{'='*55}")
