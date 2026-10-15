"""Real PySMT/Z3 runs checked against independent finite-depth enumeration.

Set AUTOGUESS_NATIVE_ARTIFACT_DIR to retain inputs, solver logs, and JSON evidence.
No solver API is mocked; the module skips only when native dependencies are absent.
"""

from contextlib import redirect_stdout
from io import StringIO
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

pytest.importorskip("pysmt")
z3 = pytest.importorskip("z3")

from tools.autoguess_wrapper import _with_autoguess_path, run_autoguess


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    requested = os.environ.get("AUTOGUESS_NATIVE_ARTIFACT_DIR")
    directory = Path(requested) / "smt" if requested else tmp_path_factory.mktemp("native-smt")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    yield directory, rows
    import pysmt

    (directory / "results.json").write_text(json.dumps({
        "python": sys.version,
        "pysmt": pysmt.__version__,
        "z3": z3.get_version_string(),
        "native_execution": True,
        "oracle": "Independent synchronous closure over every permitted guess subset",
        "seed": 20261015,
        "comparisons": rows,
    }, indent=2) + "\n")


def closure(known, guesses, symmetric, directed, depth):
    """Independent synchronous propagation, without importing solver helpers."""
    reached = set(known) | set(guesses)
    for _ in range(depth):
        additional = set()
        for relation in symmetric:
            missing = set(relation) - reached
            if len(missing) == 1:
                additional.update(missing)
        for relation in directed:
            if set(relation[:-1]) <= reached:
                additional.add(relation[-1])
        reached.update(additional)
    return reached


def minimum_cost(variables, known, forbidden, targets, symmetric, directed, depth, weights):
    allowed = sorted(set(variables) - set(known) - set(forbidden))
    feasible = []
    for size in range(len(allowed) + 1):
        for guesses in itertools.combinations(allowed, size):
            if set(targets) <= closure(known, guesses, symmetric, directed, depth):
                feasible.append(sum(weights.get(v, 1) for v in guesses))
    return min(feasible) if feasible else None


def relation_text(variables, known=(), forbidden=(), targets=(), symmetric=(), directed=(), weights=None):
    lines = ["connection relations"]
    lines.extend(",".join(relation) for relation in symmetric)
    lines.extend(",".join(relation[:-1]) + "=>" + relation[-1] for relation in directed)
    # Include isolated variables without introducing any new deductions.
    lines.extend(v + "=>" + v for v in variables)
    for header, names in (("known", known), ("target", targets), ("not guessed", forbidden)):
        if names:
            lines.extend([header, *sorted(names)])
    if weights:
        lines.extend(["weights", *(v + " " + str(w) for v, w in sorted(weights.items()))])
    return "\n".join([*lines, "end", ""])


@_with_autoguess_path
def legacy_z3(source, report, budget, depth):
    from core.gdz3smt import ReduceGDtoZ3SMT
    from core.solverresult import current_result

    instance = ReduceGDtoZ3SMT(inputfile_name=str(source), outputfile_name=str(report),
                             max_guess=budget, max_steps=depth, preprocess=0,
                             drawgraph=False)
    instance.make_model()
    return current_result(instance, instance.solve_via_smtsolver())


def execute(evidence, case, text, budget, depth, backend, **options):
    directory, rows = evidence
    label = case + "_" + backend + ("_findmin" if options.get("findmin") else "")
    source = directory / (case + ".txt")
    source.write_text(text)
    report = directory / (label + "_report.txt")
    started = time.monotonic()
    log = StringIO()
    with redirect_stdout(log):
        if backend == "direct-z3":
            result = legacy_z3(source, report, budget, depth)
        else:
            result = run_autoguess(str(source), outputfile=str(report),
                                   solver="smt" if backend == "pysmt-z3" else "sat",
                                   smtsolver="z3", satsolver="cadical153",
                                   maxguess=budget, maxsteps=depth, drawgraph=False,
                                   **options)
    (directory / (label + ".log")).write_text(log.getvalue())
    rows.append({"case": case, "backend": backend, "budget": budget, "depth": depth,
                 "findmin": options.get("findmin", False),
                 "runtime_seconds": round(time.monotonic() - started, 4),
                 "result": result})
    return result


