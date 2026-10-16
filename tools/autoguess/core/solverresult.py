"""Current-run results and independent knowledge-closure validation.

Reports are presentation artifacts; callers must never infer success by reading
an output filename left by a previous solve.
"""

from contextvars import ContextVar
from functools import wraps
import math
import os
import tempfile
from threading import Timer
import time

from core.varnames import step_var


_active_budget = ContextVar("autoguess_search_budget", default=None)


def _validate_time_limit(time_limit):
    if (isinstance(time_limit, bool) or not isinstance(time_limit, (int, float))
            or not math.isfinite(time_limit) or (time_limit < 0 and time_limit != -1)):
        raise ValueError("Time limit must be nonnegative or -1 (finite numeric values only)")
    return time_limit


def get_time_limit(parameters):
    """Resolve one upstream time_limit value, retaining the timelimit alias."""
    if "time_limit" in parameters:
        time_limit = _validate_time_limit(parameters["time_limit"])
        if "timelimit" in parameters:
            legacy = _validate_time_limit(parameters["timelimit"])
            if legacy != time_limit:
                raise ValueError("Conflicting time_limit and timelimit values; use one value")
        return time_limit
    return _validate_time_limit(parameters.get("timelimit", -1))


class SearchBudget:
    """One cooperative deadline shared by preprocessing and optimization."""

    def __init__(self, time_limit):
        self.time_limit = _validate_time_limit(time_limit)
        self.started = time.monotonic()

    def remaining(self):
        if self.time_limit == -1:
            return -1
        return max(0.0, self.time_limit - (time.monotonic() - self.started))


def remaining_time(parameters):
    """Return the remaining request budget, rather than restarting each solve."""
    budget = _active_budget.get()
    return budget.remaining() if budget is not None else get_time_limit(parameters)


def termination_result(result, reason=None):
    """Keep feasibility, optimality and the reason for stopping independent."""
    if result.get("optimal"):
        reason = "optimal"
    elif result["status"] == "unsat":
        reason = "infeasible"
    elif reason is None:
        reason = "solution_found" if result["status"] == "sat" else "unknown"
    elif result["status"] == "unknown" and reason not in ("time_limit", "interrupted"):
        reason = "unknown"
    result["termination_reason"] = reason
    result["timed_out"] = reason == "time_limit"
    return result


def timed_search(function):
    """Time a search request; nested calls and descent iterations share its limit.

    Preparation checks its budget before invoking the native solver. Python
    preprocessing/encoding are not preemptible, and validation/reporting may
    finish after the search deadline. OCP relation generation precedes this
    engine-level budget.
    """
    @wraps(function)
    def wrapped(parameters, *args, **kwargs):
        time_limit = get_time_limit(parameters)
        # Native backends retain upstream's self.time_limit. Do not inject
        # another spelling into a caller's dictionary: it may be reused with
        # an updated legacy timelimit on the next invocation.
        budget = _active_budget.get()
        token = None
        if budget is None:
            budget = SearchBudget(time_limit)
            token = _active_budget.set(budget)
        try:
            result = function(parameters, *args, **kwargs)
            reason = result.get("termination_reason")
            if result["status"] == "unknown" and reason in (None, "unknown") and budget.remaining() == 0:
                reason = "time_limit"
            termination_result(result, reason)
            result["time_limit"] = budget.time_limit
            result["time_limit_seconds"] = result["time_limit"]
            if token is not None and result.get("outputfile"):
                # The current validated report must carry its proof/stop
                # status even when it is opened without the API/CLI result.
                with open(result["outputfile"]) as stream:
                    report = stream.read()
                summary = (
                    "Search status: %s\nTermination reason: %s\n"
                    "Timed out: %s\nOptimal guess cost proved: %s\n"
                    "Requested search time limit (seconds): %s\n\n"
                    % (result["status"], result["termination_reason"],
                       "yes" if result["timed_out"] else "no",
                       "yes" if result["optimal"] else "no", budget.time_limit)
                )
                atomic_write(result["outputfile"], summary + report)
            result["elapsed_seconds"] = max(0.0, time.monotonic() - budget.started)
            return result
        finally:
            if token is not None:
                _active_budget.reset(token)
    return wrapped


