"""
Test Autoguess on SKINNY-64-128 (TK2)
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from variables.variables import Variable
import primitives.skinny as skinny
from attacks import attacks

# Build SKINNY-64-128 cipher (TK2 version)
nbr_rounds = 20
cipher_name = "SKINNY_KEYSCH"
skinny_version = [64, 128]

inp  = [Variable(4, ID=f"in{i}")  for i in range(16)]
outp = [Variable(4, ID=f"out{i}") for i in range(16)]
key_var = [Variable(4, ID=f"key{i}") for i in range(32)]

# Build cipher
cipher = skinny.Skinny_block_cipher(cipher_name,skinny_version, inp, key_var, outp,nbr_rounds=nbr_rounds)

KS = cipher.functions["KEY_SCHEDULE"]
# Target subkeys from skinnytk2zckb (r=15..19 in 0-based paper -> r=16..20 here).
target_specs = {
    16: [5],
    17: [0, 6],
    18: [1, 3, 4, 7],
    19: [0, 1, 3, 4, 5, 7],
    20: [0, 1, 3, 4, 5, 6, 7],
}
target_vars = [
    KS.vars[r][0][i].ID
    for r, idxs in target_specs.items()
    for i in idxs
]

relationfile = f"relations_{cipher_name}_{nbr_rounds}r.txt"
outputfile = f"output_{cipher_name}_{nbr_rounds}r.txt"

# Run Autoguess
attacks.gd_attack(
    KS,
    target_vars=target_vars,
    skip_rounds=list(range(1, 16)) + [21],
    solver='sat',
    algebraic=False,
    maxguess=19,
    maxsteps=12,
    relationfile=relationfile,
    outputfile=outputfile
)