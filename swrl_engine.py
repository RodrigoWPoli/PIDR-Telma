"""
swrl_engine.py
Parses DLSafeRule elements from a KARMA OWL file and evaluates them against
the current ontology state using a forward-chaining variable-binding engine.

Why this exists: owlready2's Pellet integration calls `pellet realize`, which
only returns class memberships — not object-property assertions inferred by
SWRL rules. This engine reads the rules directly from the OWL XML so that
a researcher can modify rules in Protégé, save the file, and the system
automatically reflects those changes on the next run (no Python edits needed).

Supported SWRL atom types (covers all atoms in KARMA_v014.owl):
  - ClassAtom
  - DataPropertyAtom  (subject-var → literal  OR  subject-var → value-var)
  - ObjectPropertyAtom (subject-var → object-var)
  - BuiltInAtom       (greaterThan, lessThanOrEqual, lessThan,
                        greaterThanOrEqual, equal)
"""

import os
from xml.etree import ElementTree as ET

OWL_NS   = "http://www.w3.org/2002/07/owl#"
XSD_NS   = "http://www.w3.org/2001/XMLSchema#"
SWRLB_NS = "http://www.w3.org/2003/11/swrlb#"
SWRLA_IS_ENABLED = "http://swrl.stanford.edu/ontologies/3.3/swrla.owl#isRuleEnabled"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _local(iri: str) -> str:
    """Return the local name from a full IRI or abbreviated IRI."""
    return iri.split("#")[-1].lstrip("#")


def _cast_literal(text: str, datatype_iri: str):
    """Convert an OWL literal text + datatype to a Python value."""
    dt = datatype_iri.split("#")[-1] if datatype_iri else ""
    if dt in ("integer", "int", "long", "short", "byte",
              "nonNegativeInteger", "positiveInteger"):
        return int(text)
    if dt in ("decimal", "float", "double"):
        return float(text)
    if dt == "boolean":
        return text.strip().lower() == "true"
    return str(text)                       # xsd:string or plain literal


def _values_equal(a, b) -> bool:
    """Numeric-aware equality that coerces int/float."""
    if type(a) == type(b):
        return a == b
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _builtin_check(name: str, args: list) -> bool:
    """Evaluate an swrlb built-in with already-resolved argument values."""
    try:
        a, b = float(args[0]), float(args[1])
    except (TypeError, ValueError, IndexError):
        return False
    return {
        "greaterThan":         a > b,
        "lessThan":            a < b,
        "greaterThanOrEqual":  a >= b,
        "lessThanOrEqual":     a <= b,
        "equal":               a == b,
        "notEqual":            a != b,
    }.get(name, False)


# ── XML Rule Parser ────────────────────────────────────────────────────────────