def validate_result(result, expected_cost, budget, known, forbidden, targets,
                    symmetric, directed, depth, weights):
    feasible = expected_cost is not None and expected_cost <= budget
    assert result["status"] == ("sat" if feasible else "unsat")
    if not feasible:
        assert result["outputfile"] is None
        assert result["guessed_variables"] == []
        return
    guesses = result["guessed_variables"]
    assert not set(guesses) & (set(forbidden) - set(known))
    assert not set(guesses) & set(known)
    assert result["cost"] == sum(weights.get(v, 1) for v in guesses) <= budget
    assert set(targets) <= closure(known, guesses, symmetric, directed, depth)
    assert result["targets_covered"]


@pytest.mark.parametrize("backend", ["pysmt-z3", "direct-z3"])
def test_native_smt_matches_exhaustive_finite_depth(evidence, backend):
    rng = random.Random(20261015)
    variables = list("abcd")
    for system in range(12):
        symmetric = [rng.sample(variables, rng.randint(2, 4)) for _ in range(3)]
        directed = [rng.sample(variables, rng.randint(2, 4)) for _ in range(3)]
        known = rng.sample(variables, rng.randint(0, 2))
        forbidden = rng.sample(variables, 1)
        targets = rng.sample(variables, 2)
        weights = {v: rng.randrange(0, 7) for v in rng.sample(variables, 2)}
        text = relation_text(variables, known, forbidden, targets, symmetric, directed, weights)
        for depth in (0, 1, 3):
            expected = minimum_cost(variables, known, forbidden, targets,
                                    symmetric, directed, depth, weights)
            for budget in (0, 2, 20):
                case = "random%02d_depth%d_budget%d" % (system, depth, budget)
                result = execute(evidence, case, text, budget, depth, backend)
                evidence[1][-1]["expected_minimum_cost"] = expected
                validate_result(result, expected, budget, known, forbidden, targets,
                                symmetric, directed, depth, weights)
                if backend == "pysmt-z3":
                    sat = execute(evidence, case, text, budget, depth, "sat")
                    assert sat["status"] == result["status"]


@pytest.mark.parametrize("backend", ["pysmt-z3", "direct-z3"])
@pytest.mark.parametrize("name,known,forbidden,targets,symmetric,directed,weights,depth,budget", [
    ("known-forbidden", ["a"], ["a", "b"], ["b"], [["a", "b"]], [], {}, 1, 0),
    ("zero-depth-known", ["a"], ["a", "b"], ["a"], [["a", "b"]], [], {}, 0, 0),
    ("zero-depth-unsat", ["a"], ["a", "b"], ["b"], [["a", "b"]], [], {}, 0, 20),
    ("partial-weight", [], ["t"], ["t"], [], [["a", "b", "t"]], {"a": 5}, 1, 6),
    ("weight-overflow", [], ["t"], ["t"], [], [["a", "b", "t"]], {"a": 5}, 1, 1000),
    ("free-guess", [], ["t"], ["t"], [], [["a", "t"]], {"a": 0}, 1, 0),
    ("isolated-known", ["a"], ["a", "b"], ["a"], [], [], {}, 3, 0),
])
def test_native_smt_boundaries(evidence, backend, name, known, forbidden, targets,
                               symmetric, directed, weights, depth, budget):
    variables = sorted(set("abt") | set(known) | set(forbidden) | set(targets))
    text = relation_text(variables, known, forbidden, targets, symmetric, directed, weights)
    expected = minimum_cost(variables, known, forbidden, targets,
                            symmetric, directed, depth, weights)
    result = execute(evidence, name, text, budget, depth, backend)
    evidence[1][-1]["expected_minimum_cost"] = expected
    validate_result(result, expected, budget, known, forbidden, targets,
                    symmetric, directed, depth, weights)


@pytest.mark.parametrize("name,known,forbidden,directed,weights", [
    ("minimum-count", [], ["t"], [["a", "t"], ["b", "c", "t"]], {}),
    ("minimum-weight", [], ["t"], [["a", "t"], ["b", "c", "t"]], {"a": 5}),
    ("minimum-zero-known", ["a"], ["a", "t"], [["a", "t"]], {}),
    ("minimum-zero-weight", [], ["t"], [["a", "t"]], {"a": 0}),
])
def test_native_pysmt_findmin(evidence, name, known, forbidden, directed, weights):
    variables = list("abct")
    text = relation_text(variables, known, forbidden, ["t"], [], directed, weights)
    expected = minimum_cost(variables, known, forbidden, ["t"], [], directed, 3, weights)
    result = execute(evidence, name, text, 20, 3, "pysmt-z3", findmin=True)
    evidence[1][-1]["expected_minimum_cost"] = expected
    sat = execute(evidence, name, text, 20, 3, "sat", findmin=True)
    assert result["status"] == sat["status"] == "sat"
    assert result["cost"] == sat["cost"] == expected
    assert result["optimal"] is sat["optimal"] is True
    assert Path(result["outputfile"]).is_file()


