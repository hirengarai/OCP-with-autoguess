"""Replayable lower bounds for abstract AutoGuess deduction rules.

The formal vectors below describe an inference invariant, not the cipher's
equations. Every deduction places its conclusion in the span of its premises
modulo the formal rows. A paid guess adds at most one dimension. Consequently
the target deficiency is a necessary guess count at every propagation depth.
Certificate verification uses independent elimination and needs no solver.
"""

from collections import Counter
import hashlib
import json
import math
import time

from core.solverresult import SearchBudget


class _BudgetExpired(Exception):
    pass


class _Deadline:
    """Combine an optional phase cap with the caller's shared search budget."""

    def __init__(self, time_limit=-1, budget=None):
        self.local = SearchBudget(time_limit)
        if budget is not None and not callable(getattr(budget, "remaining", None)):
            raise ValueError("budget must provide a remaining() method")
        self.budget = budget

    def remaining(self):
        limits = [self.local.remaining()]
        if self.budget is not None:
            value = self.budget.remaining()
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0 and value != -1):
                raise ValueError("budget.remaining() must return -1 or a finite nonnegative number")
            limits.append(value)
        finite = [value for value in limits if value != -1]
        return min(finite) if finite else -1

    def check(self):
        if self.remaining() == 0:
            raise _BudgetExpired


def _validated_model(data):
    """Copy the prepared model's semantics and validate direct API input."""
    if not isinstance(data, dict):
        raise ValueError("A prepared model dictionary is required")

    def names(value, label, unique=False):
        if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or not v for v in value):
            raise ValueError(label + " must contain variable IDs")
        result = list(value)
        if unique and len(result) != len(set(result)):
            raise ValueError(label + " must not contain repeated variable IDs")
        return result

    variables = names(data.get("variables"), "variables", unique=True)
    universe = set(variables)
    model = {"variables": variables}
    for role in ("known_variables", "target_variables", "notguessed_variables"):
        model[role] = names(data.get(role, []), role, unique=True)
        if not set(model[role]) <= universe:
            raise ValueError(role + " references an unknown variable")
    for kind in ("symmetric_relations", "implication_relations"):
        if not isinstance(data.get(kind), (list, tuple)):
            raise ValueError(kind + " must be a sequence of relations")
        model[kind] = []
        for raw in data[kind]:
            relation = names(raw, kind)
            if not relation or not set(relation) <= universe:
                raise ValueError(kind + " contains an empty relation or an unknown variable")
            model[kind].append(relation)
    weights = data.get("target_weights")
    if weights is None:
        weights = {}
    if not isinstance(weights, dict) or not set(weights) <= universe:
        raise ValueError("Weights must map known variable IDs to nonnegative integers")
    if any(isinstance(w, bool) or not isinstance(w, int) or w < 0 for w in weights.values()):
        raise ValueError("Weights must be nonnegative integers")
    model["target_weights"] = dict(weights)
    return model


def _deduction_rules(model):
    """Yield exactly the nontrivial rules used by synchronous propagation.

    Repeated symmetric variables are positional: [a,a,b] permits a=>b,
    whereas b cannot determine the two missing occurrences of a.
    """
    for relation in model["symmetric_relations"]:
        counts = Counter(relation)
        for head in dict.fromkeys(relation):
            if counts[head] == 1:
                yield tuple(v for v in dict.fromkeys(relation) if v != head), head
    for relation in model["implication_relations"]:
        premises, head = tuple(dict.fromkeys(relation[:-1])), relation[-1]
        if head not in premises:
            yield premises, head


def _digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _add_high(row, basis, deadline=None):
    while row:
        if deadline is not None:
            deadline.check()
        pivot = row.bit_length() - 1
        if pivot not in basis:
            basis[pivot] = row
            return True
        row ^= basis[pivot]
    return False


