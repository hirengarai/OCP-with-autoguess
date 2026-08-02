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

# Build 10 round SKINNY-64-128 cipher (TK2 version) 
nbr_rounds = 23
cipher_name = "SKINNY_TK3"
skinny_version = [64, 192]


# Build cipher
cipher = skinny.SKINNY_BLOCKCIPHER(nbr_rounds, skinny_version)

KS = cipher.functions["KEY_SCHEDULE"]
# Target subkeys from skinnytk2zckb (r=15..19 in 0-based paper -> r=16..20 here).
target_specs = {
    18: [48+0],
    19: [48+3, 48+4],
    20: [48+2, 48+5, 48+7],
    21: [48+0, 48+1, 48+4, 48+6, 48+7],
    22: [48+0, 48+1, 48+2, 48+4, 48+5, 48+6, 48+7],
    23: [48+0, 49, 50, 52, 53, 54, 55]
}
    

target_vars = [
    KS.vars[r][5][i].ID
    for r, idxs in target_specs.items()
    for i in idxs
]

# Run attack
result = attacks.guess_and_determine_attack(
    KS,
    target_vars=target_vars,
    objective_target="AT MOST 25",
    show_mode=1,
    config_model={
        "model_type": "cp",
        "name_prefix": cipher_name,
        "skip_rounds": list(range(1, 17)) + [24],
        "maxsteps": 12,
    },
)






# import sys
# from pathlib import Path

# ROOT_DIR = Path(__file__).resolve().parents[2]
# if str(ROOT_DIR) not in sys.path:
#     sys.path.insert(0, str(ROOT_DIR))

# import primitives.skinny as skinny
# from attacks import attacks
# from tools.relation_rename import rename_relation_file
# from tools.autoguess_wrapper import solve_autoguess

# nbr_rounds = 23
# cipher_name = "SKINNY_TK3"
# skinny_version = [64, 192]

# cipher = skinny.SKINNY_BLOCKCIPHER(nbr_rounds, skinny_version)
# KS = cipher.functions["KEY_SCHEDULE"]

# target_specs = {
#     18: [48+0],
#     19: [48+3, 48+4],
#     20: [48+2, 48+5, 48+7],
#     21: [48+0, 48+1, 48+4, 48+6, 48+7],
#     22: [48+0, 48+1, 48+2, 48+4, 48+5, 48+6, 48+7],
#     23: [48+0, 49, 50, 52, 53, 54, 55]
# }

# target_vars = [
#     KS.vars[r][5][i].ID
#     for r, idxs in target_specs.items()
#     for i in idxs
# ]

# # Step 1: Generate relations only (no solver yet)
# from tools import relation_generator
# from tools.autoguess_wrapper import _resolve_output_path

# relationfile = _resolve_output_path(f"relations_{cipher_name}_KEY_SCHEDULE_{nbr_rounds}r.txt", "autoguess")
# outputfile   = _resolve_output_path(f"output_{cipher_name}_KEY_SCHEDULE_{nbr_rounds}r.txt", "autoguess")

# relation_generator.generate_relations(
#     KS,
#     function_mode=True,
#     name_prefix=cipher_name,
#     target_vars=target_vars,
#     not_guessed_vars=["vk_22_5_53"],
#     skip_rounds=list(range(1, 17)) + [24],
#     relation_file=relationfile,
# )

# # Step 2: Rename variables in the file
# rules = {
#     "vk_*_4_*": "p_*_4_*", 
#     "vk_*_5_*": "p_*_5_*"# * matches any sequence of digits
# }
# # rename_relation_file(relationfile, rules)

# # Step 3: Run solver on renamed file
# from tools.autoguess_wrapper import solve_autoguess
# solve_autoguess(
#     inputfile=relationfile,
#     outputfile=outputfile,
#     solver='sat',
#     skip_rounds = list(range(1, 17)) + [24],
#     maxguess=25,
#     maxsteps=12,
    
# )

