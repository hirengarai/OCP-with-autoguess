"""
Guess-and-determine engine.

`search_guess_basis` runs the two-step AutoGuess pipeline:
  1. Generate a relation file from the cipher/function (relation_generator).
  2. Solve it with AutoGuess to find a guess basis.

The entry point deliberately mirrors the other OCP attack engines
(`search_diff_trail`, `search_linear_trail`, `search_integral_distinguisher`):
the caller passes a cipher, a `goal`, an `objective_target`, a `show_mode`, and
two plain dictionaries `config_model` / `config_solver`.

    result = search_guess_basis(
        cipher,
        target_vars=[...],
        objective_target="AT MOST 20",
        config_model={"model_type": "sat", "skip_rounds": [4]},
        config_solver={"solver": "cadical153"},
    )

`RelGenConfig` / `SolverConfig` below are internal plumbing: they carry the
defaults of the two downstream tools and are populated from those two dicts.
Callers never need to import them.

The function auto-detects whether its input is a full cipher (has `.functions`)
or a single function (has `.constraints` directly).

The user-facing wrapper with timing lives in `attacks.attacks` as
`guess_and_determine_attack`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List, Optional

from tools.autoguess_wrapper import run_autoguess
from tools.relation_generator import generate_relations


ROOT = Path(__file__).resolve().parents[1]
# Relation files and AutoGuess outputs land here. This is where the existing
# (git-tracked) artifacts live, and where relation_generator resolves relative
# paths, so the two stay in agreement. Override via config_model["filename"].
FILES_DIR = ROOT / "test" / "autoguess" / "files"

# Accepted values of `goal`, in the style of the other attack modules.
GOALS = ("GUESSBASIS", "REDUCEBASIS")

# Accepted values of config_model["model_type"]: the framework AutoGuess encodes
# the guess-and-determine problem into. The OCP analogue is the 'milp'/'sat'
# switch used by the differential/linear/integral engines.
MODEL_TYPES = ("sat", "milp", "smt", "cp", "mark", "elim", "propagate")

# Frameworks whose concrete backend is selectable through config_solver["solver"],
# and the run_autoguess argument that carries it.
_BACKEND_ARG = {"sat": "satsolver", "smt": "smtsolver", "cp": "cpsolver"}


# Configuration objects
@dataclass
class RelGenConfig:
    """
    Options forwarded to `tools.relation_generator.generate_relations`.

    Populated from `config_model`; all fields default to the same values as the
    underlying generator, so `RelGenConfig()` is a no-op override.

    skip_layers, skip_ops, skip_rounds, skip_functions
        Filters passed to relation_generator. See its docstring. These are the
        guess-and-determine analogue of the "functions"/"rounds"/"layers" keys
        that the other OCP attacks put in `config_model`.

    sbox_form : "rename" | "implication" | None, default None
        Per-S-box emission form. ``None`` infers from wiring shape
        (single multi-bit var in/out → "rename"; otherwise "implication").
        Use ``"rename"``/``"implication"`` to override.

    algebraic_layers : list of str, optional
        Layer class names emitted algebraically (e.g. ["MatrixLayer"]).

    perm_rename, rot_rename, gf2linear_rename : bool
        If True, collapse the corresponding linear operations by renaming
        variables instead of emitting identity relations.

    cleaning_direction : str or None, default None
        One of "input", "output", "default", "opp_default". Selects which
        round-boundary side the canonical reps land on. None means use
        "default".
            "input"       — uniform input boundary; survivors at vk_<k+1>_0_*.
            "output"      — uniform output boundary; survivors at vk_<k>_<max>_*.
            "default"     — earliest layer + earlier round; histogram
                            splits between layer 0 and max_layer.
            "opp_default" — opposite mixed corner.

    bridge_skipped_rounds : bool, default True
        If True, equate values across skipped rounds via bridge relations.
    """

    skip_layers: Optional[List[str]] = None
    skip_ops: Optional[List[str]] = None
    skip_rounds: Optional[List[int]] = None
    skip_functions: Optional[List[str]] = None
    sbox_form: Optional[str] = None
    algebraic_layers: Optional[List[str]] = None
    perm_rename: bool = True
    rot_rename: bool = True
    gf2linear_rename: bool = True
    cleaning_direction: Optional[str] = None
    emit_debug_chains: bool = False
    bridge_skipped_rounds: bool = True


@dataclass
class SolverConfig:
    """
    Options forwarded to `tools.autoguess_wrapper.run_autoguess`.

    Populated from `config_solver`, plus the fields that `search_guess_basis`
    derives from `goal` / `objective_target` / `show_mode`: `solver`, `findmin`,
    `maxguess`, `maxsteps`, `reducebasis`, `drawgraph`, `tikz` and `log`.
    """

    solver: str = "sat"
    findmin: bool = False
    maxguess: Optional[int] = None
    maxsteps: Optional[int] = None
    reducebasis: bool = False
    drawgraph: bool = True
    satsolver: str = "cadical153"
    smtsolver: str = "z3"
    cpsolver: str = "cp-sat"
    milpdirection: str = "min"
    cpoptimization: int = 1
    timelimit: int = -1
    threads: int = 0
    preprocess: int = 0
    tikz: int = 0
    dglayout: str = "dot"
    log: int = 0


# Keys accepted in each configuration dict.
_RELGEN_KEYS = {f.name for f in fields(RelGenConfig)}
# config_model keys consumed by this module rather than forwarded to the generator.
_MODEL_LOCAL_KEYS = {"model_type", "filename", "name_prefix", "maxsteps"}
_MODEL_KEYS = _RELGEN_KEYS | _MODEL_LOCAL_KEYS
_SOLVER_KEYS = {"solver", "timelimit", "threads", "preprocess",
                "milpdirection", "cpoptimization", "dglayout"}


# =================== Configuration parsing ===================
def _reject_unknown_keys(label, config, accepted):
    """Fail loudly on a misspelled or misplaced configuration key."""
    unknown = sorted(set(config) - accepted)
    if unknown:
        raise ValueError(f"Invalid {label} key(s): {unknown}. Expected one of {sorted(accepted)}.")


def _parse_objective_target(objective_target):
    """Translate OCP's ``objective_target`` into AutoGuess' ``(findmin, maxguess)``.

    'OPTIMAL' asks AutoGuess to minimise the basis size; 'AT MOST X' caps it;
    'EXISTENCE' takes whatever basis the encoding yields. OCP's 'EXACTLY X' and
    'AT LEAST X' have no AutoGuess counterpart and are rejected rather than
    silently reinterpreted.
    """
    if objective_target == "EXISTENCE":
        return False, None
    if objective_target == "OPTIMAL":
        return True, None
    if objective_target.startswith("AT MOST"):
        bound = objective_target[len("AT MOST"):].strip()
        if not bound.isdigit():
            raise ValueError(f"Invalid objective_target: {objective_target}. Expected 'AT MOST X' with integer X.")
        return False, int(bound)
    raise ValueError(f"Invalid objective_target: {objective_target}. "
                     f"Expected one of ['OPTIMAL', 'AT MOST X', 'EXISTENCE'].")


def _default_relation_filename(cipher_or_function, name_prefix=None):
    """Default relation-file name, e.g. ``relations_AES_AES128_3r.txt``.

    Mirrors ``relation_generator._auto_filename`` (plus the optional prefix) so
    the artifact names already in test/autoguess/files keep being reused. The
    name intentionally omits goal/objective_target: the relation system depends
    only on the model, so runs differing only in objective share the file.
    """
    function_mode = not hasattr(cipher_or_function, "functions")
    name = getattr(cipher_or_function, "name", "function" if function_mode else "cipher")
    parts = ["relations"] + ([name_prefix] if name_prefix else []) + [name]
    filename = "_".join(parts)
    rounds = getattr(cipher_or_function, "nbr_rounds", None)
    if rounds is not None:
        filename += f"_{rounds}r"
    return filename + ".txt"


def _parse_and_set_configs(cipher_or_function, goal, objective_target, config_model, config_solver):
    """Fill in default model/solver configuration and return ``(config_model, config_solver)``.

    Same contract as the ``_parse_and_set_configs`` helpers in the differential,
    linear and integral modules. ``goal`` and ``objective_target`` are part of
    that shared signature but unused here: those modules fold them into the
    model filename, whereas a guess-and-determine relation system depends only
    on the cipher and the modelling options.
    """
    config_model = dict(config_model or {})
    config_solver = dict(config_solver or {})
    _reject_unknown_keys("config_model", config_model, _MODEL_KEYS)
    _reject_unknown_keys("config_solver", config_solver, _SOLVER_KEYS)

    # Set "model_type", the automated model framework.
    config_model["model_type"] = config_model.get("model_type", "sat").lower()
    if config_model["model_type"] not in MODEL_TYPES:
        raise ValueError(f"Invalid model_type: {config_model['model_type']}. Expected one of {list(MODEL_TYPES)}.")

    # Set the model "filename", i.e. the relation file handed to AutoGuess.
    FILES_DIR.mkdir(parents=True, exist_ok=True)  # ensure the output directory exists
    filename = config_model.get("filename")
    if filename is None:
        filename = _default_relation_filename(cipher_or_function, config_model.get("name_prefix"))
    if not Path(filename).is_absolute():
        filename = str(FILES_DIR / filename)
    config_model["filename"] = filename

    # Set "solver" for solving the model.
    config_solver.setdefault("solver", "DEFAULT")

    return config_model, config_solver


def _backend_kwargs(model_type, solver):
    """Map the single OCP-style ``solver`` key onto AutoGuess' per-framework backend argument.

    'DEFAULT' keeps run_autoguess' own default for the framework, matching how
    the other OCP attacks treat config_solver["solver"].
    """
    arg = _BACKEND_ARG.get(model_type)
    if arg is None:
        if solver != "DEFAULT":
            print(f"[WARNING] config_solver['solver']='{solver}' ignored: model_type='{model_type}' "
                  f"has no selectable backend. Applicable to {sorted(_BACKEND_ARG)}.")
        return {}
    return {} if solver == "DEFAULT" else {arg: solver}


def _verbosity_kwargs(show_mode):
    """Map OCP's 0-3 ``show_mode`` onto AutoGuess' log / drawgraph / tikz switches.

    The ladder goes result-detail first, diagnostics second: the determination
    graph is part of the result, the solver log is noise about how it was found.
    """
    return {
        0: {"log": 0, "drawgraph": False, "tikz": 0},  # results only
        1: {"log": 0, "drawgraph": True, "tikz": 0},   # + determination graph
        2: {"log": 1, "drawgraph": True, "tikz": 0},   # + solver log
        3: {"log": 1, "drawgraph": True, "tikz": 1},   # + TikZ source
    }[show_mode]


# Engine
def search_guess_basis(cipher_or_function, goal="GUESSBASIS", known_vars=None,
                       target_vars=None, not_guessed_vars=None, protect_all_targets=False,
                       objective_target="EXISTENCE", show_mode=0, config_model=None,
                       config_solver=None):
    """Search for a guess-and-determine basis of the specified cipher.

    Args:
        cipher_or_function: The cipher object to analyze. A single function is
            also accepted (e.g. ``cipher.functions["KEY_SCHEDULE"]``).
        goal (str): Cryptanalysis goal, one of ``"GUESSBASIS"`` (search a guess
            basis) or ``"REDUCEBASIS"`` (reduce a supplied basis through the
            propagation-based reducer).
        known_vars, target_vars, not_guessed_vars (list, optional): Variable IDs
            marking initial knowns, recovery targets, and variables forbidden
            from being guessed.
        protect_all_targets (bool): If True, every target variable is implicitly
            added to ``not_guessed_vars`` (key recovery). If False, only the
            first target is protected.
        objective_target (str): The target for the objective function:
            - 'EXISTENCE': Find any guess basis.
            - 'OPTIMAL': Find a minimum-size guess basis.
            - 'AT MOST X': Find a guess basis of size at most X.
        show_mode (int): Result-printing detail level (0-3); see
            ``_verbosity_kwargs``.
        config_model (dict, optional): Advanced modeling options; see
            ``_parse_and_set_configs``. Accepts ``"model_type"``, ``"filename"``,
            ``"name_prefix"``, ``"maxsteps"`` and every ``RelGenConfig`` field.
        config_solver (dict, optional): Advanced solver options; see
            ``_parse_and_set_configs``. Accepts ``"solver"``, ``"timelimit"``,
            ``"threads"``, ``"preprocess"``, ``"milpdirection"``,
            ``"cpoptimization"`` and ``"dglayout"``.

    Returns:
        dict: The guess basis found, with keys
            - 'outputfile'         : path to AutoGuess output
            - 'cipher'             : input cipher / function
            - 'known_variables'    : OCP Variables marked known
            - 'target_variables'   : OCP Variables marked targets
            - 'guessed_variables'  : OCP Variables in the guess basis
            - 'determination_steps': list of {step, determined_vars}
    """
    if goal not in GOALS:
        raise ValueError(f"Invalid goal: {goal}. Expected one of {list(GOALS)}.")
    for label, value in (("known_vars", known_vars), ("target_vars", target_vars),
                         ("not_guessed_vars", not_guessed_vars)):
        if not (value is None or isinstance(value, list)):
            raise ValueError(f"Invalid {label}: {value}. Expected a list of variable IDs or None.")
    if show_mode not in (0, 1, 2, 3):
        raise ValueError(f"Invalid show_mode: {show_mode}. Expected one of [0, 1, 2, 3].")
    if not (isinstance(config_model, dict) or config_model is None):
        raise ValueError(f"Invalid config_model: {config_model}. Expected a dictionary or None.")
    if not (isinstance(config_solver, dict) or config_solver is None):
        raise ValueError(f"Invalid config_solver: {config_solver}. Expected a dictionary or None.")
    findmin, maxguess = _parse_objective_target(objective_target)

    # Step 1. Parse and set model and solver configurations.
    config_model, config_solver = _parse_and_set_configs(cipher_or_function, goal, objective_target,
                                                         config_model, config_solver)
    model_type, relation_file = config_model["model_type"], config_model["filename"]
    function_mode = not hasattr(cipher_or_function, "functions")

    # Step 2. Keep at least one target unguessable, otherwise the solver returns
    # the trivial basis "guess the targets".
    if target_vars:
        ng = set(not_guessed_vars or [])
        if protect_all_targets:
            ng.update(target_vars)
        elif not ng.intersection(target_vars):
            ng.add(target_vars[0])
        not_guessed_vars = list(ng)

    # Step 3. Generate the relation system for the cipher.
    relgen_cfg = RelGenConfig(**{k: v for k, v in config_model.items() if k in _RELGEN_KEYS})
    generate_relations(
        cipher_or_function,
        function_mode=function_mode,
        known=known_vars,
        target=target_vars,
        not_guessed=not_guessed_vars,
        output_file=relation_file,
        **asdict(relgen_cfg),
    )

    # Step 4. Solve it. AutoGuess' own "solver" argument names the framework,
    # which is what config_model["model_type"] carries here.
    solver_cfg = SolverConfig(
        solver=model_type,
        findmin=findmin,
        maxguess=maxguess,
        maxsteps=config_model.get("maxsteps"),
        reducebasis=(goal == "REDUCEBASIS"),
        **_backend_kwargs(model_type, config_solver["solver"]),
        **{k: v for k, v in config_solver.items() if k != "solver"},
        **_verbosity_kwargs(show_mode),
    )
    ag_outputfile = str(
        Path(relation_file).parent
        / Path(relation_file).stem.replace("relations_", "output_")
    )
    return run_autoguess(
        inputfile=relation_file,
        cipher_or_function=cipher_or_function,
        outputfile=ag_outputfile,
        known=known_vars,
        **asdict(solver_cfg),
    )
