"""
AutoGuess Wrapper — thin bridge to call AutoGuess from within OCP.

AutoGuess lives at tools/autoguess/ and uses internal imports like
"from core.search import ..." and "from config import TEMP_DIR".
These only work when autoguess/ is on sys.path.

This wrapper handles that path setup, then exposes a simple function:

    from tools.autoguess_wrapper import run_autoguess

    run_autoguess(
        cipher,
        inputfile='relations_aes_2r.txt',
        solver='sat',
        findmin=True,
    )

AutoGuess itself is NOT modified — it stays self-contained.
"""

import functools
import os
import re
import sys
from pathlib import Path

# Path to the autoguess directory inside OCP
_AUTOGUESS_DIR = Path(__file__).resolve().parent / "autoguess"


def _with_autoguess_path(func):
    """
    Decorator that temporarily adds autoguess/ to sys.path,
    changes cwd to autoguess/, runs the function, then restores both.

    AutoGuess expects:
      - sys.path to include its own directory (for 'from core.xxx' imports)
      - cwd to be its own directory (for 'temp/' relative paths)
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        old_path = sys.path[:]
        old_cwd = os.getcwd()

        try:
            # Add autoguess dir to front of sys.path
            ag_str = str(_AUTOGUESS_DIR)
            if ag_str not in sys.path:
                sys.path.insert(0, ag_str)

            # Change to autoguess dir so relative paths work
            os.chdir(_AUTOGUESS_DIR)

            # Override TEMP_DIR to store temp files in test/autoguess/files/temp/
            import config as ag_config

            old_temp_dir = ag_config.TEMP_DIR
            temp_dir = str(
                _AUTOGUESS_DIR.parents[1] / "test" / "autoguess" / "files" / "temp"
            )
            ag_config.TEMP_DIR = temp_dir
            os.makedirs(temp_dir, exist_ok=True)

            try:
                return func(*args, **kwargs)
            finally:
                ag_config.TEMP_DIR = old_temp_dir
        finally:
            # Restore original state
            sys.path[:] = old_path
            os.chdir(old_cwd)

    return wrapper


def _default_params():
    """Return AutoGuess default parameters (same as autoguess.py loadparameters)."""
    return {
        "inputfile": None,
        "outputfile": "output",
        "maxguess": None,
        "maxsteps": None,
        "solver": "sat",
        "milpdirection": "min",
        "timelimit": -1,
        "cpsolver": "cp-sat",
        "satsolver": "cadical153",
        "smtsolver": "z3",
        "cpoptimization": 1,
        "tikz": 0,
        "preprocess": 0,
        "D": 2,
        "term_ordering": "degrevlex",
        "overlapping_number": 2,
        "cnf_to_anf_conversion": "simple",
        "dglayout": "dot",
        "log": 0,
        "known": None,
        "threads": 0,
        "drawgraph": True,
        "findmin": False,
        "reducebasis": False,
    }


def _parse_autoguess_output(output_path, vars_dict):
    """
    Parse the AutoGuess output file and convert variable IDs to OCP Variable objects.

    Parameters
    ----------
    output_path : str
        Path to the AutoGuess output file.
    vars_dict : dict
        Mapping from variable ID strings to Variable objects (cipher.vars_dictionary).

    Returns
    -------
    dict with keys:
        outputfile, known_variables, target_variables, guessed_variables,
        determination_steps
    """
    result = {
        "outputfile": output_path,
        "known_variables": [],
        "target_variables": [],
        "guessed_variables": [],
        "determination_steps": [],
    }

    if not os.path.exists(output_path):
        return result

    with open(output_path, "r") as f:
        content = f.read()

    separator = "############################################################"
    sections = content.split(separator)

    def _resolve_vars(id_string):
        """Split comma-separated var IDs and resolve to Variable objects."""
        ids = [v.strip() for v in id_string.split(",") if v.strip()]
        resolved = []
        for vid in ids:
            # Strip dummy annotations like " (represents: ...)"
            clean_id = vid.split(" (represents:")[0].strip()
            if clean_id in vars_dict:
                resolved.append(vars_dict[clean_id])
        return resolved

    # parsesolution.py writes the separator after every State block, so the
    # determination flow is split across multiple chunks. current_step must
    # persist across sections to accumulate State 0, State 1, ...
    current_step = None

    for section in sections:
        stripped = section.strip()

        # Guessed variables section
        if "variable(s) are guessed:" in stripped:
            lines = stripped.split("\n")
            for line in lines:
                if "variable(s) are guessed:" in line:
                    continue
                if line.strip():
                    result["guessed_variables"] = _resolve_vars(line)

        # Known variables section
        elif "variable(s) are initially known:" in stripped:
            lines = stripped.split("\n")
            for line in lines:
                if "variable(s) are initially known:" in line:
                    continue
                if line.strip():
                    result["known_variables"] = _resolve_vars(line)

        # Target variables section
        elif stripped.startswith("Target variables:"):
            lines = stripped.split("\n")
            for line in lines[1:]:
                if line.strip():
                    result["target_variables"] = _resolve_vars(line)

        # Determination flow: header chunk OR a continuation State X chunk
        elif stripped.startswith("Determination flow:") or re.match(
            r"State\s+\d+:", stripped
        ):
            for line in stripped.split("\n"):
                state_match = re.match(r"State\s+(\d+):", line)
                if state_match:
                    current_step = {
                        "step": int(state_match.group(1)),
                        "determined_vars": [],
                    }
                    result["determination_steps"].append(current_step)
                elif current_step is not None and "===>" in line:
                    rhs = line.split("===>")[1].strip()
                    current_step["determined_vars"].extend(_resolve_vars(rhs))

    return result


@_with_autoguess_path
def run_autoguess(
    inputfile,
    *,
    cipher_or_function=None,
    outputfile="output",
    solver="sat",
    maxguess=None,
    maxsteps=None,
    findmin=False,
    reducebasis=False,
    known=None,
    drawgraph=True,
    satsolver="cadical153",
    smtsolver="z3",
    cpsolver="cp-sat",
    milpdirection="min",
    cpoptimization=1,
    timelimit=-1,
    preprocess=0,
    D=2,
    tikz=0,
    log=0,
    threads=0,
    dglayout="dot",
    term_ordering="degrevlex",
    overlapping_number=2,
    cnf_to_anf_conversion="simple",
):
    """
    Run AutoGuess on a relation file.

    Parameters
    ----------
    inputfile : str
        Path to the relation file (absolute or relative to OCP root).

    cipher_or_function : Cipher or Function object, optional
        OCP cipher/function whose vars_dictionary is used to resolve
        variable IDs in the output back to Variable objects.

    solver : str
        One of: 'sat', 'milp', 'smt', 'cp', 'mark', 'elim', 'propagate'.

    maxguess : int, optional
        Upper bound on guessed variables. Auto-computed if None.

    maxsteps : int, optional
        Search depth. Auto-computed if None.

    findmin : bool
        Find minimum guess basis iteratively.

    reducebasis : bool
        Reduce a guess basis (requires known variables).

    known : list of str, optional
        Extra known variables.

    drawgraph : bool
        Generate determination flow graph.

    For other parameters, see AutoGuess documentation.

    Returns
    -------
    dict
        If cipher_or_function is provided:
            {
                'outputfile': str,
                'cipher': cipher_or_function,
                'known_variables': [Variable, ...],
                'target_variables': [Variable, ...],
                'guessed_variables': [Variable, ...],
                'determination_steps': [
                    {'step': int, 'determined_vars': [Variable, ...]},
                    ...
                ],
            }
        Otherwise: the raw AutoGuess parameters dict.
    """
    # Build params dict
    params = _default_params()
    params.update(
        {
            "inputfile": str(inputfile),
            "outputfile": outputfile,
            "solver": solver,
            "maxguess": maxguess,
            "maxsteps": maxsteps,
            "findmin": findmin,
            "reducebasis": reducebasis,
            "known": known,
            "drawgraph": drawgraph,
            "satsolver": satsolver,
            "smtsolver": smtsolver,
            "cpsolver": cpsolver,
            "milpdirection": milpdirection,
            "cpoptimization": cpoptimization,
            "timelimit": timelimit,
            "preprocess": preprocess,
            "D": D,
            "tikz": tikz,
            "log": log,
            "threads": threads,
            "dglayout": dglayout,
            "term_ordering": term_ordering,
            "overlapping_number": overlapping_number,
            "cnf_to_anf_conversion": cnf_to_anf_conversion,
        }
    )

    # Import and run autoguess (inside the path context)
    from autoguess import startsearch, checkenvironment

    checkenvironment()

    if reducebasis:
        params["solver"] = "propagate"
        params["reducebasis"] = True
    startsearch(params)

    # If a cipher/function was provided, parse output and return Variable objects
    if cipher_or_function is not None:
        vars_dict = getattr(cipher_or_function, "vars_dictionary", {})
        output_path = str(_AUTOGUESS_DIR / params["outputfile"])
        result = _parse_autoguess_output(output_path, vars_dict)
        result["cipher"] = cipher_or_function
        return result

    return params
