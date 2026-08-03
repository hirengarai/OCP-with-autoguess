"""
Test automatic guess and determine on 2 round AES
"""
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# import variables.variables as var
import primitives.aes as aes
from attacks import attacks


def test_gd_aes():
    nbr_rounds = 3
    cipher_name = "AES"
    aes_version = [128, 128]

    cipher = aes.AES_BLOCKCIPHER(nbr_rounds, aes_version)

    # Define known variables (input + output state)
    func = cipher.functions["PERMUTATION"]

    known_vars = [v.ID for v in func.vars[1][0]] + \
                 [v.ID for v in func.vars[func.nbr_rounds][1]]

    # Run attack
    result = attacks.guess_and_determine_attack(
        cipher,
        known_vars=known_vars,
        objective_target="AT MOST 11",
        show_mode=1,
        config_model={
            "model_type": "sat",
            "name_prefix": cipher_name,
            "skip_rounds": [3],
            "maxsteps": 20,
        },
        config_solver={"solver": "cadical153"},  # alternatives: glucose4, cadical153
    )

    print(f"[TEST] Guess basis ({len(result['guessed_variables'])}): "
          f"{[v.ID for v in result['guessed_variables']]}")
    return result


if __name__ == '__main__':
    test_gd_aes()
