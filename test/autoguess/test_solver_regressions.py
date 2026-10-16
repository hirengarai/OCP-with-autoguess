"""Small correctness regressions; no cipher artifacts are overwritten."""

import itertools
import importlib.util
import os
from pathlib import Path
import random
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.autoguess_wrapper import run_autoguess


def relations(tmp_path, text):
    source = tmp_path / "relations.txt"
    source.write_text(text + "\nend\n")
    return source


def solve(tmp_path, source, **options):
    defaults = dict(outputfile=str(tmp_path / "report"), maxguess=1, maxsteps=3, drawgraph=False)
    defaults.update(options)
    return run_autoguess(str(source), **defaults)


def test_unsat_never_returns_previous_report(tmp_path):
    source = relations(tmp_path, "connection relations\na,b,c\nknown\na\ntarget\nc\nnot guessed\nc")
    successful = solve(tmp_path, source)
    assert successful["status"] == "sat"
    assert successful["guessed_variables"] == ["b"]
    failed = solve(tmp_path, source, maxguess=0)
    assert failed["status"] == "unsat"
    assert failed["guessed_variables"] == []
    assert failed["outputfile"] is None


@pytest.mark.parametrize("role", ["known", "target", "not guessed", "weights"])
def test_absent_role_rejected(tmp_path, role):
    source = relations(tmp_path, "connection relations\na,b\n" + role + "\nc" + (" 2" if role == "weights" else ""))
    with pytest.raises(ValueError, match="absent from relations"):
        solve(tmp_path, source)


def test_empty_relations_do_not_create_empty_variable(tmp_path):
    source = relations(tmp_path, "connection relations\n")
    result = solve(tmp_path, source, maxguess=0, findmin=True)
    assert result["status"] == "sat"
    assert result["target_variables"] == []
    assert result["guessed_variables"] == []
    assert result["optimal"] is True


@pytest.mark.parametrize("preprocess", [-1, 2, "1"])
def test_invalid_preprocess_cannot_silently_drop_equations(tmp_path, preprocess):
    source = relations(tmp_path, "algebraic relations\na+b\nknown\na\ntarget\nb")
    with pytest.raises(ValueError, match="preprocess must be 0 or 1"):
        solve(tmp_path, source, preprocess=preprocess)


@pytest.mark.parametrize("malformed", ["a,,b", "a=>", "=>a", "a=>b=>c"])
def test_malformed_relation_does_not_create_phantom_variables(tmp_path, malformed):
    source = relations(tmp_path, "connection relations\n" + malformed)
    with pytest.raises(ValueError, match="Empty variable|Malformed implication"):
        solve(tmp_path, source)


@pytest.mark.parametrize("extra", [False, True])
def test_known_variable_may_also_be_forbidden(tmp_path, extra):
    source = relations(tmp_path, "connection relations\na=>b\n" + ("" if extra else "known\na\n") + "target\nb\nnot guessed\na\nb")
    result = solve(tmp_path, source, maxguess=0, known=["a"] if extra else None)
    assert result["status"] == "sat"
    assert result["guessed_variables"] == []


def test_zero_guess_findmin_saves_current_solution(tmp_path):
    source = relations(tmp_path, "connection relations\na,b\nknown\na\ntarget\nb\nnot guessed\nb")
    (tmp_path / "report").write_text("old successful basis")
    result = solve(tmp_path, source, findmin=True)
    assert result["status"] == "sat" and result["optimal"] is True
    assert result["cost"] == 0 and result["guessed_variables"] == []
    assert "old successful basis" not in Path(result["outputfile"]).read_text()
    assert "b" in result["determination_steps"][1]["determined_vars"]


@pytest.mark.parametrize("weight", [0, 5])
def test_weighted_findmin_reports_weight_not_count(tmp_path, weight):
    source = relations(tmp_path, "connection relations\na=>t\ntarget\nt\nnot guessed\nt\nweights\na %d" % weight)
    result = solve(tmp_path, source, maxguess=weight, findmin=True)
    assert result["status"] == "sat" and result["optimal"] is True
    assert result["cost"] == weight
    assert result["guessed_variables"] == ["a"]
    assert result["outputfile"] is not None


def test_partial_weights_default_to_one(tmp_path):
    source = relations(tmp_path, "connection relations\na,b=>t\ntarget\nt\nnot guessed\nt\nweights\na 5")
    result = solve(tmp_path, source, maxguess=6, findmin=True)
    assert result["status"] == "sat" and result["optimal"] is True
    assert result["cost"] == 6
    assert set(result["guessed_variables"]) == {"a", "b"}


def test_milp_partial_weights_and_status(tmp_path):
    gurobi = pytest.importorskip("gurobipy")
    source = relations(tmp_path, "connection relations\na,b=>t\ntarget\nt\nnot guessed\nt\nweights\na 5")
    try:
        result = solve(tmp_path, source, solver="milp", maxguess=6)
        failed = solve(tmp_path, source, solver="milp", maxguess=5)
    except gurobi.GurobiError as error:
        if error.errno == 10009:
            pytest.skip("Gurobi license unavailable")
        raise
    assert result["status"] == "sat" and result["optimal"] is True
    assert result["cost"] == 6 and set(result["guessed_variables"]) == {"a", "b"}
    assert failed["status"] == "unsat" and failed["guessed_variables"] == []
    assert failed["outputfile"] is None