@pytest.mark.parametrize("backend", ["pysmt-z3", "direct-z3"])
@pytest.mark.parametrize("empty", [False, True])
def test_native_smt_no_unknown_variables(evidence, backend, empty):
    text = "connection relations\nend\n" if empty else relation_text(
        ["a"], known=["a"], forbidden=["a"], targets=["a"], directed=[["a", "a"]])
    result = execute(evidence, "empty" if empty else "all-known", text, 0, 0, backend)
    assert result["status"] == "sat"
    assert result["guessed_variables"] == [] and result["cost"] == 0
    assert result["targets_covered"]


@pytest.mark.parametrize("findmin", [False, True])
def test_native_pysmt_z3_enforces_finite_time_limit(evidence, findmin):
    directory, _ = evidence
    source = directory / "time-limit.txt"
    source.write_text(relation_text(["a", "b"], targets=["b"], symmetric=[["a", "b"]]))
    result = run_autoguess(str(source), outputfile=str(directory / "time-limit-report"),
                           solver="smt", smtsolver="z3", maxguess=1, maxsteps=1,
                           drawgraph=False, timelimit=10, findmin=findmin)
    assert result["status"] == "sat" and result["targets_covered"]
    assert result["optimal"] is findmin
    assert result["time_limit_seconds"] == 10
    assert result["timed_out"] is False
    assert result["termination_reason"] == ("optimal" if findmin else "solution_found")
    timed_out = run_autoguess(str(source), outputfile=str(directory / "time-limit-report"),
                              solver="smt", smtsolver="z3", maxguess=1, maxsteps=1,
                              drawgraph=False, timelimit=0, findmin=findmin)
    assert timed_out["status"] == "unknown" and timed_out["outputfile"] is None
    assert timed_out["timed_out"] is True and timed_out["termination_reason"] == "time_limit"


def test_native_pysmt_ocp_aes_quickstart(evidence):
    from attacks import attacks
    import primitives.aes as aes

    directory, rows = evidence
    cipher = aes.AES_BLOCKCIPHER(2, [128, 128])
    function = cipher.functions["PERMUTATION"]
    known = [v.ID for v in function.vars[1][0]] + [v.ID for v in function.vars[function.nbr_rounds][1]]
    source = directory / "relations_aes_guide.txt"
    started = time.monotonic()
    log = StringIO()
    with redirect_stdout(log):
        result = attacks.guess_and_determine_attack(
            cipher, known_vars=known, objective_target="AT MOST 6", show_mode=0,
            config_model={"model_type": "smt", "filename": str(source),
                          "skip_rounds": [2], "maxsteps": 14},
            config_solver={"solver": "z3"},
        )
    (directory / "aes_guide_pysmt-z3.log").write_text(log.getvalue())
    serializable = {key: result[key] for key in (
        "status", "guessed_variable_ids", "known_variable_ids", "target_variable_ids",
        "targets_covered", "unresolved_variable_ids", "cost", "optimal", "relation_file",
        "model_hash", "model_config", "solver_config",
    )}
    rows.append({"case": "ocp-aes-guide", "backend": "pysmt-z3", "budget": 6,
                 "depth": 14, "runtime_seconds": round(time.monotonic() - started, 4),
                 "result": serializable,
                 "scope": "Guide's reduced relation system: round 2 deliberately skipped and bridged."})
    assert result["status"] == "sat"
    assert result["targets_covered"]
    assert len(result["target_variable_ids"]) == 96
    assert len(result["guessed_variable_ids"]) <= 6
    assert len(result["guessed_variable_ids"]) == len(result["guessed_variables"])
    assert result["unresolved_variable_ids"] == []
    # Check the native direct Z3 implementation on the same generated OCP model.
    legacy = execute(evidence, "aes-guide", source.read_text(), 6, 14, "direct-z3")
    assert legacy["status"] == "sat" and legacy["targets_covered"]
    assert legacy["cost"] <= 6
