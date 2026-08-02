"""The interface for differential attacks.

Provides:

1. search for differential trails
"""

from pathlib import Path
from math import log2
from attacks.attack_trace import DifferentialTrail
from tools.model_constraints import fill_functions_rounds_layers_positions, set_model_versions, gen_round_model_constraint_obj_fun, gen_predefined_constraints
import tools.model_objective as model_objective
import tools.milp_search as milp_search
import tools.sat_search as sat_search
# import visualisations.visualisations as vis

ROOT = Path(__file__).resolve().parents[1] # differential_cryptanalysis.py -> attacks -> <ROOT>
FILES_DIR = ROOT / "files"


# ---------------------- Model and Solver Configuration ----------------------
def _parse_and_set_configs(cipher, goal, objective_target, config_model, config_solver):
    """Fill in default model/solver configuration and return ``(config_model, config_solver)``."""
    # ===== Set Default config_model and config_solver =====
    config_model = config_model or {}
    config_solver = config_solver or {}

    # Set "model_type", the automated model framework, 'milp' or 'sat'
    config_model["model_type"] = config_model.get("model_type", "milp").lower()

    # Set "functions", "rounds", "layers", "positions" for modeling
    functions, rounds, layers, positions = fill_functions_rounds_layers_positions(cipher, functions=None, rounds=None, layers=None, positions=None)
    config_model.setdefault("functions", functions)
    config_model.setdefault("rounds", rounds)
    config_model.setdefault("layers", layers)
    config_model.setdefault("positions", positions)

    # Set "solver" for solving the model
    config_solver.setdefault("solver", "DEFAULT")

    FILES_DIR.mkdir(parents=True, exist_ok=True)  # ensure the output directory exists
    if config_model["model_type"] == "milp":
        # Set the model "filename".
        config_model["filename"] = str(FILES_DIR / f"{cipher.nbr_rounds}round_{cipher.name}_{goal}_{objective_target}_milp_model.lp")

    elif config_model["model_type"] == "sat":
        # Set the model "filename".
        config_model["filename"] = str(FILES_DIR / f"{cipher.nbr_rounds}round_{cipher.name}_{goal}_{objective_target}_sat_model.cnf")

    # Set solution_number to a large value if not defined when searching for differentials
    if goal == "DIFFERENTIAL_PROB":
        config_solver.setdefault("solution_number", 1000000)

    return config_model, config_solver


def configure_model_version(cipher, goal, config_model):
    """Assign each operator its ``model_version`` for the given differential goal.

    A base version is set on all operators, and a per-goal S-box version on the
    ``Sbox`` and ``AESround`` operators. An optional ``config_model["model_version"]``
    entry (``{"model_version": ..., "operator_name": ...}``) overrides the version
    for a specific operator.
    """
    functions, rounds, layers, positions = config_model.get("functions"), config_model.get("rounds"), config_model.get("layers"), config_model.get("positions")

    if goal == 'DIFFERENTIAL_SBOXCOUNT':
        set_model_versions(cipher, "XORDIFF", functions, rounds, layers, positions) # Set model_version = "XORDIFF" for all operators
        set_model_versions(cipher, "XORDIFF_A", functions, rounds, layers, positions, operator_name="Sbox") # Set model_version = "XORDIFF_A" for all Sbox operators
        set_model_versions(cipher, "XORDIFF_A", functions, rounds, layers, positions, operator_name="AESround") # Preserve S-box active-count semantics inside AESround

    elif goal == 'DIFFERENTIALPATH_PROB' or  goal == "DIFFERENTIAL_PROB":
        set_model_versions(cipher, "XORDIFF", functions, rounds, layers, positions) # Set model_version = "XORDIFF" for all operators
        set_model_versions(cipher, "XORDIFF_PR", functions, rounds, layers, positions, operator_name="Sbox") # Set model_version = "XORDIFF_PR" for all Sbox operators
        set_model_versions(cipher, "XORDIFF_PR", functions, rounds, layers, positions, operator_name="AESround") # Preserve S-box probability semantics inside AESround

    elif goal == "TRUNCATEDDIFF_SBOXCOUNT":
        set_model_versions(cipher, "TRUNCATEDDIFF", functions, rounds, layers, positions) # Set model_version = "TRUNCATEDDIFF" for all operators
        set_model_versions(cipher, "TRUNCATEDDIFF_A", functions, rounds, layers, positions, operator_name="Sbox") # Set model_version = "TRUNCATEDDIFF_A" for all Sbox operators
        set_model_versions(cipher, "TRUNCATEDDIFF_A", functions, rounds, layers, positions, operator_name="AESround") # Preserve S-box active-count semantics inside AESround

    else:
        raise ValueError(f"Invalid goal: {goal}.")

    mv = config_model.get("model_version")  # optional per-operator override
    if mv and mv.get("model_version") and mv.get("operator_name"):
        set_model_versions(cipher, mv["model_version"], functions, rounds, layers, positions,
                           operator_name=mv.get("operator_name"))


