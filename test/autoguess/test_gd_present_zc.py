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


def test_gd_present_zc():
    # Build PRESENT cipher
    nbr_rounds = 27
    cipher_name = "PRESENT"
    present_version = [64,80]


    cipher = present.PRESENT_BLOCKCIPHER(nbr_rounds, version=present_version)

    KS = cipher.functions["KEY_SCHEDULE"]

    # Define known variables (input + output state)
    def ridx(r_paper):   # paper k_r,·  → code round index
        return r_paper + 1   # if your model is 1-based; change to `return r_paper` if not

    target = []

    # k0,16~47
    target += [(ridx(0), j) for j in range(16, 48)]

    # k1,20~27 and k1,36~43
    target += [(ridx(1), j) for j in range(20, 28)]
    target += [(ridx(1), j) for j in range(36, 44)]

    # k25,{0,2,8,10,16,18,24,26,32,34,40,42,48,50,56,58}
    k25_list = [0,2,8,10,16,18,24,26,32,34,40,42,48,50,56,58]
    target += [(ridx(25), j) for j in k25_list]

    # k26,2*i  for i = 0..31   (i.e., even indices 0..62)
    target += [(ridx(26), 2*i) for i in range(32)]

    # # Build the final known list (IDs)
    target_vars = [KS.vars[r][0][j].ID for (r, j) in target]

    # Run attack
    result = attacks.guess_and_determine_attack(
        KS,
        target_vars=target_vars,
        objective_target="AT MOST 60",
        show_mode=1,
        config_model={
            "model_type": "sat",
            "name_prefix": cipher_name,
            "sbox_form": "implication",
            "algebraic_layers": ["PermutationLayer"],
            "maxsteps": 10,
        },
        config_solver={"preprocess": 1},
    )

    print(f"[TEST] Guess basis ({len(result['guessed_variables'])}): "
          f"{[v.ID for v in result['guessed_variables']]}")
    return result


if __name__ == '__main__':

    test_gd_present_zc()