@pytest.fixture
def cp_model_class(tmp_path, monkeypatch):
    """Run the real CP constructor/emitter with only MiniZinc I/O replaced."""
    minizinc = ModuleType("minizinc")
    minizinc.default_driver = SimpleNamespace(available_solvers=lambda: {"cp-sat": []})
    minizinc.Solver = SimpleNamespace(lookup=lambda name: SimpleNamespace(stdFlags=[]))

    class Model:
        def add_file(self, path):
            self.source = Path(path).read_text()

    minizinc.Model = Model
    minizinc.Instance = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "minizinc", minizinc)
    spec = importlib.util.spec_from_file_location("mocked_gdcp", ROOT / "tools/autoguess/core/gdcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TEMP_DIR", str(tmp_path))
    return module.ReduceGDtoCP


@pytest.mark.parametrize("weights", ["", "\nweights\na 5"])
def test_cp_model_construction_keeps_explicit_budget_and_handles_weights(tmp_path, cp_model_class, weights):
    from core.varnames import step_var
    source = relations(tmp_path, "connection relations\na,b,c=>t\ntarget\nt\nnot guessed\nt" + weights)
    instance = cp_model_class(inputfile_name=str(source), outputfile_name=str(tmp_path / "cp-report"),
                              max_guess=2, max_steps=1, preprocess=0, cp_optimization=1)
    instance.make_model()
    assert instance.max_guess == 2
    assert instance.target_weights == ({"a": 5} if weights else None)
    model = instance.cp_model.source
    expected_terms = ["%d * %s" % (5 if v == "a" and weights else 1, step_var(v, 0))
                      for v in "abct"]
    expected_sum = " + ".join(expected_terms)
    assert "constraint " + expected_sum + " <= 2;" in model
    assert "solve minimize " + expected_sum + ";" in model
    assert "constraint %s = 0;" % step_var("t", 0) in model


def test_cp_weighted_default_uses_cost(tmp_path, cp_model_class):
    source = relations(tmp_path, "connection relations\na,b=>t\nknown\nb\ntarget\nt\nweights\na 5")
    instance = cp_model_class(inputfile_name=str(source), max_guess=None, max_steps=1, preprocess=0)
    assert instance.max_guess == 6  # a costs 5, t defaults to 1; known b costs 0.


def test_cp_zero_depth_declares_known_inputs_and_all_solution_variables(tmp_path, cp_model_class):
    from core.varnames import step_var
    source = relations(tmp_path, "connection relations\na,b\nknown\na\ntarget\nb\nnot guessed\na\nb")
    instance = cp_model_class(inputfile_name=str(source), max_guess=0, max_steps=0, preprocess=0)
    instance.make_model()
    model = instance.cp_model.source
    for v in "ab":
        assert "var bool: %s;" % step_var(v, 0) in model
    assert "constraint %s = 1;" % step_var("a", 0) in model
    assert "constraint %s = 0;" % step_var("a", 0) not in model
    assert "constraint %s = 1;" % step_var("b", 0) in model
    assert "constraint %s = 0;" % step_var("b", 0) in model


def test_cp_solver_error_removes_temporary_model_and_restores_library_path(tmp_path, cp_model_class, monkeypatch):
    source = relations(tmp_path, "connection relations\na,b")
    instance = cp_model_class(inputfile_name=str(source), max_guess=1, max_steps=1, preprocess=0)
    instance.make_model()
    path = Path(instance.cp_file_path)
    assert path.exists()
    monkeypatch.setenv("LD_LIBRARY_PATH", "existing-library-path")
    monkeypatch.setitem(instance.solve_via_cpsolver.__func__.__globals__, "MINIZINC_LIB_DIR", str(tmp_path / "libs"))

    def failing_solver(**options):
        assert os.environ["LD_LIBRARY_PATH"].startswith(str(tmp_path / "libs"))
        raise RuntimeError("simulated MiniZinc failure")

    instance.cp_inst.solve = failing_solver
    with pytest.raises(RuntimeError, match="simulated MiniZinc failure"):
        instance.solve_via_cpsolver()
    assert not path.exists()
    assert os.environ["LD_LIBRARY_PATH"] == "existing-library-path"


def test_timer_canceled_after_quick_solve(tmp_path):
    source = relations(tmp_path, "connection relations\na,b\nknown\na\ntarget\nb")
    before = set(threading.enumerate())
    result = solve(tmp_path, source, satsolver="glucose3", timelimit=10)
    assert result["status"] == "sat"
    assert not [thread for thread in threading.enumerate() if thread not in before and isinstance(thread, threading.Timer)]


