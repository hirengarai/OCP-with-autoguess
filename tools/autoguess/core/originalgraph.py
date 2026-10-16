"""The original AutoGuess determination-flow topology, with validated bases.

This reproduces ``parse_solver_solution``'s relation scans: all qualifying
deductions are retained in input order, including alternatives and repeated
paths. The per-head occurrence number controls the original dashed-edge style.
Pairwise drawing is an original presentation convention, not a claim that each
premise independently suffices for a multi-input deduction.
"""

from core.deductiongraph import _expression
from core.lowerbounds import _validated_model
from core.solverresult import basis_result
from core.varnames import step_var


def build_original_graph(data, guesses, *, max_steps=None, solutions=None):
    """Build the original parser graph from native or synchronous states.

    Native ``solutions`` are step dictionaries indexed by ``step_var(v, t)``.
    Supplied traces may postpone knowledge, but must start from exactly the
    supplied basis and file/extra-known variables, be monotone, and
    never claim knowledge earlier than independent synchronous propagation.
    Acceptance here does not establish that a synthetic trace satisfies a
    backend's complete encoding. Without native states the original scan uses independently validated
    synchronous closure. Thus graph metadata explicitly records its state source.

    ``original_vertices`` and ``original_edges`` preserve raw parser order and
    duplicates. Normal visible nodes are exactly their vertex set. The original
    empty graph when all targets are initially known is intentionally repaired
    by displaying the initial knowledge and paid basis, without inventing edges.
    """
    if max_steps is not None and (isinstance(max_steps, bool)
            or not isinstance(max_steps, int) or max_steps < 0):
        raise ValueError("max_steps must be a nonnegative integer or None")
    if not isinstance(guesses, (list, tuple)) or any(
            not isinstance(variable, str) or not variable for variable in guesses):
        raise ValueError("guesses must contain variable IDs")
    if solutions is not None and (not isinstance(solutions, (list, tuple)) or not solutions):
        raise ValueError("solutions must be a nonempty sequence of native step dictionaries")
    model = _validated_model(data)
    variables = model["variables"]
    universe, known = set(variables), set(model["known_variables"])
    supplied = set(guesses)
    if not supplied <= universe:
        raise ValueError("Unknown guessed variable")
    paid = supplied - known
    if paid & set(model["notguessed_variables"]):
        raise ValueError("A forbidden variable cannot be guessed")
    limit = max_steps
    if limit is None:
        limit = len(solutions) - 1 if solutions is not None else len(variables)
    paid = [variable for variable in variables if variable in paid]
    result = basis_result(model, paid, max_steps=limit)
    if not result["targets_covered"]:
        raise ValueError("Guess basis does not recover every target within the propagation limit")
    earliest = {variable: record["step"] for record in result["determination_steps"]
                for variable in record["determined_vars"]}
    trace = {record["step"]: set(record["determined_vars"])
             for record in result["determination_steps"]}
    initial = known | set(paid)
    native_states = None
    if solutions is not None:
        if len(solutions) < limit + 1:
            raise ValueError("Native solutions do not include every requested propagation step")
        native_states = []
        independent, previous = set(), set()
        for step in range(limit + 1):
            independent.update(trace.get(step, ()))
            state = solutions[step]
            if not isinstance(state, dict):
                raise ValueError("Each native solution step must be a dictionary")
            reached = set()
            for variable in variables:
                key = step_var(variable, step)
                if key not in state or state[key] not in (0, 1):
                    raise ValueError("Native solution steps need a Boolean value for every variable")
                if state[key] == 1:
                    reached.add(variable)
            if step == 0 and reached != initial:
                raise ValueError("Native initial knowledge does not match the supplied paid basis")
            if not previous <= reached or not reached <= independent:
                raise ValueError("Native knowledge states disagree with validated synchronous closure")
            native_states.append(reached)
            previous = reached

    vertices, edges, deductions = [], [], []
    counts = {variable: 0 for variable in variables}
    targets = set(model["target_variables"])
    displayed_targets = targets & initial
    synchronous = set(initial)
    steps_scanned = 0

    def record(head, premises, kind, relation, step):
        vertices.append(head)
        counts[head] += 1
        for premise in premises:
            vertices.append(premise)
            edges.append([premise, head, counts[head]])
        deductions.append({"id": "original_%s" % len(deductions), "head": head,
                           "premises": list(premises), "step": step + 1,
                           "source_step": step, "count": counts[head],
                           "relation_kind": kind, "relation": list(relation)})
        if head in targets:
            displayed_targets.add(head)

    for step in range(limit + 1):
        if targets <= displayed_targets:
            break
        synchronous.update(trace.get(step, ()))
        state = native_states[step] if native_states is not None else synchronous
        # These conditions intentionally mirror the original parser exactly.
        # Repeated symmetric positions and repeated implication premises remain
        # positional here; canonicalizing relations would change old edge counts.
        for relation in model["symmetric_relations"]:
            premises = [variable for variable in relation if variable in state]
            if len(premises) == len(relation) - 1:
                missing = set(relation) - set(premises)
                if len(missing) != 1:
                    raise RuntimeError("An original symmetric deduction has no unique missing variable")
                record(next(iter(missing)), premises, "symmetric", relation, step)
        for relation in model["implication_relations"]:
            premises = [variable for variable in relation if variable in state]
            if premises == relation[:-1]:
                record(relation[-1], premises, "implication", relation, step)
        steps_scanned += 1

    if not targets <= displayed_targets:
        raise ValueError("Native graph states do not expose every target through the original relation scan")
    zero_step = targets <= initial
    visible = set(vertices)
    if zero_step:
        visible.update(initial | targets)
    mapping = data.get("dummy_mapping", {})
    if not isinstance(mapping, dict):
        mapping = {}
    nodes = []
    for variable in sorted(visible):
        node = {"id": variable, "label": variable,
                "kind": "known" if variable in known else "guessed" if variable in paid else "derived",
                "step": earliest[variable], "target": variable in targets,
                "weight": model["target_weights"].get(variable, 1)}
        expression = _expression(variable, mapping)
        if expression != variable:
            node["expression"] = expression
        nodes.append(node)
    layer_steps = sorted({node["step"] for node in nodes} | {rule["step"] for rule in deductions})
    return {
        "nodes": nodes, "deductions": deductions,
        "original_vertices": vertices, "original_edges": edges,
        "layers": [{"step": step,
                    "variables": [node["id"] for node in nodes if node["step"] == step],
                    "deductions": [rule["id"] for rule in deductions if rule["step"] == step]}
                   for step in layer_steps],
        "metadata": {
            "view": "original", "scope": "original_parser", "topology": "original_parser",
            "state_source": "native" if native_states is not None else "validated_closure",
            "cost": result["cost"], "guessed_count": len(paid), "target_count": len(targets),
            "shown_target_count": len(targets & visible), "max_steps": limit,
            "propagation_steps": max((earliest[target] for target in targets), default=0),
            "variable_count": len(variables), "shown_variable_count": len(visible),
            "deduction_count": len(deductions), "edge_count": len(edges),
            "unique_edge_count": len({tuple(edge) for edge in edges}),
            "steps_scanned": steps_scanned, "zero_step_initials": zero_step,
        },
    }
