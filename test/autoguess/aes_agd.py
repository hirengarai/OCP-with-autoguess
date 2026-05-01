"""
Test automatic guess and determine on 2 round AES
"""
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# import variables.variables as var
import primitives.aes as aes
from attacks import attacks
from attacks.guess_and_determine import RelGenConfig, SolverConfig


nbr_rounds = 2
cipher_name = "AES"
aes_version = [128, 128]

cipher = aes.AES_BLOCKCIPHER(nbr_rounds, aes_version)

# Define known variables (input + output state)
func = cipher.functions["PERMUTATION"]

known_vars = [v.ID for v in func.vars[1][0]] + \
             [v.ID for v in func.vars[func.nbr_rounds][1]]

# Run attack
result = attacks.guess_and_determine_attack(
    cipher,
    name_prefix=cipher_name,
    known_vars=known_vars,
    relgen_cfg=RelGenConfig(skip_rounds=[2]),
    solver_cfg=SolverConfig(
        solver="sat",
        satsolver="cadical153",  # alternatives: glucose4, cadical153
        maxguess=6,
        maxsteps=14,
    ),
)
