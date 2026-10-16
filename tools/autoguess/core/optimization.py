"""Optional paid-incumbent optimization, verified bounds and basis refinement."""
import json
import math
import os
import time

from core.console import progress, progress_output
from core.solverresult import (
    SearchBudget, atomic_write, basis_result, remaining_time, termination_result,
    timed_search,
)


def has_optimization_options(parameters):
    return (parameters.get("solver") == "maxsat" or
            parameters.get("seed_basis") is not None or
            parameters.get("seed_basis_file") is not None or
            bool(parameters.get("lower_bound")) or bool(parameters.get("refine_basis")) or
            parameters.get("refine_time") is not None)


def propagation_steps(result):
    if result.get("status") != "sat":
        return None
    targets = set(result["target_variables"])
    recovered = set()
    for step in result["determination_steps"]:
        recovered.update(step["determined_vars"])
        if targets <= recovered:
            return step["step"]
    return 0 if not targets else None


def _seed(parameters):
    supplied = parameters.get("seed_basis")
    filename = parameters.get("seed_basis_file")
    if supplied is not None and filename is not None:
        raise ValueError("Use either seed_basis or seed_basis_file")
    if filename is not None:
        protected = {os.path.realpath(parameters["outputfile"])}
        if os.path.realpath(filename) in protected:
            raise ValueError("The paid seed input must differ from the report path")
        with open(filename) as stream:
            supplied = json.load(stream)
        if isinstance(supplied, dict):
            if "guessed_variables" not in supplied:
                raise ValueError("Seed JSON must contain guessed_variables or be a list")
            supplied = supplied["guessed_variables"]
    if supplied is None:
        return None
    if isinstance(supplied, str):
        supplied = [supplied]
    if not isinstance(supplied, (list, tuple)) or any(not isinstance(v, str) for v in supplied):
        raise ValueError("The paid seed must be a list of variable IDs")
    return list(dict.fromkeys(v.strip() for group in supplied for v in group.split(",") if v.strip()))


class _PhaseBudget:
    def __init__(self, parameters, seconds):
        self.parameters = parameters
        self.local = SearchBudget(seconds)

    def remaining(self):
        parent, local = remaining_time(self.parameters), self.local.remaining()
        if parent == -1:
            return local
        if local == -1:
            return parent
        return min(parent, local)


def _empty(data, status="unknown", reason="unknown"):
    return termination_result(dict(status=status, guessed_variables=[], cost=None,
        known_variables=list(data["known_variables"]), target_variables=list(data["target_variables"]),
        determination_steps=[], optimal=False, outputfile=None, targets_covered=False,
        covered_target_variables=[], missing_targets=list(data["target_variables"]), finally_known=[]), reason)


def _minimizing(p):
    return (p["solver"] == "maxsat" or
            p["solver"] in ("sat", "smt") and p.get("findmin", False) or
            p["solver"] == "cp" and p.get("cpoptimization", 0) == 1 or
            p["solver"] == "milp")


def _native(parameters):
    from core import search
    if parameters["solver"] == "maxsat":
        from core.gdmaxsat import search_using_maxsat
        return search_using_maxsat(parameters)
    return getattr(search, "search_using_" + parameters["solver"])(parameters)


def _report(data, result, parameters):
    """Render the validated closure, independently of a backend's SAT states."""
    if result["status"] != "sat":
        result["outputfile"] = None
        return
    lines = ["AutoGuess optimization result", "Number of variables: %d" % len(data["variables"]),
             "Number of relations: %d" % (len(data["symmetric_relations"]) + len(data["implication_relations"])),
             "Number of guessed variables: %d" % len(result["guessed_variables"]),
             "Guess cost: %d" % result["cost"],
             "Cost lower bound: %s" % result["lower_bound"],
             "Maximum deduction steps: %s" % parameters["maxsteps"],
             "Target propagation steps: %s" % result["propagation_steps"],
             "Proof method: %s" % result.get("proof_method", "none"),
             "", "Guessed variables: " + ", ".join(result["guessed_variables"]),
             "File/extra known variables: " + ", ".join(data["known_variables"]),
             "Target variables: " + ", ".join(data["target_variables"]), "", "Determination flow:"]
    for step in result["determination_steps"]:
        lines.append("State %d: %s" % (step["step"], ", ".join(step["determined_vars"])))
    if data.get("dummy_mapping"):
        lines.extend(["", "Algebraic dummy mappings:"])
        lines.extend("%s = %s" % (name, " * ".join(factors))
                     for name, factors in sorted(data["dummy_mapping"].items()))
    atomic_write(parameters["outputfile"], "\n".join(lines) + "\n")
    result["outputfile"] = parameters["outputfile"]
    from core.graphreport import attach_graph
    attach_graph(data, result, parameters)