# -------------------- Predefined Additional Constraints --------------------
def _expand_var_ids(var, bitwise=False):
    """Return the variable's ID, expanded to per-bit IDs when ``bitwise`` and the width > 1."""
    if bitwise and var.bitsize > 1:
        return [f"{var.ID}_{i}" for i in range(var.bitsize)]
    return [var.ID]

def _gen_input_non_zero_constraints(cipher, goal, config_model):
    """Return constraints forcing the input difference to be non-zero (at least one active bit/word)."""
    cons_vars = [var for cons in cipher.inputs_constraints for var in cons.input_vars]
    model_type = config_model.get("model_type", "milp").lower()
    encoding = config_model.get("atleast_encoding_sat", "SEQUENTIAL") if model_type == "sat" else None
    bitwise = "TRUNCATEDDIFF" not in goal
    constraints = gen_predefined_constraints(
        model_type=model_type,
        cons_type="SUM_AT_LEAST",
        cons_vars=cons_vars,
        cons_value=1,
        bitwise=bitwise,
        encoding=encoding,
    )
    # MILP-specific: declare decision variables as binary
    if model_type == "milp":
        binary_vars = []
        for var in cons_vars:
            binary_vars += (_expand_var_ids(var, bitwise=bitwise))
        if binary_vars:
            constraints.append("Binary\n" + " ".join(binary_vars))
    return constraints


def _gen_fixed_input_output_constraints(in_out, fix_diff, cipher, config_model):
    """Return constraints fixing the input or output difference to ``fix_diff``."""
    cons_vars = []
    if in_out == "input":
        if not (hasattr(cipher, "inputs") and isinstance(cipher.inputs, dict)):
            raise ValueError("Cipher 'inputs' attribute is missing or not a dict.")
        for input_name in cipher.inputs.keys():
            cons_vars += cipher.inputs[input_name]
    elif in_out == "output":
        if not (hasattr(cipher, "outputs") and isinstance(cipher.outputs, dict)):
            raise ValueError("Cipher 'outputs' attribute is missing or not a dict.")
        for output_name in cipher.outputs.keys():
            cons_vars += cipher.outputs[output_name]
    else:
        raise ValueError(f"Invalid in_out: {in_out}. Expected 'input' or 'output'.")
    n = len(cons_vars) * cons_vars[0].bitsize
    s = fix_diff.strip().lower()
    if s.startswith("0b"):
        diff = s[2:].zfill(n)
    elif s.startswith("0x"):
        diff = bin(int(s, 16))[2:].zfill(n)
    else:
        raise ValueError(f"Invalid fix_diff format: {fix_diff}. Expected binary (0b...) or hexadecimal (0x...) string.")
    if len(diff) > n:
        raise ValueError(f"fix_diff {fix_diff} has {len(diff)} bits but the {in_out} state has only {n}.")

    model_type = config_model.get("model_type", "milp").lower()
    constraints = []
    if cons_vars[0].bitsize == 1:
        for i in range(len(cons_vars)):
            if model_type == "sat":
                if diff[i] == '1':
                    constraints.append(f"{cons_vars[i].ID}")
                elif diff[i] == '0':
                    constraints.append(f"-{cons_vars[i].ID}")
            elif model_type == "milp":
                constraints.append(f"{cons_vars[i].ID} = {diff[i]}")
                constraints.append("Binary\n" + f"{cons_vars[i].ID}")
        return constraints
    for i in range(len(cons_vars)):
        for j in range(cons_vars[i].bitsize):
            if model_type == "sat":
                if diff[i*cons_vars[i].bitsize+j] == '1':
                    constraints.append(f"{cons_vars[i].ID}_{j}")
                elif diff[i*cons_vars[i].bitsize+j] == '0':
                    constraints.append(f"-{cons_vars[i].ID}_{j}")
            elif model_type == "milp":
                constraints.append(f"{cons_vars[i].ID}_{j} = {diff[i*cons_vars[i].bitsize+j]}")
                constraints.append("Binary\n" + f"{cons_vars[i].ID}_{j}")
    return constraints


