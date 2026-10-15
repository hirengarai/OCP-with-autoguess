"""
Created on Aug 24, 2020

@author: Hosein Hadipour
@contact: hsn.hadipour@gmail.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

In case you use this tool please include the above copyright informations (name, contact, license)
"""

import time

from core.solverresult import (
    current_result, basis_result, solve_sat, remaining_time, timed_search,
    termination_result, get_time_limit,
)


def _parse_extra_known(parameters):
    """Parse --known into a list of variable names, or None.

    argparse declares --known with nargs='+', so the value is always a list
    (or None). Each element may itself be a comma-separated string
    ("a,b,c") or a single name. We accept a bare string too for callers
    that build the parameters dict directly.
    """
    ek = parameters.get("known", None)
    if ek is None:
        return None
    if isinstance(ek, str):
        ek = [ek]
    result = []
    for item in ek:
        result.extend(v.strip() for v in item.split(",") if v.strip())
    return result or None


def _common(parameters):
    return dict(
        inputfile_name=parameters["inputfile"], outputfile_name=parameters["outputfile"],
        max_guess=parameters["maxguess"], max_steps=parameters["maxsteps"],
        tikz=parameters.get("tikz", 0), preprocess=parameters.get("preprocess", 0),
        D=parameters.get("D", 2), dglayout=parameters.get("dglayout", "dot"),
        drawgraph=parameters.get("drawgraph", True), log=parameters.get("log", 0),
        extra_known=_parse_extra_known(parameters),
    )


def _sat_solver(parameters):
    from core.gdsat import ReduceGDtoSAT
    backend = parameters.get("satsolver") or (
        "glucose3" if get_time_limit(parameters) != -1 else "cadical153"
    )
    return ReduceGDtoSAT(**_common(parameters), sat_solver=backend)


def _extract_sat_model(solver, model):
    from core.varnames import step_var
    positive = set(literal for literal in model if literal > 0)
    solver.solutions = [
        {step_var(v, step): int(solver.variables_dictionary[step_var(v, step)] in positive)
         for v in solver.variables}
        for step in range(solver.max_steps + 1)
    ]


def _save_sat_solution(solver, model):
    from core.parsesolution import parse_solver_solution
    from core.graphdrawer import draw_graph
    _extract_sat_model(solver, model)
    parse_solver_solution(solver)
    if solver.draw_graph:
        draw_graph(solver.vertices, solver.edges, solver.known_variables, solver.guessed_vars,
                   solver.output_dir, solver.tikz, solver.dglayout)


def _findmin_sat_incremental(parameters, start_mg, _w=None):
    """Minimize count or weight, preserving the best model and proof status.

    The time limit covers the complete descent. A timeout after a feasible
    solution returns that solution with optimal=False, never a false optimum.
    """
    from pysat import solvers, pb
    from pysat.card import ITotalizer

    started = time.monotonic()
    solver = _sat_solver(parameters)
    solver.generate_sat_constraints()
    solver.generate_boundary_no_cardinality()
    literals, weights = solver.get_cardinality_lits()
    sat = solvers.Solver(name=solver.sat_solver_name)
    totalizer = None
    best_model = None
    best_cost = None
    proven = False
    last_status = None
    bound = start_mg
    top_id = solver.top_variable_identifier_so_far
    stop_reason = "unknown"
    try:
        sat.append_formula(solver.cnf_formula)
        if weights is None and literals:
            totalizer = ITotalizer(lits=literals, ubound=min(bound + 1, len(literals)), top_id=top_id)
            sat.append_formula(totalizer.cnf.clauses)
        while bound >= 0:
            assumptions = []
            if totalizer is not None and bound < len(totalizer.rhs):
                assumptions = [-totalizer.rhs[bound]]
            elif weights is not None and literals:
                encoding = pb.PBEnc.leq(lits=literals, weights=weights, bound=bound,
                                        top_id=top_id, encoding=pb.EncType.binmerge)
                sat.append_formula(encoding.clauses)
                top_id = max(top_id, encoding.nv)
            remaining = remaining_time(parameters)
            try:
                last_status = solve_sat(sat, solver.sat_solver_name, remaining, assumptions)
            except KeyboardInterrupt:
                last_status = None
                stop_reason = "interrupted"
                break
            if last_status is not True:
                proven = last_status is False and best_model is not None
                stop_reason = ("optimal" if proven else "infeasible") if last_status is False else (
                    "time_limit" if remaining != -1 else "unknown"
                )
                break
            model = sat.get_model()
            positive = set(literal for literal in model if literal > 0)
            best_cost = sum(weight for literal, weight in zip(literals, weights or [1] * len(literals))
                            if literal in positive)
            best_model = model
            print("  max_guess = %d: SAT (cost %d)" % (bound, best_cost))
            if best_cost == 0:
                proven = True
                stop_reason = "optimal"
                break
            bound = best_cost - 1
    finally:
        sat.delete()
        if totalizer is not None:
            totalizer.delete()
    solver.termination_reason = stop_reason
    if best_model is None:
        return current_result(solver, last_status)
    solver.max_guess = best_cost
    _save_sat_solution(solver, best_model)
    result = current_result(solver, True, optimal=proven)
    result["optimization_time"] = time.monotonic() - started
    print("FIND-MIN RESULT: %s cost = %d" % ("minimum" if proven else "best found", best_cost))
    return result


