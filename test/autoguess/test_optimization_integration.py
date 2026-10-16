"""Optimization features must preserve OCP roles, costs, budgets and objects."""

import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from attacks import guess_and_determine as gd
from operators.boolean_operators import XOR
from primitives.primitives import Layered_Function
from tools.autoguess_wrapper import _with_autoguess_path, run_autoguess
from variables.variables import Variable


@_with_autoguess_path
def engine_module(name):
    return importlib.import_module(name)


def relation_file(tmp_path, text=None):
    source = tmp_path / "relations.txt"
    source.write_text(text or "connection relations\na,b,c\nknown\na\ntarget\nc\nnot guessed\nc\nend\n")
    return source


def solve(tmp_path, **options):
    source = relation_file(tmp_path, options.pop("text", None))
    values = dict(outputfile=tmp_path / "report", maxguess=1, maxsteps=2,
                  drawgraph=False, verbose=False)
    values.update(options)
    return run_autoguess(source, **values)


def xor_function():
    function = Layered_Function("OPTIMIZATION_XOR", "u", 1, 1, 3, 0, 1)
    a, b = function.vars[1][0][:2]
    target = function.vars[1][1][0]
    function.constraints[1][0] = [XOR([a, b], [target], ID="OPTIMIZATION_XOR_1_1_0")]
    return function, a, b, target


def public_solve(tmp_path, *, model_type="maxsat", objective="OPTIMAL", **options):
    function, a, b, target = xor_function()
    config = {"time_limit": 5, **options}
    result = gd.search_guess_basis(
        function, known_vars=[a.ID], target_vars=[target.ID],
        objective_target=objective, show_mode=0,
        config_model={"model_type": model_type, "filename": str(tmp_path / "relations_ocp.txt"), "maxsteps": 2},
        config_solver=config,
    )
    return result, (function, a, b, target)


@pytest.mark.parametrize("limit", [-1, 5])
def test_maxsat_uses_interruptible_default_even_without_timeout(tmp_path, limit):
    result = solve(tmp_path, solver="maxsat", time_limit=limit)
    assert result["status"] == "sat" and result["optimal"]
    assert result["cost"] == result["lower_bound"] == result["upper_bound"] == 1
    assert result["parameters"]["satsolver"] == "glucose3"
    assert result["guessed_variables"] == ["b"]


def test_paid_seed_and_certificate_preserve_fixed_knowns_and_objects(tmp_path, capsys):
    function, a, b, target = xor_function()
    result = gd.search_guess_basis(
        function, known_vars=[a.ID], target_vars=[target.ID], objective_target="OPTIMAL",
        config_model={"model_type": "maxsat", "filename": str(tmp_path / "relations_ocp.txt"), "maxsteps": 2},
        config_solver={"seed_basis": [b.ID], "lower_bound": True, "time_limit": 5},
        show_mode=0,
    )
    assert result["known_variable_ids"] == [a.ID] and result["known_variables"] == [a]
    assert result["guessed_variable_ids"] == [b.ID] and result["guessed_variables"] == [b]
    assert result["target_variables"] == [target]
    assert result["seed_cost"] == result["cost"] == result["lower_bound"] == 1
    assert result["optimal"] and result["lower_bound_certificate"]
    assert result["proof_method"] == "verified_lower_bound_matches_incumbent"
    assert result["unresolved_variable_ids"] == []
    output = capsys.readouterr().out
    assert output.count("STATUS: SAT") == 1
    assert "Guess cost: 1" in output and "Known variables: " + a.ID in output
    assert "Guessed variables: " + b.ID in output
    assert "MODEL GENERATION" not in output


@pytest.mark.parametrize("solver", ["sat", "maxsat"])
def test_zero_budget_retains_paid_basis_without_inventing_optimality(tmp_path, solver):
    result = solve(tmp_path, solver=solver, findmin=True, time_limit=0,
                   seed_basis=["b"])
    assert result["status"] == "sat" and result["cost"] == result["seed_cost"] == 1
    assert result["known_variables"] == ["a"] and result["guessed_variables"] == ["b"]
    assert result["timed_out"] and not result["optimal"]
    assert result["lower_bound"] == 0 and result["upper_bound"] == 1


@pytest.mark.parametrize("contents", [["b"], {"guessed_variables": ["b"]},
                                     {"guessed_variable_ids": ["alias"], "guessed_variables": []}])
