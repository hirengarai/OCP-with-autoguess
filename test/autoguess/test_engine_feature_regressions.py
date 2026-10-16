"""Tiny independent regressions for the vendored AutoGuess engine features.

Fixtures are temporary relation models; no standalone cipher corpus or research
benchmark infrastructure is required by OCP's production integration.
"""

from collections import Counter
import copy
import importlib
import itertools
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from threading import Event
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.autoguess_wrapper import _with_autoguess_path


@_with_autoguess_path
def engine_module(name):
    return importlib.import_module(name)


@_with_autoguess_path
def run(parameters):
    return importlib.import_module("autoguess").startsearch(parameters)


def parameters(tmp_path, text=None, **updates):
    source = tmp_path / "relations.txt"
    source.write_text(text or "connection relations\na=>t\ntarget\nt\nnot guessed\nt\nend\n")
    values = dict(inputfile=str(source), outputfile=str(tmp_path / "report"),
                  solver="sat", satsolver="glucose3", maxguess=1, maxsteps=1,
                  drawgraph=False, preprocess=0, log=0, time_limit=10, threads=1)
    values.update(updates)
    return values


@pytest.fixture
def captured_graphs(monkeypatch):
    captured = []

    def capture(graph, output_dir, tikz=0, dglayout="dot"):
        captured.append(graph)
        return {"gv": str(output_dir) + "_graph.gv", "warnings": []}

    monkeypatch.setattr(engine_module("core.graphdrawer"), "draw_deduction_graph", capture)
    return captured


def test_elimination_keeps_original_known_premises(tmp_path, captured_graphs):
    text = "connection relations\na,b,c\nknown\na\nb\ntarget\nc\nend\n"
    result = run(parameters(tmp_path, text, solver="elim", maxguess=0,
                            drawgraph=True, graph_view="deduction", time_limit=-1))
    assert result["status"] == "sat" and result["cost"] == 0
    deduction, = captured_graphs[0]["deductions"]
    assert deduction["head"] == "c" and set(deduction["premises"]) == {"a", "b"}
    assert deduction["relation"] == ["a", "b", "c"]


def test_elimination_cannot_validate_a_mutated_duplicate_relation(tmp_path, captured_graphs):
    text = "connection relations\na,a,b\nknown\nb\ntarget\na\nnot guessed\na\nend\n"
    result = run(parameters(tmp_path, text, solver="elim", maxguess=0,
                            drawgraph=True, graph_view="deduction", time_limit=-1))
    assert result["status"] == "unknown" and not result["targets_covered"]
    assert captured_graphs == [] and not result.get("graph_files")


@pytest.mark.parametrize("solver", ["sat", "maxsat", "smt", "cp", "milp"])
def test_native_backends_share_the_validated_conjunction_graph(tmp_path, captured_graphs, solver):
    if solver == "cp":
        require_gecode()
    elif solver == "smt":
        pytest.importorskip("pysmt")
        pytest.importorskip("z3")
    elif solver == "milp":
        pytest.importorskip("gurobipy")
    else:
        pytest.importorskip("pysat")
    text = ("connection relations\nk,a=>u\nu=>t\nknown\nk\ntarget\nt\n"
            "not guessed\nk\nu\nt\nweights\na 5\nend\n")
    try:
        result = run(parameters(tmp_path, text, solver=solver, maxguess=5, maxsteps=3,
                                cpsolver="gecode", cpoptimization=1,
                                drawgraph=True, graph_view="deduction"))
    except Exception as error:
        if solver == "milp" and getattr(error, "errno", None) == 10009:
            pytest.skip("Gurobi license unavailable")
        raise
    assert result["status"] == "sat" and result["guessed_variables"] == ["a"]
    graph, = captured_graphs
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert {name: node["step"] for name, node in nodes.items()} == {"k": 0, "a": 0, "u": 1, "t": 2}
    deductions = {deduction["head"]: deduction for deduction in graph["deductions"]}
    assert set(deductions["u"]["premises"]) == {"k", "a"}
    assert deductions["t"]["premises"] == ["u"]
    assert graph["metadata"]["cost"] == result["cost"] == 5
    assert result["graph_files"]["gv"].endswith("report_graph.gv")


