"""Deterministic deduction witnesses from independently checked knowledge closure.

The graph records a single earliest explanation for each recovered variable.
Every deduction retains all of its premises; presentation code may draw those
premises through an AND junction without inventing independent implications.
This module deliberately has no graph-rendering or native-solver dependencies.
"""

from collections import Counter

from core.lowerbounds import _validated_model
from core.solverresult import basis_result


def _rules(model):
    """Canonical witnesses, preserving positional symmetric multiplicities."""
    rules = set()
    for raw in model["symmetric_relations"]:
        relation = tuple(sorted(raw))
        counts = Counter(relation)
        for head in sorted(counts):
            # [a,a,b] has one missing position only when b is missing.
            if counts[head] == 1:
                premises = tuple(sorted(set(relation) - {head}))
                rules.add((head, premises, "symmetric", relation))
    for raw in model["implication_relations"]:
        head = raw[-1]
        premises = tuple(sorted(set(raw[:-1])))
        if head not in premises:
            relation = tuple(sorted(raw[:-1])) + (head,)
            rules.add((head, premises, "implication", relation))
    return sorted(rules)


def _expression(variable, mapping, active=()):
    """Turn generated product variables into readable labels, safely."""
    factors = mapping.get(variable)
    if (variable in active or not isinstance(factors, (list, tuple)) or not factors
            or any(not isinstance(factor, str) or not factor for factor in factors)):
        return variable
    expressions = [_expression(factor, mapping, active + (variable,))
                   for factor in sorted(factors)]
    return " * ".join("(" + value + ")" if " * " in value else value
                      for value in expressions)


def build_deduction_graph(data, guesses, *, max_steps=None, focus_targets=True):
    """Return a serializable, solver-independent earliest-deduction graph.

    ``guesses`` are fully paid and already known variables are free. A basis
    must recover every target within ``max_steps`` (or unrestricted closure
    when None); otherwise a ValueError prevents a misleading success graph.

    The default scope shows each target's ancestors through one canonical
    earliest witness, plus every initial known variable and paid guess. Set
    ``focus_targets=False`` to show the entire reachable closure. Synchronous
    propagation steps describe knowledge rounds, not cipher rounds.

    Variable IDs and deduction IDs occupy separate namespaces. A renderer
    must namespace them too: a user variable may itself be named ``d0``.
    Symmetric relation entries retain repeated positions in ``relation``;
    ``premises`` contains distinct jointly required variable IDs.
    """
    if (max_steps is not None and (isinstance(max_steps, bool)
            or not isinstance(max_steps, int) or max_steps < 0)):
        raise ValueError("max_steps must be a nonnegative integer or None")
    if not isinstance(focus_targets, bool):
        raise ValueError("focus_targets must be a boolean")
    if not isinstance(guesses, (list, tuple)) or any(
            not isinstance(variable, str) or not variable for variable in guesses):
        raise ValueError("guesses must contain variable IDs")
    model = _validated_model(data)
    universe = set(model["variables"])
    supplied = set(guesses)
    if not supplied <= universe:
        raise ValueError("Unknown guessed variable")
    known = set(model["known_variables"])
    paid = supplied - known
    if paid & set(model["notguessed_variables"]):
        raise ValueError("A forbidden variable cannot be guessed")
    paid = sorted(paid)
    result = basis_result(model, paid, max_steps=max_steps)
    if not result["targets_covered"]:
        raise ValueError("Guess basis does not recover every target within the propagation limit")

    steps = {variable: record["step"]
             for record in result["determination_steps"]
             for variable in record["determined_vars"]}
    targets = set(model["target_variables"])
    target_depth = max((steps[variable] for variable in targets), default=0)
    rules_by_head = {}
    for head, premises, kind, relation in _rules(model):
        rules_by_head.setdefault(head, []).append((premises, kind, relation))

    witnesses = {}
    for head in sorted(steps, key=lambda variable: (steps[variable], variable)):
        step = steps[head]
        if not step:
            continue
        for premises, kind, relation in rules_by_head.get(head, ()):
            if all(variable in steps and steps[variable] < step for variable in premises):
                witnesses[head] = {
                    "id": "d" + str(len(witnesses)), "head": head,
                    "premises": list(premises), "step": step,
                    "relation_kind": kind, "relation": list(relation),
                }
                break
        else:
            raise RuntimeError("Validated closure has no matching earliest deduction witness")

    shown = set(steps)
    if focus_targets:
        shown = set(known) | set(paid) | targets
        pending = list(sorted(targets))
        visited = set()
        while pending:
            head = pending.pop()
            if head in visited:
                continue
            visited.add(head)
            if head in witnesses:
                premises = witnesses[head]["premises"]
                shown.update(premises)
                pending.extend(premises)

    dummy_mapping = data.get("dummy_mapping", {})
    if not isinstance(dummy_mapping, dict):
        dummy_mapping = {}
    nodes = []
    weights = model["target_weights"]
    for variable in sorted(shown):
        expression = _expression(variable, dummy_mapping)
        node = {"id": variable, "label": expression,
                "kind": "known" if variable in known else "guessed" if variable in paid else "derived",
                "step": steps[variable], "target": variable in targets,
                "weight": weights.get(variable, 1)}
        if expression != variable:
            node["expression"] = expression
        nodes.append(node)
    deductions = [value for head, value in witnesses.items() if head in shown]
    layer_steps = sorted({node["step"] for node in nodes})
    layers = [{"step": step,
               "variables": [node["id"] for node in nodes if node["step"] == step],
               "deductions": [rule["id"] for rule in deductions if rule["step"] == step]}
              for step in layer_steps]
    return {
        "nodes": nodes, "deductions": deductions, "layers": layers,
        "metadata": {
            "cost": result["cost"], "guessed_count": len(paid),
            "target_count": len(targets), "shown_target_count": len(targets & shown),
            "propagation_steps": target_depth, "max_steps": max_steps,
            "scope": "targets" if focus_targets else "full",
            "variable_count": len(universe), "shown_variable_count": len(shown),
            "deduction_count": len(deductions),
        },
    }