def test_seed_json_supports_ids_and_cleaner_aliases(tmp_path, contents):
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(contents))
    objects = {name: Variable(1, ID=name) for name in ("a", "b", "c", "alias")}
    result = solve(tmp_path, solver="maxsat", seed_basis_file=seed_file,
        lower_bound=True, cipher_or_function=SimpleNamespace(vars_dictionary=objects),
        relation_metadata={"variable_aliases": {"alias": "b"}})
    assert result["seed_basis"] == ["b"] and result["seed_cost"] == 1
    assert result["guessed_variables"] == [objects["b"]]
    assert result["parameters"]["seed_basis_source_file"] == str(seed_file.resolve())
    assert json.loads(seed_file.read_text()) == contents


def test_refinement_can_replace_a_seed_instead_of_making_it_known(tmp_path):
    result = solve(tmp_path, solver="sat", maxguess=2, maxsteps=1,
        seed_basis=["a", "b"], refine_basis=True, refine_trials=200,
        refine_time=1, random_seed=17, time_limit=5,
        text="connection relations\na=>u\nb=>v\nc=>u\nc=>v\ntarget\nu\nv\nnot guessed\nu\nv\nend\n")
    assert result["seed_cost"] == 2 and result["cost"] == 1
    assert result["guessed_variables"] == ["c"] and result["known_variables"] == []
    assert result["cost_improved"] and result["refinement"]["trials"] <= 200
    assert result["refinement"]["time_limit"] == 1
    assert result["targets_covered"]


@pytest.mark.parametrize("solver", ["cp", "milp"])
def test_direct_native_findmin_compatibility_routes_to_native_minimization(tmp_path, monkeypatch, solver):
    module = engine_module("autoguess")
    received = []

    def native_minimization(parameters):
        received.append(dict(parameters))
        assert parameters["findmin"] is False
        return {"status": "unknown", "optimal": False, "guessed_variables": [],
                "known_variables": [], "target_variables": [], "determination_steps": []}

    monkeypatch.setattr(module, "startsearch", native_minimization)
    solve(tmp_path, solver=solver, findmin=True)
    assert received[0]["cpoptimization"] == 1 and received[0]["milpdirection"] == "min"


@pytest.mark.parametrize("solver", ["cp", "milp"])
def test_ocp_optimal_preserves_native_cp_milp_optimization(tmp_path, monkeypatch, solver):
    captured = []

    def fake_native(inputfile, *, cipher_or_function, **options):
        captured.append(options)
        assert options["findmin"] is False
        return {"status": "sat", "optimal": True, "cost": 1, "guessed_variable_ids": ["paid"],
                "guessed_variables": [], "known_variables": [], "determination_steps": []}

    monkeypatch.setattr(gd, "run_autoguess", fake_native)
    result, _ = public_solve(tmp_path, model_type=solver)
    assert result["optimal"]
    assert captured[0]["cpoptimization"] == 1 and captured[0]["milpdirection"] == "min"


def test_weighted_ocp_postcondition_uses_cost_not_guess_count(tmp_path, monkeypatch):
    function, a, b, target = xor_function()

    def weighted_relations(obj, *, output_file, metadata_out, **kwargs):
        lines = ["connection relations", f"{a.ID},{b.ID}=>{target.ID}", "target", target.ID,
                 "not guessed", target.ID, "weights", a.ID + " 0", b.ID + " 0", "end"]
        Path(output_file).write_text("\n".join(lines) + "\n")
        metadata_out["variable_aliases"] = {}
        return lines

    monkeypatch.setattr(gd, "generate_relations", weighted_relations)
    result = gd.search_guess_basis(function, target_vars=[target.ID], objective_target="AT MOST 0",
        config_model={"model_type": "maxsat", "filename": str(tmp_path / "relations_weighted.txt"), "maxsteps": 1})
    assert result["status"] == "sat" and result["cost"] == 0
    assert set(result["guessed_variable_ids"]) == {a.ID, b.ID}


@pytest.mark.parametrize("options", [
    {"refine_basis": True}, {"refine_time": 1}, {"lower_bound": "yes"},
    {"seed_basis": [1]}, {"refine_trials": -1}, {"random_seed": True},
    {"D": -1}, {"time_limit": float("nan")},
])
def test_invalid_options_leave_existing_relation_file_untouched(tmp_path, options):
    function, a, _, target = xor_function()
    source = tmp_path / "relations_saved.txt"
    source.write_text("original saved relations\n")
    with pytest.raises(ValueError):
        gd.search_guess_basis(function, known_vars=[a.ID], target_vars=[target.ID],
            config_model={"filename": str(source)}, config_solver=options)
    assert source.read_text() == "original saved relations\n"


