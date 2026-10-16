"""
AutoGuess Wrapper — thin bridge to call AutoGuess from within OCP.

AutoGuess lives at tools/autoguess/ and uses internal imports like
"from core.search import ..." and "from config import TEMP_DIR".
These only work when autoguess/ is on sys.path.

This wrapper handles that path setup, then exposes a simple function:

    from tools.autoguess_wrapper import run_autoguess

    run_autoguess(
        'relations_aes_2r.txt',
        cipher_or_function=cipher,
        solver='sat',
        findmin=True,
    )

Results come directly from the solver, never from a previously written report.
"""

import functools
from contextlib import nullcontext
import json
import math
import os
import sys
import threading
from pathlib import Path

# Path to the autoguess directory inside OCP
_AUTOGUESS_DIR = Path(__file__).resolve().parent / "autoguess"
_AUTOGUESS_LOCK = threading.RLock()


def _read_paid_seed(filename):
    with open(filename) as stream:
        seed = json.load(stream)
    if isinstance(seed, dict):
        seed = seed.get("guessed_variable_ids", seed.get("guessed_variables"))
    if not isinstance(seed, list) or any(not isinstance(v, str) for v in seed):
        raise ValueError("Seed JSON must contain a variable ID list or guessed_variables/guessed_variable_ids")
    return seed


def _validate_solver_options(options):
    """Reject incompatible options before generating relations or reports."""
    solver = options.get("solver", "sat")
    if solver not in {"sat", "maxsat", "smt", "cp", "milp", "mark", "elim", "propagate"}:
        raise ValueError("Unsupported AutoGuess solver: %s" % solver)
    time_limit = options.get("time_limit")
    if time_limit is None:
        time_limit = options.get("timelimit", -1)
    if isinstance(time_limit, bool) or not isinstance(time_limit, (int, float)) or not math.isfinite(time_limit) or time_limit < 0 and time_limit != -1:
        raise ValueError("Time limit must be nonnegative or -1 (finite numeric values only)")
    degree = options.get("D", 2)
    if isinstance(degree, bool) or not isinstance(degree, int) or degree < 0:
        raise ValueError("D must be a nonnegative integer")
    for key in ("lower_bound", "refine_basis"):
        if not isinstance(options.get(key, False), bool):
            raise ValueError(key + " must be a boolean")
    seed, seed_file = options.get("seed_basis"), options.get("seed_basis_file")
    if seed is not None and seed_file is not None:
        raise ValueError("Use either seed_basis or seed_basis_file")
    if seed is not None and (not isinstance(seed, (str, list, tuple)) or
                            isinstance(seed, (list, tuple)) and any(not isinstance(v, str) for v in seed)):
        raise ValueError("seed_basis must contain variable ID strings")
    if seed_file is not None and not isinstance(seed_file, (str, os.PathLike)):
        raise ValueError("seed_basis_file must be a path")
    if seed_file is not None:
        protected = {Path(options[key]).expanduser().resolve() for key in ("inputfile", "outputfile")
                     if options.get(key) is not None}
        if Path(seed_file).expanduser().resolve() in protected:
            raise ValueError("The paid seed input must differ from the relation input and report paths")
        _read_paid_seed(Path(seed_file).expanduser())
    if options.get("refine_basis") and seed is None and seed_file is None:
        raise ValueError("refine_basis requires a fully paid seed_basis or seed_basis_file")
    local_limit = options.get("refine_time")
    if local_limit is not None:
        if not options.get("refine_basis"):
            raise ValueError("refine_time requires refine_basis")
        if isinstance(local_limit, bool) or not isinstance(local_limit, (int, float)) or not math.isfinite(local_limit) or local_limit < 0:
            raise ValueError("refine_time must be finite and nonnegative")
    trials = options.get("refine_trials", 1000)
    if isinstance(trials, bool) or not isinstance(trials, int) or trials < 0:
        raise ValueError("refine_trials must be a nonnegative integer")
    random_seed = options.get("random_seed", 0)
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ValueError("random_seed must be an integer")
    advanced = (solver == "maxsat" or seed is not None or seed_file is not None or
                options.get("lower_bound") or options.get("refine_basis"))
    if advanced and options.get("reducebasis"):
        raise ValueError("REDUCEBASIS cannot be combined with paid-seed optimization options")
    if advanced and solver not in {"sat", "maxsat", "smt", "cp", "milp"}:
        raise ValueError("Paid seeds, bounds and refinement require SAT, MaxSAT, SMT, CP or MILP")
    if solver == "milp" and (advanced or options.get("findmin")) and options.get("milpdirection", "min") != "min":
        raise ValueError("Optimization options require MILP minimization")
    if solver == "cp" and options.get("findmin") and options.get("cpoptimization", 1) != 1:
        raise ValueError("OPTIMAL with CP requires cpoptimization=1")
    if solver == "maxsat" and options.get("satsolver") not in (None, "g3", "glucose3"):
        raise ValueError("MaxSAT requires the g3/glucose3 SAT backend")
    if options.get("term_ordering", "degrevlex") != "degrevlex":
        raise ValueError("Relation preprocessing supports only term_ordering='degrevlex'")
    if options.get("graph_view", "original") not in {"original", "deduction"}:
        raise ValueError("graph_view must be original or deduction")
    if options.get("graph_scope", "targets") not in {"targets", "full"}:
        raise ValueError("graph_scope must be targets or full")