def _parse_atoms(container_elem):
    """Return a list of atom dicts from a Body or Head XML element."""
    atoms = []
    if container_elem is None:
        return atoms

    for elem in container_elem:
        tag = elem.tag.split("}")[-1]

        if tag == "ClassAtom":
            cls  = elem.find(f"{{{OWL_NS}}}Class")
            var  = elem.find(f"{{{OWL_NS}}}Variable")
            if cls is not None and var is not None:
                atoms.append({
                    "type": "ClassAtom",
                    "class": _local(cls.get("IRI", "")),
                    "var":   _local(var.get("IRI", "")),
                })

        elif tag == "DataPropertyAtom":
            prop = elem.find(f"{{{OWL_NS}}}DataProperty")
            prop_name = _local(prop.get("IRI", "")) if prop is not None else None
            vars_found, literal = [], None
            for child in elem:
                ctag = child.tag.split("}")[-1]
                if ctag == "Variable":
                    vars_found.append(_local(child.get("IRI", "")))
                elif ctag == "Literal":
                    literal = {
                        "value":   child.text or "",
                        "datatype": child.get("datatypeIRI", ""),
                    }
            if len(vars_found) == 2:
                atoms.append({
                    "type":        "DataPropertyAtom",
                    "prop":        prop_name,
                    "subject_var": vars_found[0],
                    "object_var":  vars_found[1],   # value variable
                })
            elif len(vars_found) == 1 and literal is not None:
                atoms.append({
                    "type":        "DataPropertyAtomLiteral",
                    "prop":        prop_name,
                    "subject_var": vars_found[0],
                    "literal":     literal,
                })

        elif tag == "ObjectPropertyAtom":
            prop = elem.find(f"{{{OWL_NS}}}ObjectProperty")
            prop_name = _local(prop.get("IRI", "")) if prop is not None else None
            vars_found = [
                _local(c.get("IRI", ""))
                for c in elem
                if c.tag.split("}")[-1] == "Variable"
            ]
            if len(vars_found) == 2:
                atoms.append({
                    "type":        "ObjectPropertyAtom",
                    "prop":        prop_name,
                    "subject_var": vars_found[0],
                    "object_var":  vars_found[1],
                })

        elif tag == "BuiltInAtom":
            builtin_iri  = elem.get("IRI", "")
            builtin_name = builtin_iri.split("#")[-1]
            args = []
            for child in elem:
                ctag = child.tag.split("}")[-1]
                if ctag == "Variable":
                    args.append({"var": _local(child.get("IRI", ""))})
                elif ctag == "Literal":
                    args.append({
                        "value":   _cast_literal(child.text or "", child.get("datatypeIRI", "")),
                        "datatype": child.get("datatypeIRI", ""),
                    })
            atoms.append({"type": "BuiltInAtom", "builtin": builtin_name, "args": args})

    return atoms


def parse_rules(owl_path: str) -> list:
    """
    Parse all enabled DLSafeRule elements from the OWL file.
    Returns a list of rule dicts with keys: label, body, head.
    """
    tree = ET.parse(owl_path)
    root = tree.getroot()
    rules = []

    for rule_elem in root.findall(f"{{{OWL_NS}}}DLSafeRule"):
        enabled, label = True, None
        for ann in rule_elem.findall(f"{{{OWL_NS}}}Annotation"):
            prop = ann.find(f"{{{OWL_NS}}}AnnotationProperty")
            lit  = ann.find(f"{{{OWL_NS}}}Literal")
            if prop is None or lit is None:
                continue
            prop_iri = prop.get("IRI", "") or prop.get("abbreviatedIRI", "")
            if SWRLA_IS_ENABLED in prop_iri and lit.text == "false":
                enabled = False
            if "rdfs:label" in prop_iri or "label" == prop_iri.split("#")[-1]:
                label = lit.text

        if not enabled:
            continue

        body = _parse_atoms(rule_elem.find(f"{{{OWL_NS}}}Body"))
        head = _parse_atoms(rule_elem.find(f"{{{OWL_NS}}}Head"))
        rules.append({"label": label, "body": body, "head": head})

    return rules


# ── Fact Base (built from owlready2 ontology) ──────────────────────────────────

