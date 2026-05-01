"""
Guess-and-determine engine.

`search_guess_basis` runs the two-step AutoGuess pipeline:
  1. Generate a relation file from the cipher/function (relation_generator).
  2. Solve it with AutoGuess to find a minimal guess basis.

The function auto-detects whether its input is a full cipher (has
`.functions`) or a single function (has `.constraints` directly).

This module is the *engine*. The user-facing wrapper with timing lives in
`attacks.attacks` as `guess_and_determine_attack`.
"""

from __future__ import annotations

from pathlib import Path

from tools.autoguess_wrapper import run_autoguess
from tools.relation_generator import generate_relations


def search_guess_basis(
    cipher_or_function,
    *,
    # Variable sections
    known_vars=None,
    target_vars=None,
    not_guessed_vars=None,
    protect_all_targets=False,
    # Relation generation options
    name_prefix=None,
    skip_layers=None,
    skip_ops=None,
    skip_rounds=None,
    skip_functions=None,
    flat_sbox=True,
    algebraic_layers=None,
    perm_rename=True,
    rot_rename=True,
    gf2linear_rename=True,
    output_file=None,
    canonical=True,
    cross_round_dir=False,
    bridge_skipped_rounds=True,
    # AutoGuess solver options
    solver="sat",
    findmin=False,
    maxguess=None,
    maxsteps=None,
    reducebasis=False,
    drawgraph=True,
    satsolver="cadical153",
    smtsolver="z3",
    cpsolver="cp-sat",
    milpdirection="min",
    cpoptimization=1,
    timelimit=-1,
    threads=0,
    preprocess=0,
    tikz=0,
    dglayout="dot",
    log=0,
):
    """
    Run a guess-and-determine attack on an OCP cipher or function.

    Parameters
    ----------
    cipher_or_function : Cipher or Function object from OCP.
        Pass a full cipher or a single function (e.g.
        `cipher.functions["KEY_SCHEDULE"]`).

    --- Variable sections ---

    known_vars : list of str, optional
        Variable IDs initially known to the attacker (e.g. plaintext
        / ciphertext bytes). These don't need to be guessed or determined.

    target_vars : list of str, optional
        Variable IDs that must be determined by the end. The solver
        finds the minimum set of guesses needed to determine all targets.

    not_guessed_vars : list of str, optional
        Variable IDs the solver is forbidden from guessing. Useful for
        key recovery where only key variables (vk_*) should be guessable,
        so all state variables (vs_*) are placed here.

    protect_all_targets : bool, default False
        If True, every target variable is implicitly added to
        not_guessed_vars (key recovery). If False, only the first target
        is protected (default for plain guess-and-determine).

    --- Relation generation options ---

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

    --- AutoGuess solver options ---

    solver : str, default "sat"
        Backend: 'sat' | 'milp' | 'smt' | 'cp' | 'mark' | 'elim' | 'propagate'.

    findmin : bool, default False
        If True, iterate to find the minimum guess count.

    maxguess : int, optional
        Upper bound on guessed variables.

    maxsteps : int, optional
        Maximum determination depth.

    Other options forwarded to the AutoGuess wrapper.

    Returns
    -------
    dict
        Result dictionary containing:
        - 'outputfile'         : path to AutoGuess output
        - 'cipher'             : input cipher / function
        - 'known_variables'    : OCP Variables marked known
        - 'target_variables'   : OCP Variables marked targets
        - 'guessed_variables'  : OCP Variables in the guess basis
        - 'determination_steps': list of {step, determined_vars}
    """
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
        skip_layers=skip_layers,
        skip_ops=skip_ops,
        skip_rounds=skip_rounds,
        skip_functions=skip_functions,
        flat_sbox=flat_sbox,
        algebraic_layers=algebraic_layers,
        perm_rename=perm_rename,
        rot_rename=rot_rename,
        gf2linear_rename=gf2linear_rename,
        canonical=canonical,
        cross_round_dir=cross_round_dir,
        bridge_skipped_rounds=bridge_skipped_rounds,
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
        solver=solver,
        findmin=findmin,
        maxguess=maxguess,
        maxsteps=maxsteps,
        reducebasis=reducebasis,
        known=known_vars,
        drawgraph=drawgraph,
        satsolver=satsolver,
        smtsolver=smtsolver,
        cpsolver=cpsolver,
        milpdirection=milpdirection,
        cpoptimization=cpoptimization,
        timelimit=timelimit,
        threads=threads,
        preprocess=preprocess,
        tikz=tikz,
        dglayout=dglayout,
        log=log,
    )

    return result