def _print_result_summary(result):
    """Print one OCP result summary using stable IDs, before object mapping."""
    print("STATUS: %s" % result["status"].upper())
    print("Termination: %s" % result.get("termination_reason", "unknown"))
    if "elapsed_seconds" in result:
        print("Elapsed: %.3f seconds" % result["elapsed_seconds"])
    print("Targets covered: %d / %d" % (len(result.get("covered_target_variables", [])),
                                          len(result.get("target_variables", []))))
    if result.get("cost") is not None:
        print("Guess cost: %s" % result["cost"])
    print("Known variables: %s" % (", ".join(result.get("known_variables", [])) or "(none)"))
    print("Guessed variables: %s" % (", ".join(result.get("guessed_variables", [])) or "(none)"))
    if "lower_bound" in result:
        upper = result.get("upper_bound", result.get("cost"))
        print("Cost bounds: %s .. %s" % (result["lower_bound"], upper if upper is not None else "unknown"))
    if result.get("propagation_steps") is not None:
        print("Target propagation steps: %s" % result["propagation_steps"])
    print("Optimal: %s" % ("yes" if result.get("optimal") else "not established"))
    if result.get("timed_out"):
        print("Time limit reached; returning the best validated basis found." if result["status"] == "sat"
              else "Time limit reached; no complete basis was found (status: unknown).")
    if result.get("outputfile"):
        print("Current report: %s" % result["outputfile"])
    for kind, path in result.get("graph_files", {}).items():
        print("Current graph (%s): %s" % (kind.upper(), path))


