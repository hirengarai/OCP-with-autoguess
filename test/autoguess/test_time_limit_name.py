"""The upstream ``time_limit`` name and the legacy alias share one deadline."""

import importlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.autoguess_wrapper import _with_autoguess_path, run_autoguess


@_with_autoguess_path
def engine_module(name):
    return importlib.import_module(name)


def relation_file(tmp_path):
    source = tmp_path / "relations.txt"
    source.write_text("connection relations\na=>t\ntarget\nt\nnot guessed\nt\nend\n")
    return source


def solve(tmp_path, **options):
    return run_autoguess(
        relation_file(tmp_path), outputfile=tmp_path / "report.txt",
        maxguess=1, maxsteps=1, drawgraph=False, threads=1, **options,
    )


@pytest.mark.parametrize("parameters, expected", [
    ({}, -1),
    ({"time_limit": -1}, -1),
    ({"time_limit": 0}, 0),
    ({"time_limit": 2.5}, 2.5),
    ({"timelimit": 2.5}, 2.5),
    ({"time_limit": 2.5, "timelimit": 2.5}, 2.5),
])
def test_parameter_dictionary_resolves_one_time_limit(parameters, expected):
    timing = engine_module("core.solverresult")
    assert timing.get_time_limit(parameters) == expected


@pytest.mark.parametrize("canonical, legacy", [(1, 2), (0, -1), (-1, 0)])
def test_conflicting_explicit_parameter_names_are_rejected(canonical, legacy):
    timing = engine_module("core.solverresult")
    with pytest.raises(ValueError, match="[Cc]onflict|[Dd]iffer|[Ss]ame|[Mm]atch"):
        timing.get_time_limit({"time_limit": canonical, "timelimit": legacy})


@pytest.mark.parametrize("limit", [-1, 0, 10.5])
def test_real_sat_accepts_canonical_name_and_preserves_legacy_results(tmp_path, limit):
    canonical = solve(tmp_path, time_limit=limit)
    legacy = solve(tmp_path, timelimit=limit)
    for result in (canonical, legacy):
        assert result["time_limit"] == result["time_limit_seconds"] == limit
        assert result["parameters"]["time_limit"] == result["parameters"]["timelimit"] == limit
    for key in ("status", "cost", "guessed_variables", "targets_covered", "optimal",
                "termination_reason", "timed_out"):
        assert canonical[key] == legacy[key]
    if limit == 0:
        assert canonical["status"] == "unknown"
        assert canonical["termination_reason"] == "time_limit"
        assert canonical["guessed_variables"] == []
        assert canonical["parameters"]["satsolver"] == "glucose3"
    else:
        assert canonical["status"] == "sat"
        assert canonical["guessed_variables"] == ["a"]
        assert canonical["cost"] == 1 and canonical["targets_covered"]
        assert canonical["parameters"]["satsolver"] == (
            "cadical153" if limit == -1 else "glucose3"
        )


def test_equal_wrapper_names_are_accepted(tmp_path):
    result = solve(tmp_path, time_limit=10.5, timelimit=10.5)
    assert result["status"] == "sat" and result["cost"] == 1
    assert result["time_limit"] == result["time_limit_seconds"] == 10.5


@pytest.mark.parametrize("options", [
    {"time_limit": 1, "timelimit": 2},
    {"time_limit": -1, "timelimit": 2},
])
def test_wrapper_conflicts_preserve_previous_report(tmp_path, monkeypatch, options):
    search = engine_module("core.search")
    report = tmp_path / "report.txt"
    report.write_text("saved successful report\n")

    def must_not_construct(parameters):
        pytest.fail("Conflicting aliases reached the SAT backend")

    monkeypatch.setattr(search, "_sat_solver", must_not_construct)
    with pytest.raises(ValueError, match="[Cc]onflict|[Dd]iffer|[Ss]ame|[Mm]atch"):
        solve(tmp_path, **options)
    assert report.read_text() == "saved successful report\n"


@pytest.mark.parametrize("limit", [-2, -0.1, float("nan"), float("inf"), True, "2"])
def test_invalid_canonical_limit_fails_before_backend_or_report_changes(tmp_path, monkeypatch, limit):
    search = engine_module("core.search")
    report = tmp_path / "report.txt"
    report.write_text("saved successful report\n")

    def must_not_construct(parameters):
        pytest.fail("Invalid canonical time limit reached the SAT backend")

    monkeypatch.setattr(search, "_sat_solver", must_not_construct)
    with pytest.raises(ValueError, match="Time limit must be"):
        solve(tmp_path, time_limit=limit)
    assert report.read_text() == "saved successful report\n"


def test_canonical_deadline_reaches_existing_sat_timer_across_optimization(tmp_path, monkeypatch):
    search = engine_module("core.search")
    timing = engine_module("core.solverresult")
    original_solve = search.solve_sat
    clock, received = [1000.0], []
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])

    def solve_then_exhaust_budget(solver, solver_name, time_limit=-1, assumptions=None):
        received.append(time_limit)
        outcome = original_solve(solver, solver_name, time_limit, assumptions)
        if outcome is True:
            clock[0] += 11
        return outcome

    monkeypatch.setattr(search, "solve_sat", solve_then_exhaust_budget)
    result = solve(tmp_path, time_limit=10, findmin=True)
    assert received == [10, 0], "Both names must use the existing shared timer"
    assert result["status"] == "sat" and result["guessed_variables"] == ["a"]
    assert result["optimal"] is False and result["timed_out"] is True
    assert result["termination_reason"] == "time_limit"
    assert result["time_limit"] == result["time_limit_seconds"] == 10
    assert result["elapsed_seconds"] == 11


