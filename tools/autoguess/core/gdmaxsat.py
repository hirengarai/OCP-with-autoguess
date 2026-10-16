"""Weighted MaxSAT optimization of the existing guess-and-determine model.

Deduction, known, target and forbidden-guess clauses are hard constraints.
Each paid initial guess violates a soft negative unit with its original weight.
PySAT is imported only when this optional backend is selected.
"""

from pathlib import Path
from threading import Event, Timer
import time

from core.solverresult import (
    basis_result, current_result, remaining_time, timed_search,
)
from core.varnames import step_var


MODEL_KEYS = (
    "problem_name", "variables", "known_variables", "target_variables",
    "notguessed_variables", "symmetric_relations", "implication_relations",
    "target_weights", "dummy_mapping",
)


class _MaxSATInterrupted(Exception):
    """Leave RC2 at an oracle boundary without using a stale UNSAT core."""


def _new_optimizer(formula, expired):
    from pysat.examples.rc2 import RC2

    class DeadlineRC2(RC2):
        def __init__(self):
            self.certified_cost = 0
            super().__init__(formula, solver="g3", adapt=False, exhaust=False,
                             minz=False, trim=0, process=0)

        def _call_oracle(self, assumptions=None, expect_interrupt=False):
            # A previous core has been fully processed at this boundary. Save
            # its bound before Python/native interruption can leave another
            # iteration only partially processed.
            self.certified_cost = int(self.cost)
            if expired.is_set():
                self.interrupted = True
                raise _MaxSATInterrupted()
            result = super()._call_oracle(assumptions or [], expect_interrupt)
            if result is None:
                self.interrupted = True
                raise _MaxSATInterrupted()
            return result

    return DeadlineRC2()


def _validated_parameters(parameters):
    parameters = dict(parameters)
    depth = parameters.get("maxsteps")
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise ValueError("maxsteps must be a nonnegative integer")
    cap = parameters.get("maxguess")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 0):
        raise ValueError("maxguess must be a nonnegative integer or None")
    if parameters.get("satsolver") not in (None, "g3", "glucose3"):
        raise ValueError("MaxSAT supports the interruptible g3/glucose3 SAT solver")
    supplied_seed = parameters.get("seed_basis")
    if supplied_seed is not None and (
            not isinstance(supplied_seed, (list, tuple)) or
            any(not isinstance(variable, str) for variable in supplied_seed)):
        raise ValueError("seed_basis must be a list of variable IDs")
    parameters.setdefault("outputfile", "output")
    parameters["maxguess"] = cap
    parameters["satsolver"] = "glucose3"
    return parameters, cap, supplied_seed


def _make_formula(engine, data, cap):
    from pysat.formula import WCNF

    engine.generate_sat_constraints()
    engine.generate_boundary_no_cardinality()
    formula = WCNF()
    for clause in engine.cnf_formula.clauses:
        formula.append(clause)
    known = set(data["known_variables"])
    weights = data["target_weights"] or {}
    paid_literals, paid_weights = [], []
    for variable in data["variables"]:
        if variable in known:
            continue
        weight = weights.get(variable, 1)
        if weight > 0:
            literal = engine.variables_dictionary[step_var(variable, 0)]
            # WCNF.append(weight=0) makes a clause HARD. Free guesses must
            # remain possible, so they have no soft clause or cap term.
            formula.append([-literal], weight=weight)
            paid_literals.append(literal)
            paid_weights.append(weight)
    if cap is not None and sum(paid_weights) > cap:
        if cap == 0:
            for literal in paid_literals:
                formula.append([-literal])
        else:
            from pysat.pb import PBEnc, EncType
            encoding = PBEnc.leq(lits=paid_literals, weights=paid_weights,
                                 bound=cap, top_id=engine.top_variable_identifier_so_far,
                                 encoding=EncType.binmerge)
            for clause in encoding.clauses:
                formula.append(clause)
    return formula


