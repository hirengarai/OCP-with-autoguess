"""
Test Autoguess on SKINNY-64-192 (TK3) with ZC targets.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from variables.variables import Variable
import primitives.skinny as skinny
from attacks import attacks


def test_gd_skinny_tk3():
    # Build SKINNY-64-192 cipher (TK3 version)
    nbr_rounds = 23
    cipher_name = "SKINNY_TK3"
    skinny_version = [64, 192]

    inp = [Variable(4, ID=f"in{i}") for i in range(16)]
    outp = [Variable(4, ID=f"out{i}") for i in range(16)]
    # 64-bit block -> 4-bit words; 192-bit key -> 48 words of 4 bits.
    key_var = [Variable(4, ID=f"key{i}") for i in range(48)]

    # Build cipher
    cipher = skinny.Skinny_block_cipher(cipher_name,skinny_version, inp, key_var, outp,nbr_rounds=nbr_rounds)

    SK = cipher.functions["KEY_SCHEDULE"]
    # Target subkeys from skinnytk3zckb (r=17..22 in 0-based paper -> r=18..23 here).
    target_specs = {
        18: [0],
        19: [3, 4],
        20: [2, 5, 7],
        21: [0, 1, 4, 6, 7],
        22: [0, 1, 2, 4, 5, 6, 7],
        23: [0, 1, 2, 4, 5, 6, 7],
    }
    target_vars = [
        SK.vars[r][0][i].ID
        for r, idxs in target_specs.items()
        for i in idxs
    ]

    # Run Autoguess
    result = attacks.guess_and_determine_attack(
        SK,
        target_vars=target_vars,
        objective_target="AT MOST 25",
        show_mode=1,
        config_model={
            "model_type": "sat",
            "skip_rounds": list(range(1, 17)) + [24],
            "maxsteps": 12,
        },
    )

    print(f"[TEST] Guess basis ({len(result['guessed_variables'])}): "
          f"{[v.ID for v in result['guessed_variables']]}")
    return result


if __name__ == '__main__':

    test_gd_skinny_tk3()