@pytest.mark.parametrize("name", ["time_limit", "timelimit"])
def test_direct_engine_dictionary_can_be_reused_with_a_changed_limit(tmp_path, name):
    search = engine_module("core.search")
    parameters = {
        "inputfile": str(relation_file(tmp_path)),
        "outputfile": str(tmp_path / "direct_report.txt"),
        "maxguess": 1, "maxsteps": 1, "drawgraph": False,
        name: 0,
    }
    timed_out = search.search_using_sat(parameters)
    assert timed_out["status"] == "unknown" and timed_out["time_limit"] == 0
    other_name = "timelimit" if name == "time_limit" else "time_limit"
    assert other_name not in parameters, "Do not inject a stale competing alias into a caller's dictionary"
    parameters[name] = 10.5
    completed = search.search_using_sat(parameters)
    assert completed["status"] == "sat" and completed["guessed_variables"] == ["a"]
    assert completed["time_limit"] == completed["time_limit_seconds"] == 10.5
    assert other_name not in parameters


@pytest.mark.parametrize("backend, module_name, class_name, solve_method", [
    ("cp", "core.gdcp", "ReduceGDtoCP", "solve_via_cpsolver"),
    ("milp", "core.gdmilp", "ReduceGDtoMILP", "solve_model"),
    ("smt", "core.gdsmt", "ReduceGDtoSMT", "solve_via_smtsolver"),
])
def test_canonical_budget_sets_existing_native_solver_time_limit(
    tmp_path, monkeypatch, backend, module_name, class_name, solve_method,
):
    solver_class = getattr(engine_module(module_name), class_name)
    timing = engine_module("core.solverresult")
    clock, received = [1000.0], []
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])

    def model_takes_three_seconds(instance):
        clock[0] += 3

    def record_native_limit(instance):
        received.append(instance.time_limit)
        return None

    monkeypatch.setattr(solver_class, "make_model", model_takes_three_seconds)
    monkeypatch.setattr(solver_class, solve_method, record_native_limit)
    result = solve(tmp_path, solver=backend, time_limit=10)
    assert received == [7], "The upstream native field must receive the remaining shared budget"
    assert result["status"] == "unknown"
    assert result["time_limit"] == result["time_limit_seconds"] == 10


def xor_function():
    from operators.boolean_operators import XOR
    from primitives.primitives import Layered_Function

    function = Layered_Function("TIME_LIMIT_NAME_XOR", "u", 1, 1, 3, 0, 1)
    a, b = function.vars[1][0][:2]
    target = function.vars[1][1][0]
    function.constraints[1][0] = [XOR([a, b], [target], ID="TIME_LIMIT_NAME_XOR_1_1_0")]
    return function, a, b, target


@pytest.mark.parametrize("config", [
    {"time_limit": 10.5},
    {"timelimit": 10.5},
    {"time_limit": 10.5, "timelimit": 10.5},
    {"time_limit": 0},
])
def test_public_ocp_config_uses_canonical_and_legacy_names(tmp_path, config):
    from attacks.attacks import guess_and_determine_attack

    function, a, b, target = xor_function()
    result = guess_and_determine_attack(
        function, known_vars=[a.ID], target_vars=[target.ID],
        objective_target="AT MOST 1", show_mode=0,
        config_model={"filename": str(tmp_path / "ocp_relations.txt"), "maxsteps": 2},
        config_solver=config,
    )
    limit = config.get("time_limit", config.get("timelimit"))
    assert result["time_limit"] == result["time_limit_seconds"] == limit
    assert result["parameters"]["satsolver"] == "glucose3"
    assert result["target_variable_ids"] == [target.ID]
    if limit == 0:
        assert result["status"] == "unknown" and result["timed_out"]
    else:
        assert result["status"] == "sat" and result["guessed_variables"] == [b]
        assert result["cost"] == 1 and result["targets_covered"]


def test_public_ocp_config_rejects_conflicts_before_generating_relations(tmp_path):
    from attacks.attacks import guess_and_determine_attack

    function, a, _, target = xor_function()
    source = tmp_path / "ocp_relations.txt"
    source.write_text("existing relation input\n")
    with pytest.raises(ValueError, match="[Cc]onflict|[Dd]iffer|[Ss]ame|[Mm]atch"):
        guess_and_determine_attack(
            function, known_vars=[a.ID], target_vars=[target.ID],
            objective_target="AT MOST 1", show_mode=0,
            config_model={"filename": str(source), "maxsteps": 2},
            config_solver={"time_limit": 1, "timelimit": 2},
        )
    assert source.read_text() == "existing relation input\n"


@pytest.mark.parametrize("limit, legacy", [(0, False), (1, True)])
def test_public_ocp_config_does_not_hide_invalid_equal_legacy_value(tmp_path, limit, legacy):
    from attacks.attacks import guess_and_determine_attack

    function, a, _, target = xor_function()
    source = tmp_path / "ocp_relations.txt"
    source.write_text("existing relation input\n")
    with pytest.raises(ValueError, match="Time limit must be"):
        guess_and_determine_attack(
            function, known_vars=[a.ID], target_vars=[target.ID],
            objective_target="AT MOST 1", show_mode=0,
            config_model={"filename": str(source), "maxsteps": 2},
            config_solver={"time_limit": limit, "timelimit": legacy},
        )
    assert source.read_text() == "existing relation input\n"