# ------------------------ Differential Trail Search -------------------------
def search_diff_trail(cipher, goal="DIFFERENTIALPATH_PROB", constraints=None,
                      objective_target="OPTIMAL", show_mode=0, config_model=None,
                      config_solver=None):
    """Search for differential trails of the specified cipher.

    Args:
        cipher: The cipher object to analyze.
        goal (str): Cryptanalysis goal, one of ``"DIFFERENTIAL_SBOXCOUNT"``,
            ``"DIFFERENTIALPATH_PROB"``, ``"DIFFERENTIAL_PROB"``,
            ``"TRUNCATEDDIFF_SBOXCOUNT"``.
        constraints (list, optional): Extra model constraints. ``["INPUT_NOT_ZERO"]``
            (the default) auto-adds an input-non-zero constraint; entries may also be
            explicit variable constraints (e.g. ``"v_1_0_0 = 1"`` for MILP,
            ``"v_1_0_0"`` / ``"-v_2_1_0"`` for SAT) or any user-defined constraint.
        objective_target (str): The target for the objective function, which can be:
            - 'OPTIMAL': Find the optimal solution.
            - 'AT MOST X': Find a solution with an objective value at most X.
            - 'EXACTLY X': Find a solution with an objective value exactly X.
            - 'AT LEAST X': Find a solution with an objective value at least X.
            - 'EXISTENCE': Find any feasible solution.
        show_mode (int): Result-printing detail level (0-3).
        config_model (dict, optional): Advanced modeling options; see
            ``_parse_and_set_configs``.
        config_solver (dict, optional): Advanced solver options; see
            ``_parse_and_set_configs``.

    Returns:
        list: The differential trail objects found.
    """
    if constraints is None:
        constraints = ["INPUT_NOT_ZERO"]

    if not any(goal.startswith(prefix) for prefix in ("DIFFERENTIAL_SBOXCOUNT", "DIFFERENTIALPATH_PROB", "DIFFERENTIAL_PROB", "TRUNCATEDDIFF_SBOXCOUNT")):
        raise ValueError(f"Invalid goal: {goal}. Expected one of ['DIFFERENTIAL_SBOXCOUNT', 'DIFFERENTIALPATH_PROB', 'DIFFERENTIAL_PROB', 'TRUNCATEDDIFF_SBOXCOUNT'].")
    if not isinstance(constraints, list):
        raise ValueError(f"Invalid constraints: {constraints}. Expected a list of strings.")
    if not any(objective_target.startswith(prefix) for prefix in ("OPTIMAL", "AT MOST", "EXACTLY", "AT LEAST", "EXISTENCE")):
        raise ValueError(f"Invalid objective_target: {objective_target}. Expected one of ['OPTIMAL', 'AT MOST X', 'EXACTLY X', 'AT LEAST X', 'EXISTENCE'].")
    if goal == "DIFFERENTIAL_PROB" and objective_target != "EXISTENCE":
        print(f"[WARNING] goal='DIFFERENTIAL_PROB' supports only objective_target='EXISTENCE'; "
              f"overriding '{objective_target}' -> 'EXISTENCE'.")
        objective_target = "EXISTENCE"
    if show_mode not in (0, 1, 2, 3):
        raise ValueError(f"Invalid show_mode: {show_mode}. Expected one of [0, 1, 2, 3].")
    if not (isinstance(config_model, dict) or config_model is None):
        raise ValueError(f"Invalid config_model: {config_model}. Expected a dictionary or None.")
    if not (isinstance(config_solver, dict) or config_solver is None):
        raise ValueError(f"Invalid config_solver: {config_solver}. Expected a dictionary or None.")

    # Step 1. Parse and set model and solver configurations.
    config_model, config_solver = _parse_and_set_configs(cipher, goal, objective_target, config_model, config_solver)
    model_type = config_model.get("model_type", "milp")

    # Step 2. Generate round constraints and objective function for the cipher.
    configure_model_version(cipher, goal, config_model)
    round_constraints, obj_fun = gen_round_model_constraint_obj_fun(cipher, model_type, config_model)

    # Step 3. Process additional constraints.
    model_cons = []
    for cons in constraints:
        if cons == "INPUT_NOT_ZERO":  # Deal with specific additional constraints.
            model_cons += _gen_input_non_zero_constraints(cipher, goal, config_model)
        else:
            model_cons += [cons]
    model_cons += round_constraints

    # For the goal of searching for differentials, fix the input and output differences
    if goal == "DIFFERENTIAL_PROB":
        input_diff = config_model.get("input_diff", None)
        output_diff = config_model.get("output_diff", None)
        if input_diff is None and output_diff is None:
            raise ValueError("For goal='DIFFERENTIAL_PROB', either input_diff or output_diff must be specified in config_model.")
        if input_diff is not None:
            model_cons += _gen_fixed_input_output_constraints("input", input_diff, cipher, config_model)
        if output_diff is not None:
            model_cons += _gen_fixed_input_output_constraints("output", output_diff, cipher, config_model)

    # Step 4: Modeling and Solving.
    if model_type == "milp":
        solutions = milp_search.modeling_solving_milp(objective_target, model_cons, obj_fun, config_model, config_solver)

    elif model_type == "sat":
        if goal in ["DIFFERENTIALPATH_PROB", "DIFFERENTIAL_PROB"] and model_objective.has_Sbox_with_decimal_weights(cipher, goal):
            config_model["decimal_objective_function"] = {}
            Sbox = model_objective.detect_Sbox(cipher)
            config_model["decimal_objective_function"]["Sbox"] = Sbox
            config_model["decimal_objective_function"]["table"] = Sbox.computeDDT()

        solutions = sat_search.modeling_solving_sat(objective_target, model_cons, obj_fun, config_model, config_solver)

    else:
        raise ValueError(f"Invalid model_type: {model_type}. Expected one of ['milp', 'sat'].")

    # Step 5: Build the trails from the solutions, then print and save them.
    if isinstance(solutions, list):
        return _extract_and_save_diff_trails(cipher, goal, config_model, config_solver, show_mode, solutions)

    raise ValueError("No valid solutions found.")


