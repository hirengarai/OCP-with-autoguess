"""
Test automatic guess and determine on SKINNY-n-n
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import primitives.skinny as skinny
from attacks import attacks
from attacks.guess_and_determine import RelGenConfig, SolverConfig

# Build 10 round SKINNY-64-64 cipher (TK1 version) 
nbr_rounds = 10
cipher_name = "SKINNY_TK1"
skinny_version = [64, 64]

# Build cipher
cipher = skinny.SKINNY_BLOCKCIPHER(nbr_rounds, skinny_version)

# Define known variables (input + output state)
func = cipher.functions["PERMUTATION"]

known_vars = [v.ID for v in func.vars[1][0]] + \
             [v.ID for v in func.vars[func.nbr_rounds][func.nbr_layers]]


# Run attack
result = attacks.guess_and_determine_attack(
    cipher,
    name_prefix=cipher_name,
    known_vars=known_vars,
    relgen_cfg=RelGenConfig(
        skip_layers=["SboxLayer", "AddConstantLayer"],
        algebraic_layers=["MatrixLayer"],
    ),
    solver_cfg=SolverConfig(solver="sat", maxguess=15, maxsteps=75),
)