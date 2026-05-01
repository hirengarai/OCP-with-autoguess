import time

import attacks.differential_cryptanalysis as diff
import attacks.linear_cryptanalysis as linear
import attacks.guess_and_determine as gd

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
def linear_attacks(cipher, goal="LINEARPATH_CORR", constraints=["INPUT_NOT_ZERO"], objective_target="OPTIMAL", show_mode=0, config_model=None, config_solver=None):
    time_start = time.time()

    if goal in ["LINEAR_SBOXCOUNT", "LINEARPATH_CORR", "LINEARHULL_CORR", "TRUNCATEDLINEAR_SBOXCOUNT"]:
        trails = linear.search_linear_trail(cipher, goal=goal, constraints=constraints, objective_target=objective_target, show_mode=show_mode, config_model=config_model, config_solver=config_solver)
    else:
        raise ValueError(f"[WARNING] Invalid goal: {goal}.")

    print(f"--- Total Time ---: {time.time() - time_start:.2f} seconds")
    return trails


# =================== Guess-and-Determine ===================
def guess_and_determine_attack(*args, **kwargs):
    """Guess-and-determine pipeline — timing wrapper over guess_and_determine.search_guess_basis."""
    t0 = time.time()
    result = gd.search_guess_basis(*args, **kwargs)
    print(f"--- Total Time ---: {time.time() - t0:.2f} seconds")
    return result
