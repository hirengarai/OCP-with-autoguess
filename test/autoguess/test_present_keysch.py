import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # two levels up from test/autoguess/
sys.path.insert(0, str(ROOT))

FILES_DIR = ROOT / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)

import primitives.present as present
from variables.variables import Variable
from attacks.autoguess import genAutoGuessRelationsForFunction, solve

# --- build the cipher ---
nbr_rounds   = 27
cipher_name  = "present_keysch"

inp  = [Variable(1, ID=f"in{i}")  for i in range(64)]
outp = [Variable(1, ID=f"out{i}") for i in range(64)]
key_var = [Variable(1, ID=f"key{i}") for i in range(80)]

cipher = present.PRESENT_block_cipher(cipher_name,[64,80], inp, key_var, outp,nbr_rounds=nbr_rounds)

KS = cipher.functions["KEY_SCHEDULE"]


# --- known variables ---
def ridx(r_paper):   # paper k_r,·  → code round index
    return r_paper + 1   # if your model is 1-based; change to `return r_paper` if not


known_pairs = []

# k0,16~47
known_pairs += [(ridx(0), j) for j in range(16, 48)]

# k1,20~27 and k1,36~43
known_pairs += [(ridx(1), j) for j in range(20, 28)]
known_pairs += [(ridx(1), j) for j in range(36, 44)]

# k25,{0,2,8,10,16,18,24,26,32,34,40,42,48,50,56,58}
k25_list = [0,2,8,10,16,18,24,26,32,34,40,42,48,50,56,58]
known_pairs += [(ridx(25), j) for j in k25_list]

# k26,2*i  for i = 0..31   (i.e., even indices 0..62)
known_pairs += [(ridx(26), 2*i) for i in range(32)]

# # Build the final known list (IDs)
known_vars = [KS.vars[r][0][j].ID for (r, j) in known_pairs]

# Generate relations
outfile = FILES_DIR / f"{cipher_name}_relations_{nbr_rounds}r.txt"

genAutoGuessRelationsForFunction(
    KS,
    filename= str(outfile),
    target_vars=known_vars,
    flat_sbox_mode= False,
    algebraic=True,
    clean_layers= True
    
)

solve(str(outfile), solver="cp", preprocess=1, D=2, maxguess=60, maxsteps = 10)
