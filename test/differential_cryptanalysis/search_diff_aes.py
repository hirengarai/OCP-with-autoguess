"""Demo: minimum number of active S-boxes in a differential trail of round-reduced AES.

Run:  python test/differential_cryptanalysis/search_diff_aes.py
Edit ROUNDS below to change the experiment.

For an S-box cipher the standard result is the *truncated* one: how few S-boxes
can an attacker keep active? Each active AES S-box costs at most 2^-6, so
4 rounds x 25 active S-boxes bounds any 4-round trail by 2^-150 -- this is the
wide-trail argument, reproduced here automatically.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # make the repo root importable

import attacks.attacks as attacks
from primitives.aes import AES_PERMUTATION

ROUNDS = 4  # number of rounds to attack

# 1. Describe the cipher: SubBytes / ShiftRows / MixColumns, 16 bytes of state.
cipher = AES_PERMUTATION(r=ROUNDS)

# 2. Search. TRUNCATEDDIFF_SBOXCOUNT works byte-wise: each byte is just
#    "active" or "inactive", and the objective counts the active S-boxes.
#    (A bit-level goal such as DIFFERENTIALPATH_PROB needs the full DDT of the
#    8-bit S-box modelled: pre-computed under files/sbox_modeling, else built with
#    PyEDA/Espresso. It works, but 2 rounds already take ~85 s instead of ~10 s.)
trails = attacks.diff_attacks(
    cipher,
    goal="TRUNCATEDDIFF_SBOXCOUNT",   # minimise the number of active S-boxes
    constraints=["INPUT_NOT_ZERO"],   # forbid the trivial all-zero difference
    objective_target="OPTIMAL",
    show_mode=1,                      # print every round (2 = every layer)
    config_model={"model_type": "sat"},   # "milp" also works, but needs a Gurobi licence
)

# 3. Report. Each byte of the printed pattern is 1 = active, 0 = inactive.
active = int(trails[0].data["diff_weight"])
print(f"\nMinimum active S-boxes over {ROUNDS} rounds: {active}")
print(f"Per-round counts: {trails[0].data['rounds_diff_weight']}")
print(f"=> any {ROUNDS}-round differential trail has probability at most "
      f"(2^-6)^{active} = 2^-{6 * active}")