def _findmin_descent(parameters, solver_type):
    if solver_type == "sat":
        return _findmin_sat_incremental(parameters, parameters["maxguess"])
    bound = parameters["maxguess"]
    best = None
    while bound >= 0:
        iteration = dict(parameters, maxguess=bound, findmin=False)
        result = search_using_smt(iteration)
        if result["status"] != "sat":
            if best is not None:
                best["optimal"] = result["status"] == "unsat"
                return termination_result(best, result["termination_reason"])
            return result
        best = result
        if result["cost"] == 0:
            best["optimal"] = True
            return termination_result(best)
        bound = result["cost"] - 1
    return best


@timed_search
def search_using_sat(parameters):
    if parameters.get("findmin", False):
        return _findmin_descent(parameters, "sat")
    solver = _sat_solver(parameters)
    solver.make_model()
    solver.time_limit = remaining_time(parameters)
    return current_result(solver, solver.solve_via_satsolver())


@timed_search
def search_using_smt(parameters):
    from core.gdsmt import ReduceGDtoSMT
    if parameters.get("findmin", False):
        return _findmin_descent(parameters, "smt")
    solver = ReduceGDtoSMT(**_common(parameters), smt_solver_name=parameters.get("smtsolver", "z3"))
    try:
        solver.make_model()
        solver.time_limit = remaining_time(parameters)
        return current_result(solver, solver.solve_via_smtsolver())
    finally:
        solver.smt_solver.exit()


@timed_search
def search_using_cp(parameters):
    from core.gdcp import ReduceGDtoCP
    solver = ReduceGDtoCP(**_common(parameters), cp_solver_name=parameters.get("cpsolver", "cp-sat"),
                         cp_optimization=parameters.get("cpoptimization", 0), threads=parameters.get("threads", 0))
    solver.make_model()
    solver.time_limit = remaining_time(parameters)
    outcome = solver.solve_via_cpsolver()
    return current_result(solver, outcome, optimal=getattr(solver, "optimal", False))


@timed_search
def search_using_milp(parameters):
    from core.gdmilp import ReduceGDtoMILP
    solver = ReduceGDtoMILP(**_common(parameters), direction=parameters.get("milpdirection", "min"),
                           threads=parameters.get("threads", 0))
    try:
        solver.make_model()
        solver.time_limit = remaining_time(parameters)
        outcome = solver.solve_model()
        return current_result(solver, outcome, optimal=getattr(solver, "optimal", False))
    finally:
        if hasattr(solver, "milp_model"):
            solver.milp_model.dispose()


def search_using_groebnerbasis(parameters):
    raise RuntimeError("Groebner solver requires SageMath; use the original AutoGuess or another backend")


def _heuristic_search(parameters, name):
    if get_time_limit(parameters) != -1:
        raise ValueError("%s cannot enforce time limits; use SAT, CP, MILP or SMT/Z3" % name)
    import copy
    if name == "mark":
        from core.gdmark import Mark as Solver
    else:
        from core.gdelim import Elim as Solver
    solver = Solver(inputfile_name=parameters["inputfile"], outputfile_name=parameters["outputfile"],
                    tikz=parameters.get("tikz", 0), preprocess=parameters.get("preprocess", 0),
                    D=parameters.get("D", 2), log=parameters.get("log", 0),
                    extra_known=_parse_extra_known(parameters))
    data = copy.deepcopy(solver.__dict__)
    solver.find_minimal_guess_basis()
    guesses = [v for v in solver.guess_basis if v not in data["known_variables"]]
    # Heuristics do not implement forbidden guesses or a hard budget. Validate
    # the returned candidate, and do not mistake failure for an UNSAT proof.
    weights = data.get("target_weights") or {}
    cost = sum(weights.get(v, 1) for v in guesses)
    if (set(guesses) & set(data["notguessed_variables"]) or
            cost > parameters["maxguess"]):
        return current_result(solver, None)
    return basis_result(data, guesses, max_steps=parameters["maxsteps"])


@timed_search
def search_using_mark(parameters):
    return _heuristic_search(parameters, "mark")


@timed_search
def search_using_elim(parameters):
    return _heuristic_search(parameters, "elim")


@timed_search
def search_using_propagate(parameters):
    if get_time_limit(parameters) != -1:
        raise ValueError("Propagation and basis reduction cannot enforce time limits; omit timelimit")
    from core.inputparser import read_relation_file
    from core.propagate import reduce_basis
    extra_known = _parse_extra_known(parameters)
    # Keep fixed file-known variables distinct from the guess basis.
    data = read_relation_file(parameters["inputfile"], preprocess=parameters.get("preprocess", 0),
                              D=parameters.get("D", 2), log=parameters.get("log", 0),
                              extra_known=None if parameters.get("reducebasis", False) else extra_known)
    if parameters.get("reducebasis", False):
        if extra_known is None:
            raise ValueError("--reducebasis requires --known with the initial guess basis")
        reduced = reduce_basis(data, extra_known, max_steps=parameters.get("maxsteps"))
        if reduced is None:
            result = basis_result(data, [], max_steps=parameters.get("maxsteps"))
            result["status"] = "unknown"
            result["reduced_basis"] = None
            return result
        result = basis_result(data, reduced, max_steps=parameters.get("maxsteps"))
        result["reduced_basis"] = reduced
        result["optimal_subset"] = True
        return result
    return basis_result(data, [], max_steps=parameters.get("maxsteps"))


@timed_search
def search_using_reducebasis(parameters):
    return search_using_propagate(dict(parameters, reducebasis=True))
