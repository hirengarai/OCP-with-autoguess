"""Deadline and incumbent regressions, without timing-dependent solver races.

The SAT encoding and every returned basis are real. Interruption is injected
only at the solver boundary so these checks do not depend on machine speed.
"""

import importlib
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.autoguess_wrapper import _with_autoguess_path, run_autoguess


@_with_autoguess_path
def engine_module(name):
    return importlib.import_module(name)


def source_file(tmp_path, weighted=False):
    path = tmp_path / "relations.txt"
    text = (
        "connection relations\na,b=>t\nc=>t\ntarget\nt\nnot guessed\nt\n"
        "weights\na 5\nb 2\nc 2\n"
        if weighted else "connection relations\na=>t\ntarget\nt\nnot guessed\nt\n"
    )
    path.write_text(text + "end\n")
    return path


def search(tmp_path, source, **options):
    params = dict(outputfile=tmp_path / "report.txt", maxguess=1, maxsteps=1,
                  drawgraph=False, satsolver="glucose3", threads=1)
    params.update(options)
    return run_autoguess(source, **params)


def assert_metadata(result, *, reason, timeout, limit):
    assert result["termination_reason"] == reason
    assert result["timed_out"] is timeout
    assert result["time_limit_seconds"] == limit
    assert math.isfinite(result["elapsed_seconds"])
    assert result["elapsed_seconds"] >= 0


def independently_check_basis(result, *, weighted=False):
    """Check the concrete test equations without the engine's closure helper."""
    reached = set(result["known_variables"]) | set(result["guessed_variables"])
    initial = reached.copy()
    premises_known = {"a", "b"} <= initial if weighted else "a" in initial
    if premises_known:
        reached.add("t")
    if weighted and "c" in initial:
        reached.add("t")
    weights = {"a": 5, "b": 2, "c": 2} if weighted else {"a": 1}
    assert "t" in reached
    assert "t" not in result["guessed_variables"]
    assert result["cost"] == sum(weights[v] for v in result["guessed_variables"])
    assert result["targets_covered"] and result["missing_targets"] == []


@pytest.mark.parametrize("last_outcome", [None, False], ids=["timeout", "proof"])
def test_findmin_keeps_best_improved_incumbent(tmp_path, monkeypatch, last_outcome):
    engine = engine_module("core.search")
    variable_name = engine_module("core.varnames").step_var
    original_factory, original_solve = engine._sat_solver, engine.solve_sat
    instances, calls = [], []

    def capture_solver(parameters):
        instance = original_factory(parameters)
        instances.append(instance)
        return instance

    def controlled_solve(solver, solver_name, time_limit=-1, assumptions=None):
        instance = instances[0]
        calls.append(time_limit)
        if len(calls) == 3:
            # A real UNSAT proof under the final tighter bound distinguishes
            # proven optimality from the interrupted branch.
            if last_outcome is False:
                assert original_solve(solver, solver_name, time_limit, assumptions) is False
            return last_outcome
        selected = {"a", "b"} if len(calls) == 1 else {"c"}
        force_basis = [
            instance.variables_dictionary[variable_name(v, 0)] * (1 if v in selected else -1)
            for v in "abc"
        ]
        assert original_solve(solver, solver_name, time_limit,
                              list(assumptions or []) + force_basis) is True
        return True

    monkeypatch.setattr(engine, "_sat_solver", capture_solver)
    monkeypatch.setattr(engine, "solve_sat", controlled_solve)
    source = source_file(tmp_path, weighted=True)
    report = tmp_path / "report.txt"
    report.write_text("previous run with a different basis")
    result = search(tmp_path, source, maxguess=9, findmin=True, timelimit=10)

    assert len(calls) == 3
    assert result["status"] == "sat" and result["guessed_variables"] == ["c"]
    assert result["cost"] == 2 and result["optimal"] is (last_outcome is False)
    independently_check_basis(result, weighted=True)
    assert_metadata(result, reason="time_limit" if last_outcome is None else "optimal",
                    timeout=last_outcome is None, limit=10)
    assert Path(result["outputfile"]) == report
    assert "previous run" not in report.read_text()
    assert "Total guess weight: 2" in report.read_text()
    assert "Termination reason: " + result["termination_reason"] in report.read_text()
    assert "Optimal guess cost proved: " + ("yes" if result["optimal"] else "no") in report.read_text()