def test_maxsat_rejects_explicit_unsupported_backend_before_model_write(tmp_path):
    function, *_ = xor_function()
    source = tmp_path / "relations_saved.txt"
    source.write_text("original saved relations\n")
    with pytest.raises(ValueError, match="Glucose|glucose"):
        gd.search_guess_basis(function, config_model={"model_type": "maxsat", "filename": str(source)},
                             config_solver={"solver": "cadical153"})
    assert source.read_text() == "original saved relations\n"


def test_report_cannot_overwrite_relation_input(tmp_path):
    source = relation_file(tmp_path)
    original = source.read_text()
    with pytest.raises(ValueError, match="report must differ"):
        run_autoguess(source, outputfile=source, drawgraph=False)
    assert source.read_text() == original


def test_report_cannot_overwrite_paid_seed_input(tmp_path):
    source = relation_file(tmp_path)
    seed = tmp_path / "seed.json"
    seed.write_text('["b"]\n')
    with pytest.raises(ValueError, match="paid seed input must differ"):
        run_autoguess(source, outputfile=seed, seed_basis_file=seed, drawgraph=False)
    assert seed.read_text() == '["b"]\n'


def test_extensionless_ocp_filename_keeps_relations_separate_from_report(tmp_path):
    function, a, _, target = xor_function()
    source = tmp_path / "custom_relations"
    result = gd.search_guess_basis(function, known_vars=[a.ID], target_vars=[target.ID],
        config_model={"filename": str(source), "maxsteps": 2},
        config_solver={"time_limit": 5})
    assert result["status"] == "sat"
    assert result["outputfile"] == str(source) + "_output"
    assert source.read_text().startswith("connection relations\n")


def test_graph_settings_are_forwarded_and_summarized(tmp_path):
    result = solve(tmp_path, graph_view="deduction", graph_scope="full", drawgraph=True,
                   solver="maxsat", print_result=True)
    assert result["graph_summary"]["view"] == "deduction"
    assert result["parameters"]["graph_scope"] == "full"
    assert Path(result["graph_files"]["gv"]).is_file()


@pytest.mark.parametrize("drawgraph", [False, True])
def test_retired_cipher_view_is_rejected_before_reading_or_overwriting_reports(tmp_path, drawgraph):
    source = relation_file(tmp_path)
    report = tmp_path / "saved-report"
    report.write_text("existing successful report\n")
    original_relations = source.read_text()
    with pytest.raises(ValueError, match="graph_view must be original or deduction"):
        run_autoguess(source, outputfile=report, graph_view="cipher", drawgraph=drawgraph)
    assert source.read_text() == original_relations
    assert report.read_text() == "existing successful report\n"


@pytest.mark.parametrize("show_mode", [0, 1])
def test_public_ocp_rejects_retired_cipher_view_before_relation_generation(tmp_path, show_mode):
    function, a, _, target = xor_function()
    source = tmp_path / "relations_saved.txt"
    source.write_text("original saved relations\n")
    with pytest.raises(ValueError, match="graph_view must be original or deduction"):
        gd.search_guess_basis(function, known_vars=[a.ID], target_vars=[target.ID],
            show_mode=show_mode, config_model={"filename": str(source)},
            config_solver={"graph_view": "cipher"})
    assert source.read_text() == "original saved relations\n"


def test_paid_original_id_is_normalized_through_actual_relation_cleaner(tmp_path):
    from operators.operators import Equal

    function = Layered_Function("OPTIMIZATION_ALIAS_XOR", "u", 1, 2, 3, 0, 1)
    original, known = function.vars[1][0][:2]
    renamed = function.vars[1][1][0]
    target = function.vars[1][2][0]
    function.constraints[1][0] = [Equal([original], [renamed], ID="ALIAS_EQUAL_1_1_0")]
    function.constraints[1][1] = [XOR([renamed, known], [target], ID="ALIAS_XOR_1_2_0")]
    result = gd.search_guess_basis(function, known_vars=[known.ID], target_vars=[target.ID],
        objective_target="OPTIMAL", config_solver={"seed_basis": [renamed.ID], "lower_bound": True},
        config_model={"model_type": "maxsat", "filename": str(tmp_path / "relations_alias.txt"), "maxsteps": 2})
    assert result["status"] == "sat" and result["optimal"] and result["seed_cost"] == 1
    assert result["known_variable_ids"] == [known.ID]
    assert len(result["seed_basis"]) == 1
    assert result["seed_basis"][0] == result["guessed_variable_ids"][0]
    assert result["guessed_variables"][0].ID == result["seed_basis"][0]