@pytest.mark.parametrize("view", ["original", "deduction"])
@pytest.mark.parametrize("solver", ["sat", "maxsat"])
@pytest.mark.parametrize("initial", ["known", "guessed"])
def test_zero_step_target_remains_visible(tmp_path, captured_graphs, view, solver, initial):
    pytest.importorskip("pysat")
    text = "connection relations\nt=>t\ntarget\nt\n"
    if initial == "known":
        text += "known\nt\n"
    result = run(parameters(tmp_path, text + "end\n", solver=solver, maxsteps=0,
                            maxguess=0 if initial == "known" else 1,
                            drawgraph=True, graph_view=view))
    assert result["status"] == "sat" and result["targets_covered"]
    graph, = captured_graphs
    node, = graph["nodes"]
    assert (node["id"], node["kind"], node["step"], node["target"]) == ("t", initial, 0, True)
    assert graph["deductions"] == []


@pytest.mark.parametrize("updates", [{}, {"findmin": True}, {"solver": "maxsat"},
                                     {"seed_basis": ["a"], "time_limit": 0}])
def test_nograph_never_invokes_renderer(tmp_path, captured_graphs, updates):
    result = run(parameters(tmp_path, **updates))
    assert result["status"] == "sat" and not result.get("graph_files")
    assert captured_graphs == []


@pytest.mark.parametrize("suffix", [".gv", ".pdf", ".svg", ".tex"])
def test_graph_export_cannot_overwrite_input(tmp_path, suffix):
    p = parameters(tmp_path, drawgraph=True, tikz=1)
    collision = Path(p["outputfile"] + "_graph" + suffix)
    collision.write_text(Path(p["inputfile"]).read_text())
    p["inputfile"] = str(collision)
    original = collision.read_bytes()
    with pytest.raises(ValueError, match="Graph output paths"):
        run(p)
    assert collision.read_bytes() == original and not Path(p["outputfile"]).exists()


def test_graph_export_symlink_cannot_overwrite_seed_or_json(tmp_path):
    p = parameters(tmp_path, drawgraph=True)
    seed = tmp_path / "seed.json"
    seed.write_text('["a"]')
    Path(p["outputfile"] + "_graph.gv").symlink_to(seed)
    with pytest.raises(ValueError, match="Graph output paths"):
        run(dict(p, seed_basis_file=str(seed)))
    assert seed.read_text() == '["a"]'
    main = engine_module("autoguess").main
    with pytest.raises(SystemExit) as error:
        main(["-i", p["inputfile"], "-o", p["outputfile"],
              "--json-output", p["outputfile"] + "_graph.svg"])
    assert error.value.code == 2 and not Path(p["outputfile"]).exists()


@pytest.mark.parametrize("updates,match", [({"dglayout": "nop"}, "graph layout"),
    ({"graph_scope": "bad"}, "graph_scope"), ({"graph_view": "bad"}, "graph_view"),
    ({"graph_view": "cipher"}, "graph_view"), ({"tikz": "1"}, "tikz")])
def test_invalid_graph_options_fail_before_native(tmp_path, monkeypatch, updates, match):
    def unexpected(_parameters):
        pytest.fail("Invalid graph options reached the native solver")

    monkeypatch.setattr(engine_module("core.search"), "_sat_solver", unexpected)
    with pytest.raises(ValueError, match=match):
        run(parameters(tmp_path, drawgraph=True, **updates))
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("stop", ["unsat", "time_limit"])
def test_smt_descent_reports_and_draws_only_final_native_incumbent(tmp_path, monkeypatch, captured_graphs, stop):
    pytest.importorskip("pysmt")
    pytest.importorskip("z3")
    search = engine_module("core.search")
    optimization = engine_module("core.optimization")
    parser = engine_module("core.parsesolution")
    solve_native, write_report = search._solve_smt, parser.atomic_write
    attempts, writes, models = [], [], []

    def record_report(path, text):
        writes.append(text)
        return write_report(path, text)

    def query(p):
        if attempts and stop == "time_limit":
            attempts.append((p["_defer_reporting"], None))
            return optimization._empty(models[0], reason="time_limit"), None
        result, native = solve_native(p)
        if not attempts:
            models.append(native.__dict__)
        attempts.append((p["_defer_reporting"], result["outputfile"]))
        return result, native

    monkeypatch.setattr(search, "_solve_smt", query)
    monkeypatch.setattr(parser, "atomic_write", record_report)
    result = run(parameters(tmp_path, solver="smt", findmin=True, drawgraph=True))
    assert result["status"] == "sat" and result["cost"] == 1
    assert result["optimal"] is (stop == "unsat")
    assert result["termination_reason"] == ("optimal" if stop == "unsat" else "time_limit")
    assert len(attempts) == 2 and all(deferred and report is None for deferred, report in attempts)
    assert len(writes) == len(captured_graphs) == 1
    assert result["graph_summary"]["state_source"] == "native"
    assert "Search status: sat" in Path(result["outputfile"]).read_text()