def test_findmin_deadline_is_shared_across_descent(tmp_path, monkeypatch):
    engine = engine_module("core.search")
    timing = engine_module("core.solverresult")
    original_solve = engine.solve_sat
    clock, calls = [1000.0], []
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])

    def first_solution_then_budget_expires(solver, solver_name, time_limit=-1, assumptions=None):
        calls.append(time_limit)
        if time_limit == 0:
            # The helper must short-circuit here without entering native SAT.
            return original_solve(solver, solver_name, time_limit, assumptions)
        assert original_solve(solver, solver_name, time_limit, assumptions) is True
        clock[0] += 11
        return True

    monkeypatch.setattr(engine, "solve_sat", first_solution_then_budget_expires)
    source = source_file(tmp_path)
    result = search(tmp_path, source, findmin=True, timelimit=10)
    assert calls == [10, 0], "The tighter bound must receive the original exhausted budget"
    assert result["status"] == "sat" and result["optimal"] is False
    independently_check_basis(result)
    assert_metadata(result, reason="time_limit", timeout=True, limit=10)
    assert result["elapsed_seconds"] == 11


def test_preprocessing_uses_same_budget_as_solver(tmp_path, monkeypatch):
    entrypoint = engine_module("autoguess")
    timing = engine_module("core.solverresult")
    engine = engine_module("core.search")
    original_defaults = entrypoint._resolve_dynamic_defaults
    original_solve = engine.solve_sat
    clock, limits = [1000.0], []
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])

    def expensive_defaults(parameters):
        original_defaults(parameters)
        clock[0] += 3

    def record_limit(solver, solver_name, time_limit=-1, assumptions=None):
        limits.append(time_limit)
        return original_solve(solver, solver_name, time_limit, assumptions)

    monkeypatch.setattr(entrypoint, "_resolve_dynamic_defaults", expensive_defaults)
    monkeypatch.setattr(engine, "solve_sat", record_limit)
    source = source_file(tmp_path)
    result = search(tmp_path, source, findmin=True, maxguess=None, maxsteps=None, timelimit=10)
    independently_check_basis(result)
    assert limits and all(0 < limit <= 7 for limit in limits)
    assert_metadata(result, reason="optimal", timeout=False, limit=10)
    assert result["elapsed_seconds"] == 3


@pytest.mark.parametrize("reason", ["time_limit", "interrupted"])
def test_smt_findmin_keeps_improved_incumbent_when_later_check_stops(tmp_path, monkeypatch, reason):
    pytest.importorskip("pysmt")
    pytest.importorskip("z3")
    smt = engine_module("core.gdsmt")
    variable_name = engine_module("core.varnames").step_var
    from pysmt.shortcuts import BV, Equals

    original_solve = smt.ReduceGDtoSMT.solve_via_smtsolver
    calls = []

    def controlled_solve(instance):
        calls.append(instance.time_limit)
        if len(calls) == 3:
            instance.termination_reason = reason
            instance.timed_out = reason == "time_limit"
            return None
        selected = {"a", "b"} if len(calls) == 1 else {"c"}
        for variable in "abc":
            instance.smt_solver.add_assertion(Equals(
                instance.variables_dictionary[variable_name(variable, 0)],
                BV(int(variable in selected), 1),
            ))
        assert original_solve(instance) is True
        return True

    monkeypatch.setattr(smt.ReduceGDtoSMT, "solve_via_smtsolver", controlled_solve)
    source = source_file(tmp_path, weighted=True)
    result = search(tmp_path, source, solver="smt", maxguess=9, findmin=True, timelimit=10)
    assert len(calls) == 3 and all(0 < limit <= 10 for limit in calls)
    assert result["status"] == "sat" and result["guessed_variables"] == ["c"]
    assert result["cost"] == 2 and result["optimal"] is False
    independently_check_basis(result, weighted=True)
    assert_metadata(result, reason=reason, timeout=reason == "time_limit", limit=10)
    assert "Total guess weight: 2" in Path(result["outputfile"]).read_text()