@timed_search
def search_using_maxsat(parameters):
    """Find a minimum-cost basis, retaining a fully charged optional seed.

    ``maxguess`` is an optional hard upper bound, never a claimed optimum.
    ``seed_basis`` gives an incumbent, without adding known variables or
    constraining replacement guesses. The cooperative time budget includes
    parsing/encoding; final independent validation may finish after its limit.
    """
    from config import TEMP_DIR
    from core.search import _sat_solver

    started = time.monotonic()
    parameters, cap, supplied_seed = _validated_parameters(parameters)
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
    engine = _sat_solver(parameters)
    data = {key: getattr(engine, key) for key in MODEL_KEYS}
    known = set(data["known_variables"])
    best = None
    normalized_seed = None
    seed_cost = None
    lower_bound = 0
    proof_method = "none"
    native_seconds = 0.0
    preparation_seconds = time.monotonic() - started
    model_returned = False
    proven = False
    stop_reason = "time_limit"
    hard_unsat = False

    if supplied_seed is not None:
        unknown = set(supplied_seed) - set(data["variables"])
        if unknown:
            raise ValueError("Unknown seed variable IDs: %s" % sorted(unknown))
        normalized_seed = list(dict.fromkeys(v for v in supplied_seed if v not in known))
        if set(normalized_seed) & set(data["notguessed_variables"]):
            raise ValueError("seed_basis contains forbidden guesses")
        best = basis_result(data, normalized_seed, max_steps=parameters["maxsteps"])
        if best["status"] != "sat":
            raise ValueError("seed_basis does not cover all targets at maxsteps")
        if cap is not None and best["cost"] > cap:
            raise ValueError("seed_basis exceeds maxguess")
        seed_cost = best["cost"]

    # This checks a mathematical lower bound of zero without native solving.
    # It also handles empty systems and targets already known from the file.
    empty = basis_result(data, [], max_steps=parameters["maxsteps"])
    if empty["status"] == "sat":
        best = empty
    if best is not None and best["cost"] == 0:
        proven = True
        stop_reason = "optimal"
        proof_method = "nonnegative_cost_zero"
    preparation_seconds = time.monotonic() - started

    def finish():
        result = best if best is not None else current_result(engine, False if hard_unsat else None)
        result.update(
            optimal=proven, termination_reason="optimal" if proven else stop_reason,
            lower_bound=lower_bound, upper_bound=best["cost"] if best is not None else None,
            proof_method=proof_method, solver_stop_reason=stop_reason,
            solver_seconds=native_seconds, preparation_seconds=preparation_seconds,
            max_steps=parameters["maxsteps"], max_guess=cap,
            seed_basis=normalized_seed, seed_cost=seed_cost,
            improved=bool(best is not None and seed_cost is not None and best["cost"] < seed_cost),
            improvement_delta=seed_cost-best["cost"] if best is not None and seed_cost is not None else None,
            model_returned=model_returned, model=data, inputfile=parameters["inputfile"],
            solver="maxsat", satsolver="glucose3",
        )
        return result

    if proven or remaining_time(parameters) == 0:
        return finish()
    formula = _make_formula(engine, data, cap)
    preparation_seconds = time.monotonic() - started
    if remaining_time(parameters) == 0:
        return finish()
    expired = Event()
    optimizer = _new_optimizer(formula, expired)
    timer = None
    returned = None
    interrupted = False
    try:
        remaining = remaining_time(parameters)
        preparation_seconds = time.monotonic() - started
        if remaining == 0:
            return finish()
        if remaining != -1:
            def interrupt():
                expired.set()
                optimizer.interrupt()
            timer = Timer(remaining, interrupt)
            timer.daemon = True
            timer.start()
        native_started = time.monotonic()
        try:
            returned = optimizer.compute(expect_interrupt=True)
        except _MaxSATInterrupted:
            interrupted = True
            stop_reason = "time_limit" if expired.is_set() else "interrupted"
        except KeyboardInterrupt:
            optimizer.interrupt()
            interrupted = True
            stop_reason = "interrupted"
        finally:
            native_seconds = max(0.0, time.monotonic() - native_started)
            if timer is not None:
                timer.cancel()
                timer.join()
        lower_bound = int(optimizer.cost if returned is not None else optimizer.certified_cost)
        if lower_bound < 0 or (best is not None and lower_bound > best["cost"]):
            raise RuntimeError("MaxSAT lower bound contradicts the validated incumbent")
        if returned is not None:
            positive = {literal for literal in returned if literal > 0}
            guesses = [v for v in data["variables"] if v not in known and
                       engine.variables_dictionary[step_var(v, 0)] in positive]
            candidate = basis_result(data, guesses, max_steps=parameters["maxsteps"], max_guess=cap)
            if candidate["status"] != "sat" or candidate["cost"] != lower_bound:
                raise RuntimeError("MaxSAT model failed independent cost/coverage validation")
            best = candidate
            model_returned = True
            proven = True
            stop_reason = "optimal"
            proof_method = "rc2_completed_optimum"
        elif not interrupted and not optimizer.interrupted:
            if best is not None:
                raise RuntimeError("Hard MaxSAT inconsistency contradicts the validated incumbent")
            hard_unsat = True
            stop_reason = "infeasible"
            lower_bound = cap + 1 if cap is not None else 0
            proof_method = "cost_cap_infeasible" if cap is not None else "hard_constraints_unsat"
        elif expired.is_set():
            stop_reason = "time_limit"
        elif not interrupted:
            stop_reason = "interrupted"
        if best is not None and lower_bound == best["cost"]:
            proven = True
            if not model_returned:
                proof_method = "rc2_lower_bound_meets_validated_incumbent"
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        optimizer.delete()
    return finish()
