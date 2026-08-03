"""
Test Autoguess on SKINNY-64-128 (TK2)
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import primitives.skinny as skinny
from attacks import attacks


def test_gd_skinny_tk2_zc():
    # Build 20 round SKINNY-64-128 cipher (TK2 version)
    nbr_rounds = 20
    cipher_name = "SKINNY_TK2"
    skinny_version = [64, 128]


    # Build cipher
    cipher = skinny.SKINNY_BLOCKCIPHER(nbr_rounds, skinny_version)

    KS = cipher.functions["KEY_SCHEDULE"]
    target_specs = {
        16: [32+5],
        17: [32+0, 32+6],
        18: [32+1, 32+3, 32+4, 32+7],
        19: [32+0, 32+1, 32+3, 32+4, 32+5, 32+7],
        20: [32+0, 32+1, 32+3, 32+4, 32+5, 32+6, 32+7],
    }


    target_vars = [
        KS.vars[r][3][i].ID
        for r, idxs in target_specs.items()
        for i in idxs
    ]

    # Run attack
    result = attacks.guess_and_determine_attack(
        KS,
        target_vars=target_vars,
        objective_target="AT MOST 19",
        show_mode=1,
        config_model={
            "model_type": "sat",
            "name_prefix": cipher_name,
            "skip_rounds": list(range(1, 16)) + [21],
            "maxsteps": 12,
        },
    )

    print(f"[TEST] Guess basis ({len(result['guessed_variables'])}): "
          f"{[v.ID for v in result['guessed_variables']]}")
    return result


if __name__ == '__main__':

    test_gd_skinny_tk2_zc()
