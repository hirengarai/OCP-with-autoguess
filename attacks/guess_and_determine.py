"""
Guess-and-Determine using Autoguess Solver

Provides access to the Autoguess solver for finding minimal guess bases.

Usage:
    from attacks.guess_and_determine import run_autoguess

    result = run_autoguess(
        cipher,
        known_vars=['vs_1_0_0', ...],
        target_vars=['vs_3_4_0', ...],
        solver='sat',
        maxguess=20
    )

    print(f"Guess basis size: {result.num_guesses}")
"""

from tools.ocp_autoguess import AutoguessModel, run_autoguess

__all__ = ['run_autoguess', 'AutoguessModel']