def _with_autoguess_path(func):
    """
    Temporarily make the vendored imports available, without changing cwd.

    Absolute input/output/temp paths avoid changing the caller's process-wide
    working directory. Serialize our import/config setup for concurrent calls.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _AUTOGUESS_LOCK:
            old_path = sys.path[:]
            try:
                ag_str = str(_AUTOGUESS_DIR)
                if ag_str not in sys.path:
                    sys.path.insert(0, ag_str)
                import config as ag_config

                old_temp_dir = ag_config.TEMP_DIR
                temp_dir = str(
                    _AUTOGUESS_DIR.parents[1] / "test" / "autoguess" / "files" / "temp"
                )
                ag_config.TEMP_DIR = temp_dir
                os.makedirs(temp_dir, exist_ok=True)
                # Vendored modules use ``from config import TEMP_DIR``. A
                # direct import before this wrapper otherwise leaves a stale
                # relative path, dependent on notebook/test import order.
                cached_temp_dirs = []
                for name, module in list(sys.modules.items()):
                    if not name.startswith(("core.", "autoguess", "tools.autoguess.")):
                        continue
                    filename = getattr(module, "__file__", None)
                    if filename and Path(filename).resolve().is_relative_to(_AUTOGUESS_DIR) and hasattr(module, "TEMP_DIR"):
                        cached_temp_dirs.append((module, module.TEMP_DIR))
                        module.TEMP_DIR = temp_dir
                try:
                    return func(*args, **kwargs)
                finally:
                    for module, previous in cached_temp_dirs:
                        module.TEMP_DIR = previous
                    ag_config.TEMP_DIR = old_temp_dir
            finally:
                sys.path[:] = old_path

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


def _variable_dictionary(cipher_or_function):
    """Resolve both complete primitives and single Layered_Function objects."""
    result = dict(getattr(cipher_or_function, "vars_dictionary", {}) or {})
    visited = set()

    def visit(value):
        if id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
        elif hasattr(value, "ID"):
            result[value.ID] = value
            visit(getattr(value, "copied_vars", ()))

    functions = getattr(cipher_or_function, "functions", {})
    for function in functions.values() if isinstance(functions, dict) else ():
        visit(getattr(function, "vars", ()))
    visit(getattr(cipher_or_function, "vars", ()))
    visit(getattr(cipher_or_function, "inputs", ()))
    visit(getattr(cipher_or_function, "outputs", ()))
    return result


def _resolve_result(result, cipher_or_function):
    """Attach OCP objects while retaining every original ID, including dummies."""
    result = dict(result)
    variables = _variable_dictionary(cipher_or_function)
    unresolved = set()

    def resolve(ids):
        unresolved.update(vid for vid in ids if vid not in variables)
        return [variables[vid] for vid in ids if vid in variables]

    for role in ("known", "target", "guessed"):
        ids = list(result.get(f"{role}_variables", []))
        result[f"{role}_variable_ids"] = ids
        result[f"{role}_variables"] = resolve(ids)
    steps = []
    for step in result.get("determination_steps", []):
        step = dict(step)
        ids = list(step.get("determined_vars", []))
        step["determined_var_ids"] = ids
        step["determined_vars"] = resolve(ids)
        steps.append(step)
    result["determination_steps"] = steps
    result["unresolved_variable_ids"] = sorted(unresolved)
    result["cipher"] = cipher_or_function
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
    satsolver=None,
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
    time_limit=None,
    seed_basis=None,
    seed_basis_file=None,
    lower_bound=False,
    refine_basis=False,
    refine_time=None,
    refine_trials=1000,
    random_seed=0,
    graph_view="original",
    graph_scope="targets",
    verbose=None,
    print_result=False,
    relation_metadata=None,
):
    """
    Run AutoGuess on a relation file.

    Parameters
    ----------
    inputfile : str
        Path to the relation file (absolute or relative to the caller's cwd).

    cipher_or_function : Cipher or Function object, optional
        OCP cipher/function whose vars_dictionary is used to resolve
        variable IDs in the output back to Variable objects.

    solver : str
        One of: 'sat', 'maxsat', 'milp', 'smt', 'cp', 'mark', 'elim', 'propagate'.

    maxguess : int, optional
        Upper bound on guessed variables. Auto-computed if None.

    maxsteps : int, optional
        Search depth. Auto-computed if None.

    findmin : bool
        Find minimum guess basis iteratively.

    reducebasis : bool
        Reduce a guess basis (requires known variables).

    time_limit : float, optional
        One search budget in seconds, shared by preprocessing, model creation,
        and all optimization attempts. ``-1`` is unlimited; ``0`` permits no
        search time. Result verification and report writing can finish afterward.

    timelimit : float
        Existing spelling of ``time_limit``, retained for compatibility. If both
        are supplied, a non-default ``timelimit`` must equal ``time_limit``.

    satsolver : str, optional
        PySAT backend. When omitted, timed SAT uses interruptible ``glucose3``;
        unlimited SAT uses ``cadical153``. Explicit choices are preserved.

    known : list of str, optional
        Extra known variables.

    seed_basis : list of str, optional
        Fully paid starting guesses, distinct from fixed ``known`` variables.
        Use IDs in the cleaned relation file, such as a previous OCP result's
        ``guessed_variable_ids``. ``seed_basis_file`` also accepts a JSON list
        or a standalone result containing ``guessed_variables`` IDs, or a saved
        OCP result containing ``guessed_variable_ids``.

    lower_bound, refine_basis : bool
        Verify a formal lower-bound certificate, or refine the paid seed.
        Refinement and native solving share the request's time budget.

    verbose : bool, optional
        Scope native progress output; None preserves direct API verbosity.
        ``print_result`` requests one final summary with original IDs.

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
        Every result includes ``status`` (sat/unsat/unknown), ``optimal``,
        ``termination_reason``, ``timed_out``, ``elapsed_seconds``,
        ``time_limit`` (also available as ``time_limit_seconds``) and ID lists.
        A timeout returns a validated
        incumbent with ``status='sat'`` and ``optimal=False``, or ``unknown``
        when no complete basis was found. Without a cipher/function the variable
        lists contain IDs.
    """
    from core.solverresult import get_time_limit

    time_options = {"timelimit": timelimit}
    if time_limit is not None:
        if timelimit == -1:
            time_options = {"time_limit": time_limit}
        else:
            time_options["time_limit"] = time_limit
    time_limit = get_time_limit(time_options)
    _validate_solver_options(locals())
    if verbose is not None and not isinstance(verbose, bool):
        raise ValueError("verbose must be a boolean or None")
    if not isinstance(print_result, bool):
        raise ValueError("print_result must be a boolean")

    input_path = str(Path(inputfile).expanduser().resolve())
    output_path = str(Path(outputfile).expanduser().resolve())
    if input_path == output_path:
        raise ValueError("The text report must differ from the input file")
    if seed_basis_file is not None:
        seed_basis_file = str(Path(seed_basis_file).expanduser().resolve())
        if seed_basis_file in {input_path, output_path}:
            raise ValueError("The paid seed input must differ from the relation input and report paths")

    # Build params dict
    params = _default_params()
    params.update(
        {
            "inputfile": input_path,
            "outputfile": output_path,
            "solver": solver,
            "maxguess": maxguess,
            "maxsteps": maxsteps,
            # Native CP/MILP already minimize; the standalone findmin flag is
            # reserved for incremental SAT/SMT descent.
            "findmin": findmin and solver in {"sat", "smt"},
            "reducebasis": reducebasis,
            "known": known,
            "drawgraph": drawgraph,
            "satsolver": satsolver if satsolver is not None else (
                "glucose3" if solver == "maxsat" or solver == "sat" and time_limit != -1 else "cadical153"
            ),
            "smtsolver": smtsolver,
            "cpsolver": cpsolver,
            "milpdirection": milpdirection,
            "cpoptimization": cpoptimization,
            "time_limit": time_limit,
            "timelimit": time_limit,
            "preprocess": preprocess,
            "D": D,
            "tikz": tikz,
            "log": log,
            "threads": threads,
            "dglayout": dglayout,
            "term_ordering": term_ordering,
            "overlapping_number": overlapping_number,
            "cnf_to_anf_conversion": cnf_to_anf_conversion,
            "graph_view": graph_view,
            "graph_scope": graph_scope,
            "lower_bound": lower_bound,
            "refine_basis": refine_basis,
            "refine_trials": refine_trials,
            "random_seed": random_seed,
        }
    )
    for name, value in (("seed_basis", seed_basis), ("seed_basis_file", seed_basis_file),
                        ("refine_time", refine_time)):
        if value is not None:
            params[name] = value

    # Normalize original OCP IDs through the cleaner's actual alias map. The
    # seed remains paid; fixed knowns and relation roles are never rewritten.
    if seed_basis_file is not None:
        seed_basis = _read_paid_seed(seed_basis_file)
        params.pop("seed_basis_file")
        params["seed_basis_source_file"] = seed_basis_file
    if seed_basis is not None:
        groups = [seed_basis] if isinstance(seed_basis, str) else seed_basis
        aliases = (relation_metadata or {}).get("variable_aliases", {})
        params["seed_basis"] = list(dict.fromkeys(
            aliases.get(v.strip(), v.strip())
            for group in groups for v in group.split(",") if v.strip()
        ))

    # Import and run autoguess (inside the path context)
    from autoguess import startsearch, checkenvironment

    checkenvironment()
    from core.graphreport import validate_graph_options
    validate_graph_options(params, additional_paths=[seed_basis_file])

    if reducebasis:
        params["solver"] = "propagate"
        params["reducebasis"] = True
    Path(params["outputfile"]).parent.mkdir(parents=True, exist_ok=True)
    from core.console import progress_output
    with progress_output(verbose) if verbose is not None else nullcontext():
        result = startsearch(params)
    if not isinstance(result, dict) or result.get("status") not in {"sat", "unsat", "unknown"}:
        raise RuntimeError("AutoGuess did not return a structured solver result")
    result["parameters"] = dict(params)
    if print_result:
        _print_result_summary(result)
    if cipher_or_function is not None:
        return _resolve_result(result, cipher_or_function)
    return result
