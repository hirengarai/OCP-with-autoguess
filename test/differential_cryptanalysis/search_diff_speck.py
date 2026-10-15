"""Demo: search for the best differential trail of round-reduced SPECK32.

Run:  python test/differential_cryptanalysis/search_diff_speck.py
Edit ROUNDS / MODEL below to change the experiment.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # make the repo root importable

import attacks.attacks as attacks
from primitives.speck import SPECK_PERMUTATION

ROUNDS = 4       # number of rounds to attack
MODEL = "sat"    # "sat" or "milp"

# 1. Describe the cipher.
cipher = SPECK_PERMUTATION(r=ROUNDS, version=32)

# 2. Search: best trail, non-zero input difference.
trails = attacks.diff_attacks(
    cipher,
    goal="DIFFERENTIALPATH_PROB",     # optimise the trail probability
    constraints=["INPUT_NOT_ZERO"],   # forbid the trivial all-zero difference
    objective_target="OPTIMAL",       # "EXISTENCE" / "AT MOST 9" are also allowed
    show_mode=1,                      # print every round (2 = every layer)
    config_model={"model_type": MODEL},
)

# 3. Report. The trail is also saved under files/.
weight = trails[0].data["diff_weight"]
print(f"\nBest {ROUNDS}-round trail: weight {weight}, i.e. probability 2^-{weight}")
print(f"Per-round weights: {trails[0].data['rounds_diff_weight']}")