def knowledge_trace(data, initial, max_steps=None):
    """Return synchronous closure and newly determined IDs at every step."""
    variables = list(data["variables"])
    known = set(initial)
    if not known.issubset(variables):
        raise ValueError("Initially known variables must belong to the relation system")
    trace = [{"step": 0, "determined_vars": [v for v in variables if v in known]}]
    limit = len(variables) if max_steps is None else max_steps
    for step in range(1, limit + 1):
        new = set()
        for relation in data["symmetric_relations"]:
            missing = [v for v in relation if v not in known]
            if len(missing) == 1:
                new.add(missing[0])
        for relation in data["implication_relations"]:
            if all(v in known for v in relation[:-1]):
                new.add(relation[-1])
        new -= known
        if not new:
            break
        known.update(new)
        trace.append({"step": step, "determined_vars": [v for v in variables if v in new]})
    return known, trace


def current_result(solver, status, optimal=False):
    """Adapt a backend's bool/None outcome without consulting old reports."""
    if status is True:
        status = "sat"
    elif status is False:
        status = "unsat"
    elif status is None:
        status = "unknown"
    result = {
        "status": status,
        "guessed_variables": [],
        "known_variables": list(solver.known_variables),
        "target_variables": list(solver.target_variables),
        "determination_steps": [],
        "optimal": False,
        "cost": None,
        "outputfile": None,
        "targets_covered": False,
        "covered_target_variables": [],
        "missing_targets": list(solver.target_variables),
        "finally_known": [],
    }
    reason = getattr(solver, "termination_reason", None)
    if status != "sat":
        return termination_result(result, reason)
    guesses = [v for v in solver.variables
               if solver.solutions[0][step_var(v, 0)] and v not in solver.known_variables]
    result = basis_result(
        solver.__dict__, guesses, max_steps=solver.max_steps,
        optimal=optimal, outputfile=getattr(solver, "_report_written", None),
        max_guess=solver.max_guess,
    )
    lower_bound = getattr(solver, "lower_bound", None)
    if lower_bound is not None and math.isfinite(lower_bound):
        result["lower_bound"] = lower_bound
    for key in ("graph_files", "graph_summary", "graph_warnings"):
        value = getattr(solver, "_" + key, None)
        if value is not None:
            result[key] = value
    return termination_result(result, reason)


def basis_result(data, guesses, max_steps=None, optimal=False, outputfile=None, max_guess=None):
    known = list(data["known_variables"])
    guesses = list(dict.fromkeys(guesses))
    if set(guesses) & set(data.get("notguessed_variables", [])):
        raise RuntimeError("Solver selected a variable forbidden from being guessed")
    weights = data.get("target_weights") or {}
    cost = sum(weights.get(v, 1) for v in guesses)
    if max_guess is not None and cost > max_guess:
        raise RuntimeError("Solver exceeded the requested guess bound")
    final_known, trace = knowledge_trace(data, known + guesses, max_steps)
    targets = list(data["target_variables"])
    missing = [v for v in targets if v not in final_known]
    return termination_result({
        "status": "sat" if not missing else "unknown",
        "guessed_variables": guesses,
        "known_variables": known,
        "target_variables": targets,
        "determination_steps": trace,
        "finally_known": [v for v in data["variables"] if v in final_known],
        "targets_covered": not missing,
        "covered_target_variables": [v for v in targets if v in final_known],
        "missing_targets": missing,
        "optimal": bool(optimal) and not missing,
        "cost": cost,
        "outputfile": outputfile if not missing else None,
    })


def atomic_write(path, content):
    """Replace a complete report atomically, including when the name is reused."""
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(prefix=".autoguess-", dir=directory, text=True)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def solve_sat(solver, solver_name, time_limit=-1, assumptions=None):
    """Enforce supported wall-clock limits and always cancel/join the timer."""
    from pysat import solvers

    assumptions = assumptions or []
    if time_limit == -1:
        return solver.solve(assumptions=assumptions)
    if time_limit < 0:
        raise ValueError("Time limit must be nonnegative or -1")
    unsupported = set()
    for name in ("cadical103", "cadical153", "cadical195", "cadical300", "lingeling"):
        unsupported.update(getattr(solvers.SolverNames, name, ()))
    if solver_name in unsupported:
        raise ValueError("SAT solver %s cannot enforce time limits; use glucose3 or omit timelimit" % solver_name)
    if time_limit == 0:
        return None
    timer = Timer(time_limit, solver.interrupt)
    timer.daemon = True
    timer.start()
    try:
        return solver.solve_limited(assumptions=assumptions, expect_interrupt=True)
    finally:
        timer.cancel()
        timer.join()
        solver.clear_interrupt()
