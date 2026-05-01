"""
Test Autoguess on AES
"""
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# import variables.variables as var
from variables.variables import Variable
import primitives.aes as aes
from attacks import attacks
from attacks.guess_and_determine import RelGenConfig, SolverConfig

# Build 1-round AES cipher
nbr_rounds = 4
cipher_name = "aes"
aes_version = [128, 128]

inp = [Variable(8, ID=f"in{i}") for i in range(16)]
outp = [Variable(8, ID=f"out{i}") for i in range(16)]
key = [Variable(8, ID=f"key{i}") for i in range(16)]

cipher = aes.AES_block_cipher(cipher_name, aes_version, inp, key, outp, nbr_rounds)

# Define known variables (input + output state)
func = cipher.functions["PERMUTATION"]

known_vars = [v.ID for v in func.vars[1][0]] + \
             [v.ID for v in func.vars[func.nbr_rounds][func.nbr_layers]]


# Run attack
attacks.guess_and_determine_attack(
    cipher,
    known_vars=known_vars,
    output_file=f"relations_{cipher_name}_{nbr_rounds}r.txt",
    relgen_cfg=RelGenConfig(skip_rounds=[4]),
    solver_cfg=SolverConfig(solver="sat", maxguess=15, maxsteps=22),
)