@timed_search
def search_with_options(parameters):
    from core.inputparser import read_relation_file
    from core.search import _parse_extra_known
    started = time.monotonic()
    p = dict(parameters)
    if p["solver"] not in ("sat", "maxsat", "smt", "cp", "milp"):
        raise ValueError("Paid seeds, bounds and refinement support SAT, MaxSAT, SMT, CP and MILP")
    if p["solver"] == "milp" and p.get("milpdirection", "min") != "min":
        raise ValueError("The optional optimization workflow requires MILP minimization")
    for flag in ("lower_bound", "refine_basis"):
        if flag in p and not isinstance(p[flag], bool):
            raise ValueError(flag + " must be a boolean")
    trials = p.get("refine_trials", 1000)
    random_seed = p.get("random_seed", 0)
    if isinstance(trials, bool) or not isinstance(trials, int) or trials < 0:
        raise ValueError("refine_trials must be a nonnegative integer")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ValueError("random_seed must be an integer")
    if p.get("refine_time") is not None and not p.get("refine_basis"):
        raise ValueError("refine_time requires refine_basis")
    if p.get("refine_time") is not None:
        cap = p["refine_time"]
        if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap < 0:
            raise ValueError("refine_time must be a finite nonnegative number")
    supplied = _seed(p)
    if p.get("refine_basis") and supplied is None:
        raise ValueError("--refine-basis requires a fully paid --seed-basis or --seed-basis-file")
    data = p.get("_prepared_model")
    if data is None:
        data = read_relation_file(p["inputfile"], preprocess=p.get("preprocess", 0),
                                 D=p.get("D", 2), log=p.get("log", 0),
                                 extra_known=_parse_extra_known(p))
    p["_prepared_model"] = data
    best, seed_cost, seed_steps, seed = None, None, None, None
    if supplied is not None:
        unknown = set(supplied) - set(data["variables"])
        if unknown:
            raise ValueError("Unknown paid seed variables: " + ", ".join(sorted(unknown)))
        seed = [v for v in supplied if v not in data["known_variables"]]
        forbidden = set(seed) & set(data["notguessed_variables"])
        if forbidden:
            raise ValueError("Forbidden paid seed variables: " + ", ".join(sorted(forbidden)))
        weights = data["target_weights"] or {}
        if sum(weights.get(v, 1) for v in seed) > p["maxguess"]:
            raise ValueError("Paid seed cost exceeds maxguess")
        best = basis_result(data, seed, max_steps=p["maxsteps"], max_guess=p["maxguess"])
        if best["status"] != "sat":
            raise ValueError("Paid seed does not cover every target within maxsteps")
        seed_cost, seed_steps = best["cost"], propagation_steps(best)
    lower, certificate, refinement = 0, None, None
    if p.get("lower_bound"):
        from core.lowerbounds import generate_lower_bound, verify_lower_bound
        certificate = generate_lower_bound(data, budget=_PhaseBudget(p, -1))
        lower = verify_lower_bound(data, certificate)
    if lower > p["maxguess"]:
        result = _empty(data, "unsat", "infeasible")
        result["proof_method"] = "verified_lower_bound_exceeds_cap"
    else:
        if p.get("refine_basis"):
            from core.basisrefine import refine_basis
            remaining = remaining_time(p)
            cap = p.get("refine_time")
            if cap is None:
                cap = 1.0 if remaining == -1 else min(1.0, remaining * 0.2)
            best = refine_basis(data, best["guessed_variables"], max_steps=p["maxsteps"],
                time_limit=cap, budget=_PhaseBudget(p, cap), random_seed=random_seed, max_trials=trials)
            refinement = {key: best[key] for key in ("seed_cost", "seed_propagation_steps",
                "propagation_steps", "trials", "elapsed_seconds", "improved", "refinement_improved",
                "termination_reason", "timed_out", "proof_scope") if key in best}
            refinement.update(time_limit=cap, random_seed=random_seed, max_trials=trials)
            # A local phase cap can expire while the request still has time.
            # Retain that fact in refinement metadata, without marking an
            # otherwise completed satisfaction request as globally timed out.
            if best.get("termination_reason") == "time_limit" and remaining_time(p) != 0:
                termination_result(best)
        if best is not None and best["cost"] == 0:
            result = best
            result.update(optimal=True, proof_method="nonnegative_zero_cost")
        elif best is not None and lower == best["cost"]:
            result = best
            result.update(optimal=True, proof_method="verified_lower_bound_matches_incumbent")
        elif best is not None and not _minimizing(p):
            result = best
        else:
            native_parameters = dict(p, drawgraph=False, _defer_reporting=True)
            if best is not None and p["solver"] == "maxsat":
                native_parameters["seed_basis"] = best["guessed_variables"]
            elif best is not None:
                native_parameters["maxguess"] = best["cost"] - 1
                native_parameters.pop("seed_basis", None)
            if best is not None:
                if p["solver"] == "maxsat":
                    progress("MaxSAT optimization: paid incumbent cost %d" % best["cost"])
                else:
                    progress("Cost-bound subsearch: maximum guess cost %d" % native_parameters["maxguess"])
            with progress_output(False):
                result = _native(native_parameters)
            native_reason = result.get("termination_reason", "unknown")
            raw_lower = result.get("lower_bound", 0)
            if isinstance(raw_lower, (int, float)) and math.isfinite(raw_lower):
                lower = max(lower, max(0, math.floor(raw_lower)))
            if result["status"] == "sat" and result.get("optimal"):
                lower = max(lower, result["cost"])
            if best is not None and result["status"] == "unsat":
                if p["solver"] == "maxsat":
                    raise RuntimeError("Native infeasibility contradicts the validated paid seed")
                result = best
                lower = best["cost"]
                result.update(optimal=True, proof_method="strict_cost_bound_unsat")
            elif best is not None and (result["status"] != "sat" or
                    (result["cost"], propagation_steps(result)) > (best["cost"], propagation_steps(best))):
                native_metadata = {key: result[key] for key in ("solver_seconds", "preparation_seconds") if key in result}
                result = best
                result.update(native_metadata)
                termination_result(result, native_reason)
    result.pop("model", None)
    result.update(lower_bound=lower, upper_bound=result["cost"] if result["status"] == "sat" else None,
                  propagation_steps=propagation_steps(result), max_steps=p["maxsteps"],
                  random_seed=random_seed, optimization_seconds=time.monotonic()-started)
    if result["status"] == "sat" and lower > result["cost"]:
        raise RuntimeError("Lower bound contradicts the validated basis")
    if result["status"] == "sat" and result.get("optimal"):
        result["lower_bound"] = lower = result["cost"]
    if result["status"] == "sat" and lower == result["cost"]:
        result["optimal"] = True
        if result.get("proof_method") in (None, "none"):
            result["proof_method"] = "lower_bound_matches_incumbent"
    result.setdefault("proof_method", "none")
    if result["status"] == "sat":
        result["proof_scope"] = ("minimum_guess_cost_for_prepared_deduction_model_and_depth"
                                 if result.get("optimal") else
                                 "validated_feasible_basis_at_requested_depth")
    elif result["status"] == "unsat":
        result["proof_scope"] = "infeasible_within_prepared_deduction_model_cost_cap_and_depth"
    else:
        result["proof_scope"] = "no_complete_feasible_basis_validated"
    if certificate is not None:
        result["lower_bound_certificate"] = certificate
    if refinement is not None:
        result["refinement"] = refinement
    if seed is not None:
        result.update(seed_basis=seed, seed_cost=seed_cost, seed_propagation_steps=seed_steps,
                      cost_improved=result["status"] == "sat" and result["cost"] < seed_cost,
                      propagation_improved=result["status"] == "sat" and result["cost"] == seed_cost
                      and result["propagation_steps"] < seed_steps)
    termination_result(result, result.get("termination_reason"))
    _report(data, result, p)
    return result