# -------------------- Trail Extraction and Visualization --------------------
def _add_index(path, i):
    """Insert ``_i`` before the file extension: ``a/b_trail.json`` -> ``a/b_trail_i.json``."""
    p = Path(path)
    return str(p.with_name(f"{p.stem}_{i}{p.suffix}"))


def _persist_trail(trail, show_mode):
    """Print and save a single trail."""
    trail.print_trail(show_mode=show_mode)
    trail.save_json()
    trail.save_txt(show_mode=show_mode)


def _extract_and_save_diff_trails(cipher, goal, config_model, config_solver, show_mode, solutions):
    """Build each distinct trail and immediately print/save it; return the deduplicated list."""
    trails = []
    trail_structs = []
    for i, sol in enumerate(solutions):
        trail_struct = _extract_trail_structures(cipher, goal, sol)
        if trail_struct in trail_structs:
            continue
        trail_structs.append(trail_struct)
        data = {"cipher": f"{cipher.nbr_rounds}_round_{cipher.name}",
                "functions": config_model["functions"],
                "rounds": config_model["rounds"],
                "config_model": config_model,
                "config_solver": config_solver,
                "trail_struct": trail_struct,
                "diff_weight": sol.get("obj_fun_value"),
                "rounds_diff_weight": sol.get("rounds_obj_fun_values")}
        trail = DifferentialTrail(data, solution_trace=sol)
        if i > 0:
            print(f"[INFO] Saving trail #{i+1}.")
            trail.json_filename = _add_index(trail.json_filename, i)
            trail.txt_filename = _add_index(trail.txt_filename, i)
        _persist_trail(trail, show_mode)
        trails.append(trail)
    if trails and goal == "DIFFERENTIAL_PROB":
        pr = sum(2 ** (-t.data['diff_weight']) for t in trails if t.data['diff_weight'] is not None)
        print(f"[INFO] Total probability of all {len(trails)} found trails: 2^{log2(pr) if pr > 0 else 'undefined'}")
    return trails