BACKENDS = [
    pytest.param("sat", {}, False, id="sat"),
    pytest.param("sat", {"findmin": True}, True, id="sat-findmin"),
    pytest.param("smt", {}, False, id="pysmt-z3"),
    pytest.param("smt", {"findmin": True}, True, id="pysmt-z3-findmin"),
    pytest.param("cp", {"cpoptimization": 0}, False, id="cp-satisfy"),
    pytest.param("cp", {"cpoptimization": 1}, True, id="cp-optimize"),
    pytest.param("milp", {}, True, id="milp"),
]


def require_backend(backend):
    if backend == "cp":
        minizinc = pytest.importorskip("minizinc")
        engine_module("config").ensure_minizinc_driver()
        if minizinc.default_driver is None:
            pytest.skip("MiniZinc unavailable")
    elif backend == "milp":
        pytest.importorskip("gurobipy")
    elif backend == "smt":
        pytest.importorskip("pysmt")
        pytest.importorskip("z3")


@pytest.mark.parametrize("backend,options,optimal", BACKENDS)
def test_native_backends_report_finite_success_and_infeasibility(tmp_path, backend, options, optimal):
    require_backend(backend)
    source = source_file(tmp_path)
    try:
        result = search(tmp_path, source, solver=backend, timelimit=10, **options)
        infeasible = search(tmp_path, source, solver=backend, timelimit=10,
                            maxguess=0, **options)
    except Exception as error:
        if backend == "milp" and getattr(error, "errno", None) == 10009:
            pytest.skip("Gurobi license unavailable")
        raise
    assert result["status"] == "sat" and result["optimal"] is optimal
    independently_check_basis(result)
    assert_metadata(result, reason="optimal" if optimal else "solution_found",
                    timeout=False, limit=10)
    assert infeasible["status"] == "unsat" and infeasible["optimal"] is False
    assert infeasible["guessed_variables"] == [] and infeasible["outputfile"] is None
    assert_metadata(infeasible, reason="infeasible", timeout=False, limit=10)


@pytest.mark.parametrize("backend,options,optimal", BACKENDS)
def test_zero_deadline_has_no_incumbent_and_ignores_old_report(tmp_path, backend, options, optimal):
    source = source_file(tmp_path)
    report = tmp_path / "report.txt"
    report.write_text("prior successful run, not a current incumbent")
    result = search(tmp_path, source, solver=backend, timelimit=0, **options)
    assert result["status"] == "unknown"
    assert result["guessed_variables"] == [] and result["outputfile"] is None
    assert result["cost"] is None and result["optimal"] is False
    assert_metadata(result, reason="time_limit", timeout=True, limit=0)
    assert report.read_text() == "prior successful run, not a current incumbent"


@pytest.mark.parametrize("has_incumbent", [False, True])
def test_cp_timeout_preserves_only_current_run_incumbent(tmp_path, monkeypatch, has_incumbent):
    require_backend("cp")
    cp = engine_module("core.gdcp")
    minizinc = importlib.import_module("minizinc")
    variable_name = engine_module("core.varnames").step_var
    assignment = {variable_name(v, step): int(v == "a" or step == 1)
                  for step in (0, 1) for v in ("a", "t")}

    def make_model_without_native_search(instance):
        instance.cp_file_path = str(tmp_path / "unused.mzn")
        result = SimpleNamespace(
            status=minizinc.Status.SATISFIED if has_incumbent else minizinc.Status.UNKNOWN,
            solution=assignment if has_incumbent else None,
        )
        instance.cp_inst = SimpleNamespace(solve=lambda **kwargs: result)

    monkeypatch.setattr(cp.ReduceGDtoCP, "make_model", make_model_without_native_search)
    source = source_file(tmp_path)
    result = search(tmp_path, source, solver="cp", cpoptimization=1, timelimit=10)
    assert_metadata(result, reason="time_limit", timeout=True, limit=10)
    assert result["optimal"] is False
    if has_incumbent:
        assert result["status"] == "sat"
        independently_check_basis(result)
        assert Path(result["outputfile"]).is_file()
    else:
        assert result["status"] == "unknown" and result["cost"] is None
        assert result["guessed_variables"] == [] and result["outputfile"] is None


