"""
Test Autoguess on SKINNY-64-128 (TK2)
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import primitives.skinny as skinny
from attacks import attacks
from attacks.guess_and_determine import RelGenConfig, SolverConfig

# Build 20 round SKINNY-64-128 cipher (TK2 version)
nbr_rounds = 20
cipher_name = "SKINNY_TK2"
skinny_version = [64, 128]


# Build cipher
cipher = skinny.SKINNY_BLOCKCIPHER(nbr_rounds, skinny_version)

KS = cipher.functions["KEY_SCHEDULE"]
target_specs = {
    16: [32+5],
    17: [32+0, 32+6],
    18: [32+1, 32+3, 32+4, 32+7],
    19: [32+0, 32+1, 32+3, 32+4, 32+5, 32+7],
    20: [32+0, 32+1, 32+3, 32+4, 32+5, 32+6, 32+7],
}


target_vars = [
    KS.vars[r][3][i].ID
    for r, idxs in target_specs.items()
    for i in idxs
]

# Run attack
result = attacks.guess_and_determine_attack(
    KS,
    name_prefix=cipher_name,
    target_vars=target_vars,
    relgen_cfg=RelGenConfig(skip_rounds=list(range(1, 16)) + [21]),
    solver_cfg=SolverConfig(solver="sat", maxguess=19, maxsteps=12),
)