def _extract_trail_structures(cipher, goal, solution):
    """Extract a structured differential trail (``trail_struct``) from a solver assignment.

    Returns:
        dict: A nested structure with keys ``bitwise``, ``inputs``, ``outputs``, and
        ``functions`` (each function maps to ``rounds``, ``nbr_words``,
        ``nbr_temp_words``, and one entry per round mapping a layer index to a list
        of per-variable nodes).
    """
    bitwise = "TRUNCATEDDIFF" not in goal

    def _get_solution_bit(var_id): # Map a variable id to '0'/'1'/'-'.
        v = solution.get(var_id, None)
        if v is None:
            return "-"
        try: # robust handling for bool/int/float
            return "1" if int(round(v)) == 1 else "0"
        except Exception:
            return "-"

    def node(var):
        """Build a per-variable node."""
        ids = _expand_var_ids(var, bitwise=bitwise)
        bits = "".join(_get_solution_bit(v_id) for v_id in ids)
        return {
            "var_ID": getattr(var, "ID", str(var)), # ID of var
            "variables": ids, # List of extended word/bit variables from the given var
            "bin_values": bits, # Binary string value
            }

    # ------------------------------ Build trail_struct ------------------------------
    trail_struct = {
        "bitwise": bitwise,
        "inputs": {},
        "outputs": {},
        "functions": {}
    }

    # ------------------------------ Inputs / Outputs ------------------------------
    # Prefer cipher.inputs/cipher.outputs if present; otherwise fall back to constraints.
    if hasattr(cipher, "inputs") and isinstance(cipher.inputs, dict):
        for name, var_list in cipher.inputs.items():
            trail_struct["inputs"][name] = [node(v) for v in var_list]
    if hasattr(cipher, "outputs") and isinstance(cipher.outputs, dict):
        for name, var_list in cipher.outputs.items():
            trail_struct["outputs"][name] = [node(v) for v in var_list]

    # ------------------------------ Functions / Rounds / Layers ------------------------------
    for fun in cipher.functions:
        fun_store = {
        "rounds": list(range(1, cipher.functions[fun].nbr_rounds + 1)),
        "nbr_words": cipher.functions[fun].nbr_words if hasattr(cipher.functions[fun], "nbr_words") else None,
        "nbr_temp_words": cipher.functions[fun].nbr_temp_words if hasattr(cipher.functions[fun], "nbr_temp_words") else None
        }
        for r in range(1, cipher.functions[fun].nbr_rounds + 1):
            round_store = {}
            for l in range(cipher.functions[fun].nbr_layers + 1):
                layer_nodes = [node(v) for v in cipher.functions[fun].vars[r][l]]
                round_store[l] = layer_nodes
            fun_store[r] = round_store
        trail_struct["functions"][fun] = fun_store
    return trail_struct