def test_timeout_and_unsupported_limit_fail_honestly(tmp_path):
    source = relations(tmp_path, "connection relations\na,b\ntarget\nb")
    (tmp_path / "report").write_text("previous run")
    for findmin in (False, True):
        result = solve(tmp_path, source, satsolver="glucose3", timelimit=0, findmin=findmin)
        assert result["status"] == "unknown" and result["outputfile"] is None
        assert result["guessed_variables"] == [] and result["optimal"] is False
    with pytest.raises(ValueError, match="cannot enforce time limits"):
        solve(tmp_path, source, satsolver="cadical153", timelimit=1)


def test_findmin_timeout_preserves_feasible_basis_without_claiming_optimum(tmp_path, monkeypatch):
    from core import search
    original = search.solve_sat
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs) if len(calls) == 1 else None

    monkeypatch.setattr(search, "solve_sat", interrupted)
    source = relations(tmp_path, "connection relations\na=>t\ntarget\nt\nnot guessed\nt")
    result = solve(tmp_path, source, findmin=True)
    assert result["status"] == "sat" and result["guessed_variables"] == ["a"]
    assert result["optimal"] is False and result["cost"] == 1


def test_reducer_returns_empty_basis_when_file_knowns_suffice(tmp_path):
    source = relations(tmp_path, "connection relations\na,b\nknown\na\ntarget\nb")
    result = solve(tmp_path, source, solver="propagate", reducebasis=True, known=["b"])
    assert result["status"] == "sat"
    assert result["known_variables"] == ["a"]
    assert result["guessed_variables"] == result["reduced_basis"] == []
    assert result["optimal"] is False and result["optimal_subset"] is True


def test_reducer_keeps_basis_distinct_from_fixed_knowns(tmp_path):
    source = relations(tmp_path, "connection relations\na,b,c\nknown\na\ntarget\nc\nnot guessed\nc")
    result = solve(tmp_path, source, reducebasis=True, known=["b"])
    assert result["status"] == "sat" and result["known_variables"] == ["a"]
    assert result["guessed_variables"] == result["reduced_basis"] == ["b"]


def test_reducer_respects_finite_depth(tmp_path):
    source = relations(tmp_path, "connection relations\na=>b\nb=>c\nknown\na\ntarget\nc")
    result = solve(tmp_path, source, reducebasis=True, known=["b"], maxsteps=1)
    assert result["reduced_basis"] == ["b"]


def test_reducebasis_cli_routes_to_implemented_handler(tmp_path):
    source = relations(tmp_path, "connection relations\na,b\nknown\na\ntarget\nb")
    completed = subprocess.run([sys.executable, str(ROOT / "tools/autoguess/autoguess.py"),
                                "-i", str(source), "-o", str(tmp_path / "cli-report"),
                                "--reducebasis", "-kn", "b", "--nograph"],
                               cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert "STATUS: SAT" in completed.stdout
    assert "Guess cost: 0" in completed.stdout
    assert "Guessed variables: (none)" in completed.stdout


@pytest.mark.parametrize("backend", ["mark", "elim"])
def test_heuristic_modes_do_not_crash_and_validate_basis(tmp_path, backend):
    source = relations(tmp_path, "connection relations\na,b\ntarget\na\nb")
    result = solve(tmp_path, source, solver=backend)
    assert result["status"] == "sat"
    assert len(result["guessed_variables"]) == 1
    assert result["optimal"] is False


def test_sat_against_independent_exhaustive_small_systems(tmp_path):
    rng = random.Random(20261015)
    variables = list("abcd")
    for _ in range(12):
        symmetric = [rng.sample(variables, rng.randint(2, 4)) for _ in range(3)]
        directed = [rng.sample(variables, rng.randint(2, 4)) for _ in range(3)]
        known = set(rng.sample(variables, rng.randint(0, 2)))
        forbidden = set(rng.sample([v for v in variables if v not in known], 1))
        targets = set(rng.sample(variables, 2))
        lines = ["connection relations"] + [",".join(r) for r in symmetric]
        lines += [",".join(r[:-1]) + "=>" + r[-1] for r in directed]
        lines += [v + "=>" + v for v in variables]
        for role, names in (("known", known), ("target", targets), ("not guessed", forbidden)):
            if names:
                lines += [role] + sorted(names)
        source = relations(tmp_path, "\n".join(lines))
        for depth in (0, 1, 3):
            budget = 1
            feasible = False
            allowed = sorted(set(variables) - known - forbidden)
            for size in range(budget + 1):
                for guesses in itertools.combinations(allowed, size):
                    reached = known | set(guesses)
                    for _step in range(depth):
                        new = set()
                        for relation in symmetric:
                            missing = set(relation) - reached
                            if len(missing) == 1:
                                new |= missing
                        for relation in directed:
                            if set(relation[:-1]) <= reached:
                                new.add(relation[-1])
                        reached |= new
                    feasible |= targets <= reached
            result = solve(tmp_path, source, maxguess=budget, maxsteps=depth)
            assert (result["status"] == "sat") == feasible