@pytest.mark.parametrize("has_incumbent", [False, True])
@pytest.mark.parametrize("stop_reason", ["TIME_LIMIT", "INTERRUPTED"])
def test_milp_native_stop_status_keeps_valid_incumbent(tmp_path, monkeypatch, has_incumbent, stop_reason):
    pytest.importorskip("gurobipy")
    milp = engine_module("core.gdmilp")
    variable_name = engine_module("core.varnames").step_var
    assignment = {variable_name(v, step): int(v == "a" or step == 1)
                  for step in (0, 1) for v in ("a", "t")}
    model = SimpleNamespace(
        params=SimpleNamespace(), Status=getattr(milp.GRB, stop_reason),
        SolCount=int(has_incumbent), objval=1, ObjBound=0,
        optimize=lambda: None, dispose=lambda: None,
        getVarByName=lambda name: SimpleNamespace(X=assignment[name], Xn=assignment[name]),
    )
    monkeypatch.setattr(milp, "read", lambda path: model)
    source = source_file(tmp_path)
    result = search(tmp_path, source, solver="milp", timelimit=10)
    assert_metadata(result, reason="time_limit" if stop_reason == "TIME_LIMIT" else "interrupted",
                    timeout=stop_reason == "TIME_LIMIT", limit=10)
    assert result["optimal"] is False
    if has_incumbent:
        assert result["status"] == "sat"
        independently_check_basis(result)
        assert Path(result["outputfile"]).is_file()
    else:
        assert result["status"] == "unknown" and result["cost"] is None
        assert result["guessed_variables"] == [] and result["outputfile"] is None


@pytest.mark.parametrize("limit", [0, 10.5])
def test_ocp_public_attack_default_solver_preserves_timeout_metadata(tmp_path, limit):
    from attacks.attacks import guess_and_determine_attack
    from operators.boolean_operators import XOR
    from primitives.primitives import Layered_Function

    function = Layered_Function("TIMEOUT_XOR", "u", 1, 1, 3, 0, 1)
    a, b = function.vars[1][0][:2]
    target = function.vars[1][1][0]
    function.constraints[1][0] = [XOR([a, b], [target], ID="TIMEOUT_XOR_1_1_0")]
    result = guess_and_determine_attack(
        function, known_vars=[a.ID], target_vars=[target.ID],
        objective_target="AT MOST 1", show_mode=0,
        config_model={"filename": str(tmp_path / "relations_timeout.txt"), "maxsteps": 2},
        config_solver={"timelimit": limit},
    )
    assert result["parameters"]["satsolver"] == "glucose3"
    assert result["target_variable_ids"] == [target.ID]
    if limit == 0:
        assert result["status"] == "unknown" and result["guessed_variables"] == []
        assert result["outputfile"] is None and result["optimal"] is False
        assert_metadata(result, reason="time_limit", timeout=True, limit=limit)
    else:
        assert result["status"] == "sat" and result["guessed_variables"] == [b]
        assert result["guessed_variable_ids"] == [b.ID] and result["targets_covered"]
        assert_metadata(result, reason="solution_found", timeout=False, limit=limit)


@pytest.mark.parametrize("limit", ["0", "10.5"])
def test_cli_accepts_fractional_budget_and_prints_stopping_reason(tmp_path, limit):
    source = source_file(tmp_path)
    report = tmp_path / "report.txt"
    report.write_text("old successful report")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools/autoguess/autoguess.py"), "-i", str(source),
         "-o", str(report), "-mg", "1", "-ms", "1", "-tl", limit, "--nograph"],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Solver: glucose3" in completed.stdout
    assert "Elapsed:" in completed.stdout
    if limit == "0":
        assert "Termination: time_limit" in completed.stdout
        assert "no complete basis was found (status: unknown)" in completed.stdout
        assert report.read_text() == "old successful report"
    else:
        assert "Termination: solution_found" in completed.stdout
        assert "Number of guessed variables: 1" in report.read_text()
        assert "old successful report" not in report.read_text()


@pytest.mark.parametrize("limit", [-2, -0.1, float("nan"), float("inf"), -float("inf"), True])
def test_invalid_time_limit_rejected_before_backend_construction(tmp_path, monkeypatch, limit):
    engine = engine_module("core.search")

    def backend_must_not_run(parameters):
        pytest.fail("Invalid time limit reached the backend constructor")

    monkeypatch.setattr(engine, "_sat_solver", backend_must_not_run)
    source = source_file(tmp_path)
    with pytest.raises(ValueError, match="Time limit must be"):
        search(tmp_path, source, timelimit=limit)
