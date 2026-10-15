"""Small end-to-end checks for solver results crossing the OCP boundary."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from attacks.guess_and_determine import search_guess_basis
from operators.boolean_operators import XOR
from primitives.primitives import Layered_Function
from tools.autoguess_wrapper import run_autoguess
from variables.variables import Variable


def relation_file(tmp_path, known=("a",), target="c"):
    path = tmp_path / "relations.txt"
    path.write_text(
        "connection relations\na,b,c\nknown\n" + "\n".join(known)
        + f"\ntarget\n{target}\nnot guessed\n{target}\nend\n"
    )
    return path


def mapped_cipher():
    return SimpleNamespace(vars_dictionary={v: Variable(1, ID=v) for v in "abc"})


def xor_function():
    function = Layered_Function("UNIT_XOR", "u", 1, 1, 3, 0, 1)
    a, b = function.vars[1][0][:2]
    c = function.vars[1][1][0]
    function.constraints[1][0] = [XOR([a, b], [c], ID="XOR_1_1_0")]
    return function, a, b, c


def test_unsat_never_returns_previous_basis(tmp_path):
    path = relation_file(tmp_path)
    output = tmp_path / "output"
    options = dict(cipher_or_function=mapped_cipher(), outputfile=output,
                   maxsteps=2, drawgraph=False)
    success = run_autoguess(path, maxguess=1, **options)
    assert success["status"] == "sat"
    assert success["guessed_variable_ids"] == ["b"]
    previous_report = output.read_text()
    failure = run_autoguess(path, maxguess=0, **options)
    assert failure["status"] == "unsat"
    assert failure["guessed_variables"] == []
    assert failure["guessed_variable_ids"] == []
    assert failure["outputfile"] is None
    # Old reports may remain on disk, but are never used as current results.
    assert output.read_text() == previous_report


def test_zero_guess_optimum_returns_current_solution(tmp_path):
    path = relation_file(tmp_path, known=("a", "b"))
    output = tmp_path / "output"
    output.write_text("an old report that must never be parsed")
    result = run_autoguess(path, cipher_or_function=mapped_cipher(),
                           outputfile=output, maxguess=1, maxsteps=2,
                           findmin=True, drawgraph=False)
    assert result["status"] == "sat"
    assert result["optimal"]
    assert result["guessed_variable_ids"] == []
    assert result["target_variable_ids"] == ["c"]
    assert result["targets_covered"]
    assert "Number of guessed variables: 0" in output.read_text()


def test_single_function_maps_solver_ids_to_ocp_objects(tmp_path):
    function, a, b, c = xor_function()
    result = search_guess_basis(
        function, known_vars=[a.ID], target_vars=[c.ID],
        objective_target="AT MOST 1",
        config_model={"filename": str(tmp_path / "relations_unit.txt"), "maxsteps": 2},
    )
    assert result["status"] == "sat"
    assert result["guessed_variables"] == [b]
    assert result["target_variables"] == [c]
    assert result["known_variables"] == [a]
    assert result["unresolved_variable_ids"] == []
    assert result["targets_covered"]
    assert len(result["model_hash"]) == 64


def test_ocp_reducer_does_not_treat_basis_as_fixed_knowledge(tmp_path):
    function, a, b, c = xor_function()
    result = search_guess_basis(
        function, goal="REDUCEBASIS", known_vars=[a.ID, b.ID], target_vars=[c.ID],
        config_model={"filename": str(tmp_path / "relations_reduce.txt")},
    )
    assert result["status"] == "sat"
    assert set(result["guessed_variable_ids"]) == {a.ID, b.ID}
    assert result["known_variables"] == []
    assert result["targets_covered"]


def test_unknown_ocp_target_is_rejected_before_solving(tmp_path):
    function, *_ = xor_function()
    path = tmp_path / "relations_bad.txt"
    with pytest.raises(ValueError, match="Unknown OCP variable IDs"):
        search_guess_basis(function, target_vars=["typo"],
                           config_model={"filename": str(path)})
    assert not path.exists()


def test_relative_paths_and_working_directory_are_preserved(tmp_path, monkeypatch):
    relation_file(tmp_path)
    monkeypatch.chdir(tmp_path)
    original_path = sys.path[:]
    result = run_autoguess("relations.txt", outputfile="nested/output", maxguess=1,
                           maxsteps=2, drawgraph=False)
    assert result["status"] == "sat"
    assert Path.cwd() == tmp_path
    assert sys.path == original_path
    assert (tmp_path / "nested" / "output").is_file()
    with pytest.raises(ValueError):
        run_autoguess("missing.txt", drawgraph=False)
    assert Path.cwd() == tmp_path
    assert sys.path == original_path


def test_preprocessing_after_direct_vendor_import_uses_managed_temp(tmp_path, monkeypatch):
    import importlib

    monkeypatch.syspath_prepend(str(ROOT / "tools" / "autoguess"))
    parser = importlib.import_module("core.inputparser")
    monkeypatch.setattr(parser, "TEMP_DIR", "uncreated-relative-temp")
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "algebraic.txt"
    path.write_text("algebraic relations\na+b\nknown\na\ntarget\nb\nend\n")
    result = run_autoguess(path, outputfile=tmp_path / "output", maxguess=0,
                           maxsteps=2, preprocess=1, drawgraph=False)
    assert result["status"] == "sat"
    assert result["targets_covered"]
    assert parser.TEMP_DIR == "uncreated-relative-temp"
    assert Path.cwd() == tmp_path
