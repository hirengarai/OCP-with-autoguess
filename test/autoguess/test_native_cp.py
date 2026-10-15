"""Optional native MiniZinc checks against SAT and an independent small oracle.

Run with ``env312/bin/python -m pytest test/autoguess/test_native_cp.py``.
Missing MiniZinc dependencies skip these tests; installed solvers execute for real.
Set AUTOGUESS_NATIVE_CP_EVIDENCE to save the individual native comparisons as JSON.
"""

import itertools
import json
import os
from pathlib import Path
import random
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.autoguess_wrapper import run_autoguess


@pytest.fixture(scope="module")
def native_cp():
    minizinc = pytest.importorskip("minizinc")
    sys.path.insert(0, str(ROOT / "tools" / "autoguess"))
    try:
        from config import ensure_minizinc_driver
        ensure_minizinc_driver()
    finally:
        sys.path.pop(0)
    if minizinc.default_driver is None:
        pytest.skip("MiniZinc executable unavailable")
    return minizinc


@pytest.fixture(params=["cp-sat", "gecode", "chuffed"])
def cp_solver(request, native_cp):
    if request.param not in native_cp.default_driver.available_solvers():
        pytest.skip(f"Native MiniZinc solver {request.param} unavailable")
    return request.param


@pytest.fixture(scope="module")
def evidence(native_cp):
    records = []
    yield records
    destination = os.environ.get("AUTOGUESS_NATIVE_CP_EVIDENCE")
    if destination:
        payload = {
            "minizinc_python_version": native_cp.__version__,
            "minizinc_executable": str(native_cp.default_driver._executable),
            "solver_versions": {
                name: native_cp.Solver.lookup(name).version
                for name in sorted({record["solver"] for record in records})
            },
            "records": records,
        }
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2) + "\n")


def compare(tmp_path, name, text, cp_solver, evidence, *, expected_cost, depth=3,
            budget=8, optimize=True):
    source = tmp_path / f"{name}.txt"
    source.write_text(text + "\nend\n")
    options = dict(maxguess=budget, maxsteps=depth, drawgraph=False)
    sat = run_autoguess(source, outputfile=tmp_path / f"{name}-sat",
                        solver="sat", findmin=optimize, **options)
    started = time.monotonic()
    cp = run_autoguess(source, outputfile=tmp_path / f"{name}-{cp_solver}",
                       solver="cp", cpsolver=cp_solver, cpoptimization=int(optimize),
                       threads=1, timelimit=10, **options)
    record = dict(case=name, solver=cp_solver, maxsteps=depth, maxguess=budget,
                  optimization=optimize, expected_cost=expected_cost,
                  runtime_seconds=round(time.monotonic() - started, 4),
                  sat_status=sat["status"], sat_cost=sat["cost"],
                  cp_status=cp["status"], cp_cost=cp["cost"],
                  cp_guesses=cp["guessed_variables"], cp_optimal=cp["optimal"],
                  targets_covered=cp["targets_covered"])
    evidence.append(record)
    assert cp["status"] == sat["status"] == ("unsat" if expected_cost is None else "sat"), record
    if expected_cost is None:
        assert cp["guessed_variables"] == [] and cp["outputfile"] is None, record
        assert cp["optimal"] is False, record
    else:
        assert cp["targets_covered"] and cp["cost"] <= budget, record
        assert Path(cp["outputfile"]).is_file(), record
        if optimize:
            assert cp["cost"] == sat["cost"] == expected_cost, record
            # An empty objective uses solve satisfy, so no optimization proof is claimed.
            if text.strip() != "connection relations":
                assert cp["optimal"] is True, record
        else:
            assert cp["optimal"] is False, record


CASES = [
    ("symmetric", "connection relations\na,b,t\nknown\na\ntarget\nt\nnot guessed\nt", 1, 1, 1),
    ("partial_weights", "connection relations\na,b=>t\ntarget\nt\nnot guessed\nt\nweights\na 5", 6, 1, 6),
    ("weighted_too_small", "connection relations\na,b=>t\ntarget\nt\nnot guessed\nt\nweights\na 5", None, 1, 5),
    ("zero_weight", "connection relations\na=>t\ntarget\nt\nnot guessed\nt\nweights\na 0", 0, 1, 0),
    ("known_and_forbidden", "connection relations\na=>b\nknown\na\ntarget\nb\nnot guessed\na\nb", 0, 1, 0),
    ("depth_zero_guess", "connection relations\na,b\nknown\na\ntarget\nb", 1, 0, 1),
    ("depth_zero_forbidden", "connection relations\na,b\nknown\na\ntarget\nb\nnot guessed\na\nb", None, 0, 0),
    ("depth_too_short", "connection relations\na=>b\nb=>t\nknown\na\ntarget\nt\nnot guessed\nb\nt", None, 1, 0),
    ("depth_sufficient", "connection relations\na=>b\nb=>t\nknown\na\ntarget\nt\nnot guessed\nb\nt", 0, 2, 0),
    ("cheapest_route", "connection relations\na,b=>t\nc=>t\ntarget\nt\nnot guessed\nt\nweights\na 5\nb 2\nc 1", 1, 1, 8),
    ("constant_relation", "connection relations\na\na=>t\ntarget\nt\nnot guessed\na\nt", 0, 1, 0),
    ("empty", "connection relations", 0, 0, 0),
]