def test_smt_model_error_is_not_masked_by_resource_cleanup(tmp_path, monkeypatch):
    pytest.importorskip("pysmt")

    class BrokenModel:
        def __init__(self, **options):
            pass

        def make_model(self):
            raise ValueError("native model generation failed")

    monkeypatch.setattr(engine_module("core.gdsmt"), "ReduceGDtoSMT", BrokenModel)
    with pytest.raises(ValueError, match="native model generation failed"):
        run(parameters(tmp_path, solver="smt"))


def require_gecode():
    native = pytest.importorskip("minizinc")
    engine_module("config").ensure_minizinc_driver()
    if native.default_driver is None or "gecode" not in native.default_driver.available_solvers():
        pytest.skip("Native MiniZinc solver gecode unavailable")


@pytest.mark.parametrize("verbose", [False, True])
def test_cp_internal_unsat_proof_keeps_one_authoritative_cli_result(tmp_path, verbose):
    require_gecode()
    p = parameters(tmp_path, "connection relations\na,b=>u\nu=>t\na=>spare\nknown\na\n"
                   "target\nt\nnot guessed\nu\nt\nspare\nweights\nb 3\nend\n")
    sidecar = tmp_path / "result.json"
    command = [sys.executable, str(ROOT / "tools/autoguess/autoguess.py"), "-i", p["inputfile"],
               "-o", p["outputfile"], "-s", "cp", "-cps", "gecode", "-cpopt", "1",
               "-mg", "3", "-ms", "2", "-tl", "10", "--seed-basis", "b",
               "--nograph", "--json-output", str(sidecar)]
    if verbose:
        command.append("--verbose")
    completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=25)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(sidecar.read_text())
    assert result["status"] == "sat" and result["cost"] == result["seed_cost"] == 3
    assert result["guessed_variables"] == ["b"] and result["known_variables"] == ["a"]
    assert result["targets_covered"] and result["optimal"]
    assert result["lower_bound"] == result["upper_bound"] == 3
    assert result["proof_method"] == "strict_cost_bound_unsat"
    assert completed.stdout.count("STATUS: SAT") == completed.stdout.count("Guess cost: 3") == 1
    assert "STATUS: UNSAT" not in completed.stdout and "The model is UNSAT" not in completed.stdout
    assert "RESULT: UNSATISFIABLE" not in completed.stdout and "Increase max_guess" not in completed.stdout
    assert ("Cost-bound subsearch" in completed.stdout) is verbose
    assert Path(p["outputfile"]).read_text().count("Search status: sat") == 1


def test_quiet_cli_does_not_silence_later_direct_backend_api(tmp_path, capsys):
    p = parameters(tmp_path)
    main = engine_module("autoguess").main
    assert main(["-i", p["inputfile"], "-o", p["outputfile"], "-mg", "1", "-ms", "1", "--nograph"])["status"] == "sat"
    capsys.readouterr()
    native = engine_module("core.gdsat").ReduceGDtoSAT(
        inputfile_name=p["inputfile"], outputfile_name=str(tmp_path / "direct"),
        max_guess=1, max_steps=1, sat_solver="glucose3", preprocess=0, drawgraph=False)
    native.make_model()
    assert native.solve_via_satsolver() is True
    output = capsys.readouterr().out
    assert "SAT SOLVER" in output and "SOLVING" in output and "Number of guesses:" in output


