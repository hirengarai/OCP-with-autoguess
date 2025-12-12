import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # two levels up from test/autoguess/
sys.path.insert(0, str(ROOT))

FILES_DIR = ROOT / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)

import primitives.aes as aes
from variables.variables import Variable
from attacks.autoguess import genAutoGuessRelations, solve

# --- build the cipher ---
nbr_rounds   = 1
cipher_name  = "aes"
aes_version = [128, 128]

# Build cipher
inp  = [Variable(8, ID=f"in{i}") for i in range(16)]
outp = [Variable(8, ID=f"out{i}") for i in range(16)]
key  = [Variable(8, ID=f"key{i}") for i in range(16)]

cipher = aes.AES_block_cipher(cipher_name, aes_version, inp, key, outp, nbr_rounds)

# Known variables
func = cipher.functions["PERMUTATION"]
known_vars = [v.ID for v in func.vars[1][0]] + [v.ID for v in func.vars[func.nbr_rounds][func.nbr_layers]]

# Generate relations
outfile = FILES_DIR / f"{cipher_name}_relations_{nbr_rounds}r.txt"

genAutoGuessRelations(
    cipher,
    filename=str(outfile),
    rename_loose=True,
    known_vars=known_vars,
    flat_sbox_mode=True,
    clean_layers= True,
    clean_key_schedule= True
)

# Solve
solve(str(outfile), solver="sat", maxguess=6, maxsteps = 14)