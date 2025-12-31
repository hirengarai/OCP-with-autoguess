"""
Test Autoguess on PRESENT Key Schedule
"""
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# import variables.variables as var
from variables.variables import Variable
import primitives.present as present
from attacks import attacks


# Build PRESENT cipher
nbr_rounds = 27
cipher_name = "PRESENT_KEYSCH"
present_version = [64,80]

inp  = [Variable(1, ID=f"in{i}")  for i in range(64)]
outp = [Variable(1, ID=f"out{i}") for i in range(64)]
key_var = [Variable(1, ID=f"key{i}") for i in range(80)]

cipher = present.PRESENT_block_cipher(cipher_name,present_version, inp, key_var, outp,nbr_rounds=nbr_rounds)

KS = cipher.functions["KEY_SCHEDULE"]


# Define known variables (input + output state)
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

relationfile = f"relations_{cipher_name}_{nbr_rounds}r.txt"
outputfile = f"output_{cipher_name}_{nbr_rounds}r.txt"

# Run Autoguess
result = attacks.gd_attack(
    KS,
    target_vars=known_vars,
    solver='cp',
    preprocess = 1,
    flat_sbox_mode = False,
    maxguess=60,
    maxsteps=10,
    relationfile=relationfile,
    outputfile=outputfile
)
