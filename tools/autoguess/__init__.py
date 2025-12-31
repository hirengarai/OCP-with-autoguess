"""
Wrapper utilities for the autoguess solver.

Exposes a stable solve_autoguess() API for OCP integration.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict


_AUTOGUESS_DIR = Path(__file__).resolve().parent
if str(_AUTOGUESS_DIR) not in sys.path:
    # Allow autoguess.py to import its sibling modules (core, config, ...).
    sys.path.insert(0, str(_AUTOGUESS_DIR))

try:
    import autoguess as _autoguess
except Exception as exc:  # pragma: no cover - import wrapper
    raise ImportError("Failed to import autoguess module") from exc


def _list_or_none(value: Any):
    return None if value is None else [value]


def _build_args(params: Dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        inputfile=_list_or_none(params.get("inputfile")),
        outputfile=_list_or_none(params.get("outputfile")),
        maxguess=_list_or_none(params.get("maxguess")),
        maxsteps=_list_or_none(params.get("maxsteps")),
        solver=_list_or_none(params.get("solver")),
        milpdirection=_list_or_none(params.get("milpdirection")),
        timelimit=_list_or_none(params.get("timelimit")),
        cpsolver=_list_or_none(params.get("cpsolver")),
        satsolver=_list_or_none(params.get("satsolver")),
        smtsolver=_list_or_none(params.get("smtsolver")),
        cpoptimization=_list_or_none(params.get("cpoptimization")),
        tikz=_list_or_none(params.get("tikz")),
        preprocess=_list_or_none(params.get("preprocess")),
        D=_list_or_none(params.get("D")),
        term_ordering=_list_or_none(params.get("term_ordering")),
        overlapping_number=_list_or_none(params.get("overlapping_number")),
        cnf_to_anf_conversion=_list_or_none(params.get("cnf_to_anf_conversion")),
        dglayout=_list_or_none(params.get("dglayout")),
        log=_list_or_none(params.get("log")),
    )


def solve_autoguess(
    *,
    inputfile: str | None = None,
    outputfile: str | None = None,
    solver: str | None = None,
    maxguess: int | None = None,
    maxsteps: int | None = None,
    timelimit: int | None = None,
    preprocess: int | None = None,
    D: int | None = None,
    tikz: int | None = None,
    dglayout: str | None = None,
    tool: str | None = None,
    milpdirection: str | None = None,
    cpsolver: str | None = None,
    satsolver: str | None = None,
    smtsolver: str | None = None,
    cpoptimization: int | None = None,
    term_ordering: str | None = None,
    overlapping_number: int | None = None,
    cnf_to_anf_conversion: str | None = None,
    log: int | None = None,
    **kwargs: Any,
):
    """Run autoguess with a stable API for OCP integration."""

    if tool is not None:
        if solver == "cp":
            cpsolver = tool
        elif solver == "sat":
            satsolver = tool
        elif solver == "smt":
            smtsolver = tool
        elif solver == "milp" and tool in {"min", "max"}:
            milpdirection = tool

    params = {
        "inputfile": inputfile,
        "outputfile": outputfile,
        "solver": solver,
        "maxguess": maxguess,
        "maxsteps": maxsteps,
        "timelimit": -1 if timelimit is None else timelimit,
        "preprocess": preprocess,
        "D": D,
        "tikz": tikz,
        "dglayout": dglayout,
        "milpdirection": milpdirection,
        "cpsolver": cpsolver,
        "satsolver": satsolver,
        "smtsolver": smtsolver,
        "cpoptimization": cpoptimization,
        "term_ordering": term_ordering,
        "overlapping_number": overlapping_number,
        "cnf_to_anf_conversion": cnf_to_anf_conversion,
        "log": log,
    }
    params.update(kwargs)

    _autoguess.checkenvironment()
    args = _build_args(params)
    tool_params = _autoguess.loadparameters(args)
    _autoguess.startsearch(tool_params)
    return tool_params


__all__ = ["solve_autoguess"]