class FactBase:
    """
    Lightweight in-memory triplestore built from an owlready2 ontology.
    Stores class memberships, data properties, and object properties.
    """

    def __init__(self, onto):
        # {ind_name: set(class_names)}  — direct + superclass memberships
        self.classes: dict[str, set] = {}
        # {ind_name: {prop_name: [values]}}
        self.data_props: dict[str, dict] = {}
        # {ind_name: {prop_name: set(ind_names)}}
        self.obj_props: dict[str, dict] = {}

        self._build(onto)

    def _build(self, onto):
        # Collect all superclass names for a given class
        def all_class_names(cls):
            names = set()
            queue = [cls]
            seen  = set()
            while queue:
                c = queue.pop()
                if c in seen or not hasattr(c, "name") or c.name is None:
                    continue
                seen.add(c)
                names.add(c.name)
                queue.extend(getattr(c, "is_a", []))
            return names

        for ind in onto.individuals():
            name = ind.name
            self.classes[name]    = set()
            self.data_props[name] = {}
            self.obj_props[name]  = {}

            # Class memberships (direct + inferred via is_a hierarchy)
            for cls in ind.is_a:
                self.classes[name] |= all_class_names(cls)

            # Data properties
            for prop in onto.data_properties():
                values = getattr(ind, prop.name, None)
                if values:
                    self.data_props[name][prop.name] = list(values)

            # Object properties
            for prop in onto.object_properties():
                targets = getattr(ind, prop.name, None)
                if targets:
                    self.obj_props[name][prop.name] = {
                        t.name for t in targets if hasattr(t, "name")
                    }

    # ── Query helpers ──────────────────────────────────────────────────────────

    def individuals(self) -> list:
        return list(self.classes.keys())

    def is_a(self, ind: str, class_name: str) -> bool:
        return class_name in self.classes.get(ind, set())

    def get_data(self, ind: str, prop: str):
        """Return the first data property value, or None."""
        vals = self.data_props.get(ind, {}).get(prop)
        return vals[0] if vals else None

    def get_obj(self, ind: str, prop: str) -> set:
        """Return the set of object property targets."""
        return self.obj_props.get(ind, {}).get(prop, set())

    def instances_of(self, class_name: str) -> list:
        return [n for n, cls in self.classes.items() if class_name in cls]

    # ── Mutable assertions (written by rule heads, read by later rules) ────────

    def assert_data(self, ind: str, prop: str, value):
        if ind not in self.data_props:
            self.data_props[ind] = {}
        self.data_props[ind].setdefault(prop, [])
        if value not in self.data_props[ind][prop]:
            self.data_props[ind][prop].append(value)

    def assert_obj(self, ind: str, prop: str, target: str):
        if ind not in self.obj_props:
            self.obj_props[ind] = {}
        self.obj_props[ind].setdefault(prop, set())
        self.obj_props[ind][prop].add(target)


# ── Variable-Binding Evaluator ─────────────────────────────────────────────────

def _resolve_arg(arg: dict, bindings: dict):
    """Return the resolved value of a built-in argument."""
    if "var" in arg:
        return bindings.get(arg["var"])
    return arg.get("value")


