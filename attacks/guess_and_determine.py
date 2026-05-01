"""
Guess-and-determine engine.

`search_guess_basis` runs the two-step AutoGuess pipeline:
  1. Generate a relation file from the cipher/function (relation_generator).
  2. Solve it with AutoGuess to find a minimal guess basis.

Configuration is grouped via two dataclasses:

    from attacks.guess_and_determine import RelGenConfig, SolverConfig

    result = search_guess_basis(
        cipher,
        target_vars=[...],
        relgen_cfg=RelGenConfig(skip_rounds=[4], flat_sbox=False),
        solver_cfg=SolverConfig(solver="sat", findmin=True, maxguess=20),
    )

The function auto-detects whether its input is a full cipher (has
`.functions`) or a single function (has `.constraints` directly).

The user-facing wrapper with timing lives in `attacks.attacks` as
`guess_and_determine_attack`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from tools.autoguess_wrapper import run_autoguess
from tools.relation_generator import generate_relations


# ---------------------------------------------------------------------------
# Configuration objects
# ---------------------------------------------------------------------------


@dataclass
class RelGenConfig:
    """
    Options forwarded to `tools.relation_generator.generate_relations`.

    All fields default to the same values as the underlying generator,
    so `RelGenConfig()` is a no-op override.
    name_prefix : str, optional
        Prefix for the output relation/result filenames.

    skip_layers, skip_ops, skip_rounds, skip_functions
        Filters passed to relation_generator. See its docstring.

    flat_sbox : bool, default True
        If True, emit S-box as a flat lookup table; otherwise as
        Boolean equations.

    algebraic_layers : list of str, optional
        Layer class names emitted algebraically (e.g. ["MatrixLayer"]).

    perm_rename, rot_rename, gf2linear_rename : bool
        If True, collapse the corresponding linear operations by renaming
        variables instead of emitting identity relations.

    output_file : str, optional
        Explicit relation-file path. If None, auto-generated.

    canonical : bool, default True
        If True, sort variables within each relation alphabetically.

    cross_round_dir : bool, default False
        If True, emit cross-round linking relations.

    bridge_skipped_rounds : bool, default True
        If True, equate values across skipped rounds via bridge relations.
    """

    skip_layers: Optional[List[str]] = None
    skip_ops: Optional[List[str]] = None
    skip_rounds: Optional[List[int]] = None
    skip_functions: Optional[List[str]] = None
    flat_sbox: bool = True
    algebraic_layers: Optional[List[str]] = None
    perm_rename: bool = True
    rot_rename: bool = True
    gf2linear_rename: bool = True
    canonical: bool = True
    cross_round_dir: bool = False
    bridge_skipped_rounds: bool = True


@dataclass
class SolverConfig:
    """
    Options forwarded to `tools.autoguess_wrapper.run_autoguess`.

    `solver` selects the backend: 'sat' | 'milp' | 'smt' | 'cp' |
    'mark' | 'elim' | 'propagate'. `reducebasis=True` reroutes through
    the propagation-based reducer regardless of the chosen backend.
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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def search_guess_basis(
    cipher_or_function,
    *,
    # Variable selection — the actual arguments to the attack
    known_vars: Optional[List[str]] = None,
    target_vars: Optional[List[str]] = None,
    not_guessed_vars: Optional[List[str]] = None,
    protect_all_targets: bool = False,
    # Output naming — orchestration concerns
    name_prefix: Optional[str] = None,
    output_file: Optional[str] = None,
    # Configuration groups
    relgen_cfg: Optional[RelGenConfig] = None,
    solver_cfg: Optional[SolverConfig] = None,
):
    """
    Run a guess-and-determine attack on an OCP cipher or function.

    Parameters
    ----------
    cipher_or_function : Cipher or Function from OCP.
        Pass a full cipher or a single function (e.g.
        `cipher.functions["KEY_SCHEDULE"]`).

    known_vars, target_vars, not_guessed_vars : list of str, optional
        Variable IDs marking initial knowns, recovery targets, and
        variables forbidden from being guessed.

    protect_all_targets : bool, default False
        If True, every target variable is implicitly added to
        not_guessed_vars (key recovery). If False, only the first
        target is protected.

    name_prefix : str, optional
        Prefix for the auto-generated relation/output filenames.

    output_file : str, optional
        Explicit relation-file path. If None, auto-generated.

    relgen_cfg : RelGenConfig, optional
        Relation-generation options. Defaults applied if None.

    solver_cfg : SolverConfig, optional
        AutoGuess solver options. Defaults applied if None.

    Returns
    -------
    dict
        - 'outputfile'         : path to AutoGuess output
        - 'cipher'             : input cipher / function
        - 'known_variables'    : OCP Variables marked known
        - 'target_variables'   : OCP Variables marked targets
        - 'guessed_variables'  : OCP Variables in the guess basis
        - 'determination_steps': list of {step, determined_vars}
    """
    relgen_cfg = relgen_cfg or RelGenConfig()
    solver_cfg = solver_cfg or SolverConfig()

    function_mode = not hasattr(cipher_or_function, "functions")

    # Ensure not all targets are guessable (would yield trivial solution).
    if target_vars:
        ng = set(not_guessed_vars or [])
        if protect_all_targets:
            ng.update(target_vars)
        elif not ng.intersection(target_vars):
            ng.add(target_vars[0])
        not_guessed_vars = list(ng)

    if output_file is None and name_prefix:
        name = getattr(
            cipher_or_function, "name", "function" if function_mode else "cipher"
        )
        rounds = getattr(cipher_or_function, "nbr_rounds", None)
        fname = f"relations_{name_prefix}_{name}"
        if rounds is not None:
            fname += f"_{rounds}r"
        output_file = fname + ".txt"

    generate_relations(
        cipher_or_function,
        function_mode=function_mode,
        known=known_vars,
        target=target_vars,
        not_guessed=not_guessed_vars,
        output_file=output_file,
        **asdict(relgen_cfg),
    )

    # Resolve output_file path (matches generate_relations' resolution).
    if output_file is None:
        name = getattr(cipher_or_function, "name", "cipher")
        rounds = getattr(cipher_or_function, "nbr_rounds", None)
        fname = f"relations_{name}"
        if rounds is not None:
            fname += f"_{rounds}r"
        output_file = fname + ".txt"
    if not Path(output_file).is_absolute():
        project_root = Path(__file__).resolve().parents[1]
        output_dir = project_root / "test" / "autoguess" / "files"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = str(output_dir / output_file)

    ag_outputfile = str(
        Path(output_file).parent
        / Path(output_file).stem.replace("relations_", "output_")
    )
    result = run_autoguess(
        inputfile=output_file,
        cipher_or_function=cipher_or_function,
        outputfile=ag_outputfile,
        known=known_vars,
        **asdict(solver_cfg),
    )

    return result