def _rank_low(rows):
    """Independent checker: least significant pivots, without generator code."""
    pivots = {}
    for value in rows:
        while value:
            bit = value & -value
            if bit not in pivots:
                pivots[bit] = value
                break
            value ^= pivots[bit]
    return len(pivots)


def _formal_rows(model, deadline=None):
    positions = {v: i for i, v in enumerate(model["variables"])}
    rows, seen = [], set()
    for premises, head in _deduction_rules(model):
        if deadline is not None:
            deadline.check()
        row = 1 << positions[head]
        for premise in premises:
            row |= 1 << positions[premise]
        if row not in seen:
            rows.append(row)
            seen.add(row)
    return rows, positions


def _free_and_price(model):
    known, forbidden = set(model["known_variables"]), set(model["notguessed_variables"])
    weights = model["target_weights"]
    allowed = [v for v in model["variables"] if v not in known | forbidden]
    free = [v for v in allowed if weights.get(v, 1) == 0]
    positive = [weights.get(v, 1) for v in allowed if weights.get(v, 1) > 0]
    return free, min(positive, default=0)


def _certificate(model, *, field="GF(2)", duals=(), complete=False, **details):
    free, price = _free_and_price(model)
    certificate = {
        "format_version": 1, "method": "formal_span", "field": field,
        "model_sha256": _digest(model), "variables": len(model["variables"]),
        "positive_cost_guess_count_lower_bound": len(duals),
        "minimum_positive_guess_weight": price,
        "cost_lower_bound": len(duals) * price, "lower_bound": len(duals) * price,
        "free_allowed_guesses_added_to_relaxation": free,
        "complete": complete,
        "proof_scope": "abstract_deduction_rules_at_any_propagation_depth",
    }
    certificate["dual_masks_hex" if field == "GF(2)" else "dual_vectors"] = list(duals)
    certificate.update(details)
    return certificate


def _gf2_bound(model, deadline):
    rows, positions = _formal_rows(model, deadline)
    basis = {}
    for row in rows:
        _add_high(row, basis, deadline)
    relation_rank = len(basis)
    free, _ = _free_and_price(model)
    for variable in dict.fromkeys(model["known_variables"] + free):
        deadline.check()
        _add_high(1 << positions[variable], basis, deadline)
    base_rank = len(basis)
    augmented = dict(basis)
    for variable in model["target_variables"]:
        _add_high(1 << positions[variable], augmented, deadline)
    deficiency = len(augmented) - base_rank
    duals, projected_basis = [], {}
    ordered = sorted(basis)
    for column in range(len(positions)):
        deadline.check()
        if column in basis:
            continue
        dual = 1 << column
        for pivot in ordered:
            deadline.check()
            if (basis[pivot] & dual).bit_count() % 2:
                dual ^= 1 << pivot
        projection = sum(((dual >> positions[v]) & 1) << i
                         for i, v in enumerate(model["target_variables"]))
        if _add_high(projection, projected_basis, deadline):
            duals.append(hex(dual))
    if len(duals) != deficiency:
        raise RuntimeError("Formal-span target deficiency does not match its dual certificate")
    return _certificate(model, duals=duals, complete=True,
                        formal_relation_rows=len(rows), relation_rank=relation_rank,
                        known_and_free_rank=base_rank, target_augmented_rank=len(augmented))


