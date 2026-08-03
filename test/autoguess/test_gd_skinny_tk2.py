"""
Test automatic guess and determine on SKINNY-n-n
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import primitives.skinny as skinny
from attacks import attacks


def test_gd_skinny_tk2():
    # Build 10 round SKINNY-64-64 cipher (TK1 version)
    nbr_rounds = 11
    cipher_name = "SKINNY_TK2"
    skinny_version = [64, 128]

    # Build cipher
    cipher = skinny.SKINNY_BLOCKCIPHER(nbr_rounds, skinny_version)

    # Define known variables (input + output state)
    func = cipher.functions["PERMUTATION"]

    known_vars = [v.ID for v in func.vars[1][0]] + \
                 [v.ID for v in func.vars[func.nbr_rounds][func.nbr_layers]]


    # Run attack
    result = attacks.guess_and_determine_attack(
        cipher,
        known_vars=known_vars,
        objective_target="AT MOST 31",
        show_mode=1,
        config_model={
            "model_type": "sat",
            "name_prefix": cipher_name,
            "skip_layers": ["SboxLayer", "AddConstantLayer"],
            "algebraic_layers": ["MatrixLayer"],
            "maxsteps": 100,
        },
    )

    print(f"[TEST] Guess basis ({len(result['guessed_variables'])}): "
          f"{[v.ID for v in result['guessed_variables']]}")
    return result


if __name__ == '__main__':

    test_gd_skinny_tk2()