def _check_atom(atom: dict, bindings: dict, fb: FactBase) -> list:
    """
    Check one body atom given current bindings.
    Returns a list of updated binding dicts that satisfy the atom,
    or an empty list if the atom cannot be satisfied.
    Each returned dict is a copy with any newly bound variables added.
    """
    t = atom["type"]

    # ── ClassAtom ──────────────────────────────────────────────────────────────
    if t == "ClassAtom":
        var, cls = atom["var"], atom["class"]
        if var in bindings:
            return [bindings] if fb.is_a(bindings[var], cls) else []
        # Enumerate all individuals of this class
        results = []
        for ind in fb.instances_of(cls):
            new = dict(bindings)
            new[var] = ind
            results.append(new)
        return results

    # ── DataPropertyAtomLiteral ────────────────────────────────────────────────
    if t == "DataPropertyAtomLiteral":
        var, prop, lit = atom["subject_var"], atom["prop"], atom["literal"]
        expected = _cast_literal(lit["value"], lit["datatype"])
        if var in bindings:
            actual = fb.get_data(bindings[var], prop)
            return [bindings] if _values_equal(actual, expected) else []
        results = []
        for ind in fb.individuals():
            actual = fb.get_data(ind, prop)
            if actual is not None and _values_equal(actual, expected):
                new = dict(bindings)
                new[var] = ind
                results.append(new)
        return results

    # ── DataPropertyAtom (subject-var → value-var) ────────────────────────────
    if t == "DataPropertyAtom":
        sub_var, val_var, prop = atom["subject_var"], atom["object_var"], atom["prop"]
        if sub_var in bindings:
            val = fb.get_data(bindings[sub_var], prop)
            if val is None:
                return []
            if val_var in bindings:
                return [bindings] if _values_equal(bindings[val_var], val) else []
            new = dict(bindings)
            new[val_var] = val
            return [new]
        # sub_var unbound: enumerate
        results = []
        for ind in fb.individuals():
            val = fb.get_data(ind, prop)
            if val is None:
                continue
            if val_var in bindings and not _values_equal(bindings[val_var], val):
                continue
            new = dict(bindings)
            new[sub_var] = ind
            new[val_var] = val
            results.append(new)
        return results

    # ── ObjectPropertyAtom ─────────────────────────────────────────────────────
    if t == "ObjectPropertyAtom":
        sub_var, obj_var, prop = atom["subject_var"], atom["object_var"], atom["prop"]
        if sub_var in bindings and obj_var in bindings:
            return [bindings] if bindings[obj_var] in fb.get_obj(bindings[sub_var], prop) else []
        if sub_var in bindings:
            results = []
            for target in fb.get_obj(bindings[sub_var], prop):
                if obj_var in bindings and bindings[obj_var] != target:
                    continue
                new = dict(bindings)
                new[obj_var] = target
                results.append(new)
            return results
        if obj_var in bindings:
            results = []
            for ind in fb.individuals():
                if bindings[obj_var] in fb.get_obj(ind, prop):
                    new = dict(bindings)
                    new[sub_var] = ind
                    results.append(new)
            return results
        # Both unbound: enumerate
        results = []
        for ind in fb.individuals():
            for target in fb.get_obj(ind, prop):
                new = dict(bindings)
                new[sub_var] = ind
                new[obj_var] = target
                results.append(new)
        return results

    # ── BuiltInAtom ────────────────────────────────────────────────────────────
    if t == "BuiltInAtom":
        resolved = [_resolve_arg(a, bindings) for a in atom["args"]]
        if any(v is None for v in resolved):
            return []
        return [bindings] if _builtin_check(atom["builtin"], resolved) else []

    return [bindings]


def _sort_atoms(atoms: list) -> list:
    """
    Topologically sort body atoms so that each atom's required variables
    are bound by earlier atoms before it runs.

    Atoms are classified as:
      "producer": can enumerate/bind new variables on its own
                  (ClassAtom, DataPropertyAtomLiteral, ObjectPropertyAtom
                   when one side is already known)
      "consumer": needs all variables already bound
                  (BuiltInAtom, DataPropertyAtom value-binding)

    We do a simple Kahn-style pass: repeatedly pick atoms whose
    required variables are all already in the bound set.
    """
    def required(atom):
        t = atom["type"]
        if t == "ClassAtom":
            return set()                          # seeds its own var
        if t == "DataPropertyAtomLiteral":
            return set()                          # can enumerate subject_var
        if t == "DataPropertyAtom":
            return {atom["subject_var"]}          # needs subject bound
        if t == "ObjectPropertyAtom":
            return set()                          # can enumerate either side
        if t == "BuiltInAtom":
            return {a["var"] for a in atom["args"] if "var" in a}
        return set()

    def produced(atom):
        t = atom["type"]
        if t == "ClassAtom":
            return {atom["var"]}
        if t == "DataPropertyAtomLiteral":
            return {atom["subject_var"]}
        if t == "DataPropertyAtom":
            return {atom["object_var"]}           # binds the value var
        if t == "ObjectPropertyAtom":
            return {atom["subject_var"], atom["object_var"]}
        return set()

    ordered, remaining = [], list(atoms)
    bound = set()
    max_iter = len(atoms) * len(atoms) + 1        # safety cap
    iters = 0
    while remaining and iters < max_iter:
        iters += 1
        for atom in remaining:
            if required(atom) <= bound:
                ordered.append(atom)
                bound |= produced(atom)
                remaining.remove(atom)
                break
        else:
            # No atom is fully satisfiable yet; take the one with fewest
            # unsatisfied dependencies to avoid infinite loops.
            remaining.sort(key=lambda a: len(required(a) - bound))
            ordered.append(remaining.pop(0))

    ordered.extend(remaining)
    return ordered