def _enocoro_coefficients(model):
    """Recognize the entire original clock family before choosing GF(4) rows."""
    relations = model["symmetric_relations"]
    if model["implication_relations"] or not relations or len(relations) % 8:
        return None
    expected = {}
    for t in range(len(relations) // 8):
        families = [
            ([f"b_{t+3}", f"a_{t}", f"e_{t}"], [1, 1, 1]),
            ([f"c_{t+5}", f"b_{t}", f"c_{t+1}"], [1, 1, 1]),
            ([f"d_{t+9}", f"c_{t}", f"d_{t+1}"], [1, 1, 1]),
            ([f"e_{t+15}", f"d_{t}", f"e_{t+3}"], [1, 1, 1]),
            ([f"a_{t+1}", f"d_{t}", f"a_{t}", f"b_{t}", f"e_{t+2}"], [1, 1, 3, 3, 2]),
            ([f"a_{t+1}", f"d_{t}", f"a_{t}", f"b_{t}", f"c_{t}"], [1, 1, 1, 1, 2]),
            ([f"a_{t+1}", f"d_{t}", f"e_{t+2}", f"c_{t}"], [1, 1, 1, 3]),
            ([f"a_{t}", f"b_{t}", f"e_{t+2}", f"c_{t}"], [1, 1, 1, 1]),
        ]
        for names, values in families:
            expected[frozenset(names)] = dict(zip(names, values))
    if (len(expected) != len(relations)
            or any(len(set(relation)) != len(relation) for relation in relations)
            or {frozenset(relation) for relation in relations} != set(expected)
            or set(model["variables"]) != set().union(*expected)):
        return None
    return [[expected[frozenset(relation)][name] for name in relation] for relation in relations]


# a + b*w is encoded as a + 2*b, with w*w = w + 1.
_PRODUCT = ((0, 0, 0, 0), (0, 1, 2, 3), (0, 2, 3, 1), (0, 3, 1, 2))
_INVERSE = (0, 1, 3, 2)


def _gf4_add(raw, basis, deadline):
    row = list(raw)
    while any(row):
        deadline.check()
        pivot = max(i for i, value in enumerate(row) if value)
        if pivot not in basis:
            inverse = _INVERSE[row[pivot]]
            basis[pivot] = [_PRODUCT[inverse][x] for x in row]
            return True
        factor = row[pivot]
        row = [x ^ _PRODUCT[factor][y] for x, y in zip(row, basis[pivot])]
    return False


def _gf4_rows(model, coefficients):
    positions = {v: i for i, v in enumerate(model["variables"])}
    if (not isinstance(coefficients, list) or len(coefficients) != len(model["symmetric_relations"])
            or model["implication_relations"]):
        raise ValueError("GF(4) certificate must describe every symmetric relation")
    rows = []
    for relation, values in zip(model["symmetric_relations"], coefficients):
        if (len(set(relation)) != len(relation) or not isinstance(values, list)
                or len(values) != len(relation)
                or any(type(v) is not int or v not in (1, 2, 3) for v in values)):
            raise ValueError("Each relation variable needs a nonzero GF(4) coefficient")
        row = [0] * len(positions)
        for name, value in zip(relation, values):
            row[positions[name]] = value
        rows.append(row)
    return rows, positions


def _gf4_unit(index, width):
    result = [0] * width
    result[index] = 1
    return result


def _gf4_bound(model, coefficients, deadline):
    rows, positions = _gf4_rows(model, coefficients)
    width, basis = len(positions), {}
    for row in rows:
        _gf4_add(row, basis, deadline)
    relation_rank = len(basis)
    free, _ = _free_and_price(model)
    for variable in dict.fromkeys(model["known_variables"] + free):
        _gf4_add(_gf4_unit(positions[variable], width), basis, deadline)
    base_rank = len(basis)
    augmented = dict(basis)
    for variable in model["target_variables"]:
        _gf4_add(_gf4_unit(positions[variable], width), augmented, deadline)
    deficiency = len(augmented) - base_rank
    duals, projected_basis = [], {}
    ordered = sorted(basis)
    for column in range(width):
        deadline.check()
        if column in basis:
            continue
        dual = _gf4_unit(column, width)
        for pivot in ordered:
            deadline.check()
            value = 0
            for left, right in zip(basis[pivot], dual):
                value ^= _PRODUCT[left][right]
            dual[pivot] = value
        projection = [dual[positions[v]] for v in model["target_variables"]]
        if _gf4_add(projection, projected_basis, deadline):
            duals.append("".join(map(str, dual)))
    if len(duals) != deficiency:
        raise RuntimeError("GF(4) target deficiency does not match its dual certificate")
    return _certificate(model, field="GF(4)", duals=duals, complete=True,
                        coefficients=coefficients, formal_relation_rows=len(rows),
                        relation_rank=relation_rank, known_and_free_rank=base_rank,
                        target_augmented_rank=len(augmented))


def generate_lower_bound(data, *, time_limit=-1, budget=None, field="auto"):
    """Return a certificate, retaining the last complete bound on timeout.

    ``auto`` uses GF(2) for all models and additionally tries a verified GF(4)
    assignment for the complete original Enocoro clock family. A completed
    certificate certifies its bound even if a later strengthening times out.
    ``complete`` records that all requested strengthening attempts finished.
    Zero-budget requests return the universally valid zero bound.
    """
    started = time.monotonic()
    deadline = _Deadline(time_limit, budget)
    if field not in ("auto", "GF(2)"):
        raise ValueError("field must be 'auto' or 'GF(2)'")
    model = _validated_model(data)
    result = _certificate(model)
    timed_out = False
    try:
        deadline.check()
        result = _gf2_bound(model, deadline)
        if field == "auto":
            deadline.check()
            coefficients = _enocoro_coefficients(model)
            if coefficients is not None:
                candidate = _gf4_bound(model, coefficients, deadline)
                if candidate["cost_lower_bound"] > result["cost_lower_bound"]:
                    result = candidate
        result["complete"] = True
    except _BudgetExpired:
        timed_out = True
        result["complete"] = False
    result.update(timed_out=timed_out, generation_seconds=time.monotonic() - started,
                  time_limit=time_limit)
    # Replay is final result validation, so it is allowed to finish after the
    # cooperative search deadline, just like basis_result in the native APIs.
    verify_lower_bound(model, result)
    return result


def _require(condition, message):
    if not condition:
        raise ValueError("Invalid lower-bound certificate: " + message)


def _gf4_checker_product(a, b):
    """Polynomial arithmetic independent of the generator multiplication table."""
    polynomial = (a if b & 1 else 0) ^ (a << 1 if b & 2 else 0)
    return polynomial ^ 7 if polynomial & 4 else polynomial


def _gf4_checker_rank(rows, width):
    matrix = [list(row) for row in rows]
    rank = 0
    for column in range(width):
        pivot = next((i for i in range(rank, len(matrix)) if matrix[i][column]), None)
        if pivot is None:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        inverse = next(v for v in (1, 2, 3) if _gf4_checker_product(matrix[rank][column], v) == 1)
        matrix[rank] = [_gf4_checker_product(inverse, v) for v in matrix[rank]]
        for i in range(rank + 1, len(matrix)):
            factor = matrix[i][column]
            if factor:
                matrix[i] = [x ^ _gf4_checker_product(factor, y)
                             for x, y in zip(matrix[i], matrix[rank])]
        rank += 1
    return rank


def verify_lower_bound(data, certificate):
    """Return the certified cost bound, or raise ValueError on malformed evidence.

    Orthogonality is replayed against all original deduction rules. Neither
    generator elimination nor a native solver is used. Optional rank metadata
    is checked as well, but the bound follows directly from the dual vectors.
    """
    model = _validated_model(data)
    if not isinstance(certificate, dict):
        raise ValueError("A lower-bound certificate dictionary is required")
    _require(type(certificate.get("format_version")) is int
             and certificate["format_version"] == 1, "unsupported format")
    _require(certificate.get("method") == "formal_span", "unsupported method")
    _require(certificate.get("model_sha256") == _digest(model), "different prepared model")
    _require(type(certificate.get("variables")) is int
             and certificate["variables"] == len(model["variables"]), "variable count")
    _require(type(certificate.get("complete")) is bool, "completion status")
    _require(certificate.get("proof_scope") == "abstract_deduction_rules_at_any_propagation_depth", "proof scope")
    free, price = _free_and_price(model)
    _require(certificate.get("free_allowed_guesses_added_to_relaxation") == free, "free guesses")
    _require(type(certificate.get("minimum_positive_guess_weight")) is int
             and certificate["minimum_positive_guess_weight"] == price, "minimum positive weight")
    positions = {v: i for i, v in enumerate(model["variables"])}
    width = len(positions)
    field = certificate.get("field")
    known_and_free = list(dict.fromkeys(model["known_variables"] + free))
    try:
        if field == "GF(2)":
            # Reconstruct rows through rule semantics, independently of the
            # generator's integer row-building and elimination functions.
            relations = set()
            for relation in model["symmetric_relations"]:
                for head in set(relation):
                    if relation.count(head) == 1:
                        relations.add(sum(2 ** positions[v] for v in set(relation)))
            for relation in model["implication_relations"]:
                if relation[-1] not in relation[:-1]:
                    relations.add(sum(2 ** positions[v] for v in set(relation)))
            rows = list(relations)
            base = rows + [2 ** positions[v] for v in known_and_free]
            texts = certificate.get("dual_masks_hex")
            _require(isinstance(texts, list) and all(isinstance(v, str) for v in texts), "dual masks")
            duals = [int(text, 16) for text in texts]
            _require(len(set(duals)) == len(duals), "repeated dual mask")
            for dual in duals:
                _require(0 < dual < 2 ** width, "dual mask range")
                _require(all((dual & row).bit_count() % 2 == 0 for row in base), "dual orthogonality")
            projections = [sum(((dual >> positions[v]) & 1) << i
                               for i, v in enumerate(model["target_variables"])) for dual in duals]
            rank = _rank_low(projections)
            ranks = (_rank_low(rows), _rank_low(base),
                     _rank_low(base + [2 ** positions[v] for v in model["target_variables"]]))
        elif field == "GF(4)":
            rows, _ = _gf4_rows(model, certificate.get("coefficients"))
            base = rows + [_gf4_unit(positions[v], width) for v in known_and_free]
            texts = certificate.get("dual_vectors")
            _require(isinstance(texts, list) and all(isinstance(v, str) for v in texts), "dual vectors")
            _require(all(len(text) == width and not set(text) - set("0123") for text in texts), "dual vector encoding")
            duals = [[int(v) for v in text] for text in texts]
            for dual in duals:
                _require(any(dual), "zero dual vector")
                for row in base:
                    value = 0
                    for a, b in zip(row, dual):
                        value ^= _gf4_checker_product(a, b)
                    _require(value == 0, "dual orthogonality")
            rank = _gf4_checker_rank([[dual[positions[v]] for v in model["target_variables"]]
                                      for dual in duals], len(model["target_variables"]))
            ranks = (_gf4_checker_rank(rows, width), _gf4_checker_rank(base, width),
                     _gf4_checker_rank(base + [_gf4_unit(positions[v], width)
                                              for v in model["target_variables"]], width))
        else:
            raise ValueError("Invalid lower-bound certificate: unsupported field")
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid lower-bound certificate encoding") from error
    _require(rank == len(duals), "dependent target projections")
    _require(type(certificate.get("positive_cost_guess_count_lower_bound")) is int
             and certificate["positive_cost_guess_count_lower_bound"] == rank, "guess-count bound")
    for key in ("cost_lower_bound", "lower_bound"):
        _require(type(certificate.get(key)) is int and certificate[key] == rank * price, key)
    for key, expected in zip(("relation_rank", "known_and_free_rank", "target_augmented_rank"), ranks):
        if key in certificate:
            _require(type(certificate[key]) is int and certificate[key] == expected, key)
    if "formal_relation_rows" in certificate:
        _require(type(certificate["formal_relation_rows"]) is int
                 and certificate["formal_relation_rows"] == len(rows), "formal row count")
    return rank * price