def test_vendored_cli_requires_an_explicit_relation_input(tmp_path):
    completed = subprocess.run([sys.executable, str(ROOT / "tools/autoguess/autoguess.py")],
                               cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 2
    assert "required" in completed.stderr and "--inputfile" in completed.stderr
    assert "FileNotFoundError" not in completed.stderr
    assert list(tmp_path.iterdir()) == []


def test_vendored_cli_rejects_retired_cipher_view_before_writing(tmp_path):
    p = parameters(tmp_path)
    sidecar = tmp_path / "result.json"
    completed = subprocess.run([sys.executable, str(ROOT / "tools/autoguess/autoguess.py"),
        "-i", p["inputfile"], "-o", p["outputfile"], "--graph-view", "cipher",
        "--json-output", str(sidecar)], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr and "cipher" in completed.stderr
    assert not sidecar.exists() and not Path(p["outputfile"]).exists()
    assert list(tmp_path.glob("*_graph.*")) == []


def independent_closure(data, guesses, depth):
    reached = set(data["known_variables"]) | set(guesses)
    for _ in range(depth):
        additional = set()
        for relation in data["symmetric_relations"]:
            missing = [v for v in relation if v not in reached]
            if len(missing) == 1:
                additional.add(missing[0])
        for relation in data["implication_relations"]:
            if set(relation[:-1]) <= reached:
                additional.add(relation[-1])
        reached |= additional
    return reached


def exhaustive_minimum(data, depth):
    allowed = sorted(set(data["variables"]) - set(data["known_variables"]) - set(data["notguessed_variables"]))
    weights = data["target_weights"] or {}
    costs = [sum(weights.get(v, 1) for v in guesses)
             for size in range(len(allowed) + 1) for guesses in itertools.combinations(allowed, size)
             if set(data["target_variables"]) <= independent_closure(data, guesses, depth)]
    return min(costs) if costs else None


def test_maxsat_and_replayable_lower_bounds_against_exhaustive_tiny_models(tmp_path):
    pytest.importorskip("pysat")
    lowerbounds = engine_module("core.lowerbounds")
    rng = random.Random(20261016)
    variables = list("abcd")
    for case in range(20):
        symmetric = [rng.choices(variables, k=rng.randrange(2, 5)) for _ in range(3)]
        implications = [rng.choices(variables, k=rng.randrange(2, 4)) for _ in range(3)]
        known = rng.sample(variables, rng.randrange(2))
        forbidden = rng.sample(variables, rng.randrange(3))
        targets = rng.sample(variables, rng.randrange(1, 5))
        weights = {v: rng.randrange(4) for v in variables}
        data = dict(variables=variables, symmetric_relations=symmetric, implication_relations=implications,
                    known_variables=known, target_variables=targets, notguessed_variables=forbidden,
                    target_weights=weights)
        lines = ["connection relations", *[v + "=>" + v for v in variables]]
        lines += [",".join(relation) for relation in symmetric]
        lines += [",".join(relation[:-1]) + "=>" + relation[-1] for relation in implications]
        for name, values in [("known", known), ("target", targets), ("not guessed", forbidden)]:
            if values:
                lines += [name, *values]
        lines += ["weights", *[v + " " + str(w) for v, w in weights.items()], "end"]
        depth = case % 4
        expected = exhaustive_minimum(data, depth)
        p = parameters(tmp_path, "\n".join(lines) + "\n", solver="maxsat", maxguess=12, maxsteps=depth)
        result = run(p)
        assert result["status"] == ("sat" if expected is not None else "unsat"), (case, data, result)
        if expected is not None:
            assert result["optimal"] and result["cost"] == result["lower_bound"] == result["upper_bound"] == expected
            assert set(targets) <= independent_closure(data, result["guessed_variables"], depth)
            if expected:
                assert run(dict(p, maxguess=expected - 1))["status"] == "unsat"
        certificate = lowerbounds.generate_lower_bound(data)
        bound = lowerbounds.verify_lower_bound(data, json.loads(json.dumps(certificate)))
        full_minimum = exhaustive_minimum(data, len(variables))
        assert full_minimum is None or bound <= full_minimum


@pytest.mark.parametrize("key,value", [("model_sha256", "wrong"), ("lower_bound", 999),
                                       ("field", "GF(3)"), ("dual_masks_hex", ["0x0"])])
def test_lower_bound_certificate_tampering_is_rejected(key, value):
    bounds = engine_module("core.lowerbounds")
    data = dict(variables=list("abc"), symmetric_relations=[list("abc")], implication_relations=[],
                known_variables=[], target_variables=list("abc"), notguessed_variables=[], target_weights={})
    certificate = bounds.generate_lower_bound(data)
    certificate[key] = value
    with pytest.raises(ValueError):
        bounds.verify_lower_bound(data, certificate)


def test_refinement_exchanges_inclusion_minimal_seed_without_claiming_global_optimum():
    refine = engine_module("core.basisrefine").refine_basis
    data = dict(variables=list("abcuv"), symmetric_relations=[],
                implication_relations=[["a", "u"], ["b", "v"], ["c", "u"], ["c", "v"]],
                known_variables=[], target_variables=["u", "v"], notguessed_variables=["u", "v"],
                target_weights={})
    original = copy.deepcopy(data)
    result = refine(data, ["a", "b"], max_steps=1, max_trials=100)
    assert result["seed_cost"] == 2 and result["cost"] == 1 and result["guessed_variables"] == ["c"]
    assert not result["optimal"] and data == original
    assert set(data["target_variables"]) <= independent_closure(data, result["guessed_variables"], 1)
    retained = refine(data, ["a", "b"], max_steps=1, time_limit=0)
    assert retained["cost"] == 2 and retained["guessed_variables"] == ["a", "b"]
    assert retained["known_variables"] == [] and retained["timed_out"] and not retained["optimal"]


@pytest.mark.parametrize("seed,expected", [(None, "unknown"), (["a"], "sat")])
def test_maxsat_zero_budget_retains_only_a_valid_paid_seed(tmp_path, seed, expected):
    result = run(parameters(tmp_path, solver="maxsat", time_limit=0, seed_basis=seed))
    assert result["status"] == expected and result["timed_out"] and not result["optimal"]
    assert result["known_variables"] == [] and result["lower_bound"] == 0
    assert result["cost"] == (1 if seed else None)
    assert result["guessed_variables"] == (seed or [])


@pytest.mark.parametrize("bound,seed,expired", [(1, ["a", "b"], True),
    (2, ["a", "b"], True), (1, None, True), (1, ["a", "b"], False)])
def test_interrupted_maxsat_keeps_only_certified_bound_and_valid_seed(tmp_path, monkeypatch, bound, seed, expired):
    backend = engine_module("core.gdmaxsat")
    deleted = []

    class InterruptedOptimizer:
        cost = 999  # Partial core processing is not a certified bound.
        certified_cost = bound
        interrupted = True

        def compute(self, expect_interrupt=False):
            raise backend._MaxSATInterrupted()

        def delete(self):
            deleted.append(True)

        def interrupt(self):
            pass

    def create(formula, event):
        if expired:
            event.set()
        return InterruptedOptimizer()

    monkeypatch.setattr(backend, "_new_optimizer", create)
    text = "connection relations\na=>u\nb=>v\n"
    if bound == 1:
        text += "c=>u\nc=>v\n"
    text += "target\nu\nv\nnot guessed\nu\nv\nend\n"
    result = backend.search_using_maxsat(parameters(tmp_path, text, maxguess=2, seed_basis=seed))
    assert deleted == [True] and result["lower_bound"] == bound
    assert result["optimal"] is (seed is not None and bound == 2)
    if seed:
        assert result["status"] == "sat" and result["cost"] == result["seed_cost"] == 2
        assert result["known_variables"] == [] and result["guessed_variables"] == seed
    else:
        assert result["status"] == "unknown" and result["cost"] is None
    if result["optimal"]:
        assert result["termination_reason"] == "optimal" and result["solver_stop_reason"] == "time_limit"
        assert result["proof_method"] == "rc2_lower_bound_meets_validated_incumbent"
    else:
        assert result["termination_reason"] == ("time_limit" if expired else "interrupted")


def test_maxsat_native_unknown_cannot_process_a_stale_unsat_core(monkeypatch):
    from pysat.formula import WCNF

    backend = engine_module("core.gdmaxsat")
    formula = WCNF()
    formula.append([1])
    formula.append([-1], weight=1)
    optimizer = backend._new_optimizer(formula, Event())
    try:
        monkeypatch.setattr(optimizer.oracle, "solve_limited", lambda **kwargs: None)
        with pytest.raises(backend._MaxSATInterrupted):
            optimizer.compute(expect_interrupt=True)
        assert optimizer.certified_cost == 0
    finally:
        optimizer.delete()


@pytest.mark.skipif(not shutil.which("dot"), reason="system Graphviz unavailable")
def test_original_svg_and_tikz_preserve_edges_roles_and_single_borders(tmp_path):
    pytest.importorskip("dot2tex")
    drawer = engine_module("core.graphdrawer")
    nodes = [dict(id="a", label="a", kind="known", step=0, target=False),
             dict(id="b", label="b", kind="guessed", step=0, target=False),
             dict(id="t", label="t", kind="derived", step=1, target=True),
             dict(id="u", label="u", kind="guessed", step=0, target=True)]
    edges = [["a", "t", 1], ["a", "t", 1], ["a", "t", 2], ["b", "t", 1], ["t", "u", 3]]
    graph = dict(nodes=nodes, deductions=[], original_edges=edges,
                 metadata=dict(view="original", cost=2, guessed_count=2, target_count=2,
                               propagation_steps=1, max_steps=1, scope="original"))
    paths = drawer.draw_deduction_graph(graph, str(tmp_path / "graph"), tikz=1)
    assert paths["warnings"] == []
    assert Path(paths["pdf"]).read_bytes().startswith(b"%PDF-")
    ns = {"svg": "http://www.w3.org/2000/svg"}
    svg = ET.fromstring(Path(paths["svg"]).read_text())
    names = {"v" + str(i): node["id"] for i, node in enumerate(nodes)}
    expected = Counter((a, b, count >= 2) for a, b, count in set(map(tuple, edges)))
    rendered = Counter()
    for group in svg.findall(".//svg:g[@class='edge']", ns):
        tail, head = group.find("svg:title", ns).text.split("->")
        dashed = "stroke-dasharray" in group.find(".//svg:path", ns).attrib
        rendered[(names[tail], names[head], dashed)] += 1
    assert rendered == expected
    groups = {group.find("svg:title", ns).text: group for group in svg.findall(".//svg:g[@class='node']", ns)}
    for identity, node in zip(names, nodes):
        shapes = groups[identity].findall(".//svg:ellipse", ns) + groups[identity].findall(".//svg:polygon", ns)
        assert len(shapes) == 1
        if node["target"] or node["kind"] == "guessed":
            expected_color = drawer.PALETTE["target_fill" if node["target"] else "guessed_fill"]
            assert shapes[0].attrib["fill"].lower() == expected_color.lower()
    tex = Path(paths["tex"]).read_text()
    tex_edges = Counter((names[a], names[b], "dashed" in style)
                        for style, a, b in re.findall(r"\\draw \[([^\]]*)\] \((v\d+)\).*?\((v\d+)\);", tex))
    assert tex_edges == expected
    assert "Original AutoGuess graph" in tex and "double" not in tex.lower()
    assert "jointly required" in Path(paths["gv"]).read_text()


@pytest.mark.skipif(not shutil.which("dot"), reason="system Graphviz unavailable")
def test_deduction_svg_and_tikz_preserve_and_premises_and_unary_edges(tmp_path):
    pytest.importorskip("dot2tex")
    data = dict(variables=["a", "k", "u", "t"], symmetric_relations=[],
                implication_relations=[["k", "a", "u"], ["u", "t"]],
                known_variables=["k"], target_variables=["t"],
                notguessed_variables=["k", "u", "t"], target_weights={"a": 5})
    graph = engine_module("core.deductiongraph").build_deduction_graph(data, ["a"], max_steps=2)
    drawer = engine_module("core.graphdrawer")
    paths = drawer.draw_deduction_graph(graph, str(tmp_path / "deduction"), tikz=1)
    assert paths["warnings"] == []
    assert Path(paths["pdf"]).read_bytes().startswith(b"%PDF-")
    expected = Counter({("v0", "r0"): 1, ("v1", "r0"): 1,
                        ("r0", "v2"): 1, ("v2", "v3"): 1})
    ns = {"svg": "http://www.w3.org/2000/svg"}
    svg_text = Path(paths["svg"]).read_text()
    svg = ET.fromstring(svg_text)
    svg_edges = Counter(tuple(group.find("svg:title", ns).text.split("->"))
                        for group in svg.findall(".//svg:g[@class='edge']", ns))
    assert svg_edges == expected
    groups = {group.find("svg:title", ns).text: group for group in svg.findall(".//svg:g[@class='node']", ns)}
    assert "r0" in groups and "r1" not in groups
    assert any(text.text == "AND" for text in groups["r0"].findall(".//svg:text", ns))
    for identity, role in [("v0", "guessed"), ("v1", "known"), ("v3", "target")]:
        shapes = groups[identity].findall(".//svg:ellipse", ns) + groups[identity].findall(".//svg:polygon", ns)
        assert len(shapes) == 1
        assert shapes[0].attrib["fill"].lower() == drawer.PALETTE[role + "_fill"].lower()
    assert "Paid guess cost: 5" in svg_text and "AND: every incoming premise is required" in svg_text
    tex = Path(paths["tex"]).read_text()
    tex_edges = Counter(re.findall(r"\\draw \[[^\]]*\] \((v\d+|r\d+)\).*?\((v\d+|r\d+)\);", tex))
    assert tex_edges == expected
    assert tex.count("AutoGuess deduction graph") == tex.count("Legend: known") == 1
    assert "double" not in tex.lower()