@pytest.mark.parametrize("name,text,cost,depth,budget", CASES, ids=[case[0] for case in CASES])
def test_native_cp_matches_sat(tmp_path, cp_solver, evidence, name, text, cost, depth, budget):
    compare(tmp_path, name, text, cp_solver, evidence, expected_cost=cost, depth=depth, budget=budget)


def test_native_cp_satisfaction_and_reused_report(tmp_path, cp_solver, evidence):
    text = "connection relations\na=>t\ntarget\nt\nnot guessed\nt"
    compare(tmp_path, "satisfy", text, cp_solver, evidence, expected_cost=1, budget=1, optimize=False)
    # The same report name survives an infeasible rerun, but must never be returned.
    compare(tmp_path, "satisfy", text, cp_solver, evidence, expected_cost=None, budget=0, optimize=False)


def test_native_cp_zero_and_negative_limits(tmp_path, cp_solver, evidence):
    source = tmp_path / "zero-limit.txt"
    source.write_text("connection relations\na=>t\ntarget\nt\nnot guessed\nt\nend\n")
    output = tmp_path / "zero-limit-report"
    output.write_text("previous successful report")
    options = dict(solver="cp", cpsolver=cp_solver, maxguess=1, maxsteps=1,
                   outputfile=output, drawgraph=False, threads=1)
    result = run_autoguess(source, timelimit=0, **options)
    evidence.append(dict(case="zero_time_limit", solver=cp_solver, cp_status=result["status"],
                         cp_guesses=result["guessed_variables"], cp_optimal=result["optimal"]))
    assert result["status"] == "unknown"
    assert result["guessed_variables"] == [] and result["outputfile"] is None
    assert result["optimal"] is False
    assert output.read_text() == "previous successful report"
    with pytest.raises(ValueError, match="Time limit must be nonnegative or -1"):
        run_autoguess(source, timelimit=-2, **options)


@pytest.mark.parametrize("case", range(6))
def test_native_cp_matches_exhaustive_weighted_oracle(tmp_path, cp_solver, evidence, case):
    rng = random.Random(2026101500 + case)
    variables = list("abcd")
    symmetric = [rng.sample(variables, rng.randint(2, 4)) for _ in range(3)]
    directed = [rng.sample(variables, rng.randint(2, 4)) for _ in range(3)]
    known = set(rng.sample(variables, rng.randint(0, 2)))
    forbidden = set(rng.sample(sorted(set(variables) - known), 1))
    targets = set(rng.sample(variables, 2))
    weights = {v: rng.randint(0, 4) for v in variables}
    budget = 4
    lines = ["connection relations"] + [",".join(r) for r in symmetric]
    lines += [",".join(r[:-1]) + "=>" + r[-1] for r in directed]
    lines += [v + "=>" + v for v in variables]
    for role, names in (("known", known), ("target", targets), ("not guessed", forbidden)):
        if names:
            lines += [role] + sorted(names)
    lines += ["weights"] + [f"{v} {weights[v]}" for v in variables]
    allowed = sorted(set(variables) - known - forbidden)
    for depth in (0, 1, 3):
        optimum = None
        for size in range(len(allowed) + 1):
            for guesses in itertools.combinations(allowed, size):
                cost = sum(weights[v] for v in guesses)
                if cost > budget:
                    continue
                reached = known | set(guesses)
                for _ in range(depth):
                    new = set()
                    for relation in symmetric:
                        missing = set(relation) - reached
                        if len(missing) == 1:
                            new |= missing
                    for relation in directed:
                        if set(relation[:-1]) <= reached:
                            new.add(relation[-1])
                    reached |= new
                if targets <= reached and (optimum is None or cost < optimum):
                    optimum = cost
        compare(tmp_path, f"oracle-{case}-depth-{depth}", "\n".join(lines),
                cp_solver, evidence, expected_cost=optimum, depth=depth, budget=budget)