def _evaluate_body(atoms: list, bindings: dict, fb: FactBase) -> list:
    """
    Recursively evaluate body atoms, threading bindings through.
    Atoms are sorted by dependency order before evaluation.
    Returns all complete binding dicts that satisfy all atoms.
    """
    if not atoms:
        return [bindings]
    sorted_atoms = _sort_atoms(atoms)
    results = []
    for new_bindings in _check_atom(sorted_atoms[0], bindings, fb):
        results.extend(_evaluate_body(sorted_atoms[1:], new_bindings, fb))
    return results


def _apply_head(atoms: list, bindings: dict, fb: FactBase) -> list:
    """Apply head atoms given a complete binding, write assertions to fact base."""
    inferred = []
    for atom in atoms:
        t = atom["type"]
        if t == "ObjectPropertyAtom":
            sub  = bindings.get(atom["subject_var"])
            obj  = bindings.get(atom["object_var"])
            prop = atom["prop"]
            if sub and obj:
                fb.assert_obj(sub, prop, obj)
                inferred.append(("obj", sub, prop, obj))
        elif t == "DataPropertyAtom":
            sub  = bindings.get(atom["subject_var"])
            val  = bindings.get(atom["object_var"])
            prop = atom["prop"]
            if sub is not None and val is not None:
                fb.assert_data(sub, prop, val)
                inferred.append(("data", sub, prop, val))
        elif t == "DataPropertyAtomLiteral":
            sub  = bindings.get(atom["subject_var"])
            prop = atom["prop"]
            lit  = atom["literal"]
            val  = _cast_literal(lit["value"], lit["datatype"])
            if sub is not None:
                fb.assert_data(sub, prop, val)
                inferred.append(("data", sub, prop, val))
    return inferred


# ── Engine ─────────────────────────────────────────────────────────────────────

class SWRLEngine:
    """
    Parses SWRL rules from an OWL file and evaluates them against the
    current state of an owlready2 ontology.

    Usage:
        engine = SWRLEngine("ontology/KARMA_v014.owl")
        # ... update data properties on the ontology ...
        result = engine.evaluate(onto)
        # result["AccumulatorMotor"]["hasState"] -> {"Healthy"}

    The rules are parsed once at construction time. When the researcher
    modifies the OWL file in Protégé and saves it, the system must be
    restarted (or a new SWRLEngine created) to pick up the new rules.
    """

    def __init__(self, owl_path: str):
        path = os.path.abspath(owl_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"OWL file not found: {path}")
        self.owl_path = path
        self.rules = parse_rules(path)
        if not self.rules:
            raise ValueError(f"No enabled DLSafeRule elements found in {path}")

    def evaluate(self, onto) -> dict:
        """
        Evaluate all SWRL rules against the given owlready2 ontology.

        Returns a dict:
          { individual_name: { property_name: set_of_values } }

        Only newly inferred assertions are included (not asserted facts).
        """
        fb      = FactBase(onto)
        inferred_all = []

        # Forward-chain: run all rules; repeat until no new facts are added.
        # Two passes are enough for this ontology (S2-S5 feed into S9/S10).
        for _pass in range(2):
            new_this_pass = False
            for rule in self.rules:
                for binding in _evaluate_body(rule["body"], {}, fb):
                    new = _apply_head(rule["head"], binding, fb)
                    if new:
                        inferred_all.extend(new)
                        new_this_pass = True
            if not new_this_pass:
                break

        # Collect results into a nested dict
        result: dict[str, dict[str, set]] = {}
        for fact in inferred_all:
            if fact[0] == "obj":
                _, sub, prop, obj = fact
                result.setdefault(sub, {}).setdefault(prop, set()).add(obj)
            elif fact[0] == "data":
                _, sub, prop, val = fact
                result.setdefault(sub, {}).setdefault(prop, set()).add(val)

        return result

    def __repr__(self):
        return f"SWRLEngine({len(self.rules)} rules from {os.path.basename(self.owl_path)})"
