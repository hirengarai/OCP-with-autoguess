import time

import attacks.differential_cryptanalysis as diff
import attacks.linear_cryptanalysis as linear
import attacks.guess_and_determine as gnd

# **************************************************************************** #
# This module provides a high-level attack interfaces, including:
# 1. differential attacks
# 2. linear attacks
# 3. guess-and-determine attacks
# 4. other types of attacks (to be contributed in the future)
# **************************************************************************** #


# =================== Differential Attacks ===================
def diff_attacks(cipher, goal="DIFFERENTIALPATH_PROB", constraints=["INPUT_NOT_ZERO"], objective_target="OPTIMAL", show_mode=0, config_model=None, config_solver=None):
    time_start = time.time()

    if goal in ["DIFFERENTIAL_SBOXCOUNT", "DIFFERENTIALPATH_PROB", "DIFFERENTIAL_PROB", "TRUNCATEDDIFF_SBOXCOUNT"]:
        trails = diff.search_diff_trail(cipher, goal=goal, constraints=constraints, objective_target=objective_target, show_mode=show_mode, config_model=config_model, config_solver=config_solver)
    else:
        raise ValueError(f"[WARNING] Invalid goal: {goal}.")

    print(f"--- Total Time ---: {time.time() - time_start:.2f} seconds")
    return trails


# =================== Linear Attacks ===================
def linear_attacks(cipher, goal="LINEARPATH_CORRE", constraints=["INPUT_NOT_ZERO"], objective_target="OPTIMAL", show_mode=0, config_model=None, config_solver=None):
    time_start = time.time()

    if goal in ["LINEAR_SBOXCOUNT", "LINEARPATH_CORRE", "LINEAR_CORRE", "TRUNCATEDLINEAR_SBOXCOUNT"]:
        trails = linear.search_linear_trail(cipher, goal=goal, constraints=constraints, objective_target=objective_target, show_mode=show_mode, config_model=config_model, config_solver=config_solver)
    else:
        raise ValueError(f"[WARNING] Invalid goal: {goal}.")

    print(f"--- Total Time ---: {time.time() - time_start:.2f} seconds")
    return trails


# =================== Guess-and-Determine Attacks ===================
# Uses Autoguess solver to find minimal guess basis
def gd_attack(cipher, known_vars=None, target_vars=None, solver="sat", maxguess=50, maxsteps=20, relationfile=None, outputfile=None, tikz=0, dglayout="dot", **kwargs):
    """
    Perform guess-and-determine attack using Autoguess solver.

    Finds the minimal set of variables that need to be guessed
    to determine all target variables.

    Parameters
    ----------
    cipher : Cipher or Function object
        The cipher or function to analyze (block cipher, key schedule, etc.)

    known_vars : list of str, optional
        Variables that are known to the attacker (e.g., plaintext, ciphertext).
        If None, must be set manually using the returned object.

    target_vars : list of str, optional
        Variables that the attacker wants to determine.
        If None, targets all variables in the cipher.

    solver : str, default='sat'
        Solver to use: 'sat', 'cp', 'smt', 'milp', 'groebner'
        - 'sat': SAT solver (fast, recommended for most cases)
        - 'cp': Constraint programming solver
        - 'smt': SMT solver
        - 'milp': Mixed integer linear programming
        - 'groebner': Groebner basis algorithm

    maxguess : int, default=50
        Maximum number of guessed variables to search for.

    maxsteps : int, default=20
        Maximum determination steps (search depth).

    outputfile : str, default='autoguess_output'
        Base name for output files (without extension).

    tikz : int, default=0
        Generate TikZ LaTeX code for the determination graph:
        - 0: Only generate PDF graph
        - 1: Generate both PDF and LaTeX/TikZ code

    dglayout : str, default='dot'
        Graph layout algorithm: 'dot', 'neato', 'fdp', 'sfdp', 'circo', 'twopi'

    **kwargs
        Additional solver-specific parameters (e.g., satsolver='cadical153')

    Returns
    -------
    AutoguessResult
        Result object with num_guesses and guess_basis

    Examples
    --------
    >>> from attacks import attacks
    >>> import primitives.aes as aes
    >>>
    >>> cipher = aes.AES_block_cipher(rounds=2, key_length=128)
    >>> func = cipher.functions["PERMUTATION"]
    >>> known = [v.ID for v in func.vars[1][0]] + [v.ID for v in func.vars[2][4]]
    >>>
    >>> result = attacks.gd_attack(cipher, known_vars=known, solver='sat', maxguess=20)
    >>> print(f"Attack complexity: 2^{result.num_guesses}")
    """
    time_start = time.time()

    # Use the high-level API from guess_and_determine module
    result = gnd.run_autoguess(
        cipher,
        known_vars=known_vars,
        target_vars=target_vars,
        solver=solver,
        maxguess=maxguess,
        maxsteps=maxsteps,
        relationfile=relationfile,
        outputfile=outputfile,
        tikz=tikz,
        dglayout=dglayout,
        **kwargs
    )

    print(f"--- Total Time ---: {time.time() - time_start:.2f} seconds")
    return result
