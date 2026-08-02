"""The interface for linear attacks.

Provides:

1. search for linear trails
"""

from pathlib import Path
from math import log2

from attacks.attack_trace import LinearTrail
from tools.model_constraints import fill_functions_rounds_layers_positions, set_model_versions, gen_round_model_constraint_obj_fun, gen_predefined_constraints
import tools.model_objective as model_objective
import tools.milp_search as milp_search
import tools.sat_search as sat_search
# import visualisations.visualisations as vis

ROOT = Path(__file__).resolve().parents[1] # linear_cryptanalysis.py -> attacks -> <ROOT>
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

    FILES_DIR.mkdir(parents=True, exist_ok=True)
    if config_model["model_type"] == "milp":
        # Set the model "filename".
        config_model["filename"] = str(FILES_DIR / f"{cipher.nbr_rounds}round_{cipher.name}_{goal}_{objective_target}_milp_model.lp")

    elif config_model["model_type"] == "sat":
        # Set the model "filename".
        config_model["filename"] = str(FILES_DIR / f"{cipher.nbr_rounds}round_{cipher.name}_{goal}_{objective_target}_sat_model.cnf")

    # Set solution_number to a large value if not defined when searching for linear hull
    if goal == "LINEARHULL_CORR":
        config_solver.setdefault("solution_number", 1000000)

    return config_model, config_solver

def configure_model_version(cipher, goal, config_model):
    """Assign each operator its ``model_version`` for the given linear goal.

    A base version is set on all operators, and a per-goal S-box version on the
    ``Sbox`` and ``AESround`` operators. An optional ``config_model["model_version"]``
    entry (``{"model_version": ..., "operator_name": ...}``) overrides the version
    for a specific operator.
    """
    functions, rounds, layers, positions = config_model.get("functions"), config_model.get("rounds"), config_model.get("layers"), config_model.get("positions")

    if goal == 'LINEAR_SBOXCOUNT':
        set_model_versions(cipher, "LINEAR", functions, rounds, layers, positions) # Set model_version = "LINEAR" for all operators
        set_model_versions(cipher, "LINEAR_A", functions, rounds, layers, positions, operator_name="Sbox") # Set model_version = "LINEAR_A" for all Sbox operators
        set_model_versions(cipher, "LINEAR_A", functions, rounds, layers, positions, operator_name="AESround") # Preserve S-box active-count semantics inside AESround

    elif goal == 'LINEARPATH_CORR' or goal == "LINEARHULL_CORR":
        set_model_versions(cipher, "LINEAR", functions, rounds, layers, positions) # Set model_version = "LINEAR" for all operators
        set_model_versions(cipher, "LINEAR_PR", functions, rounds, layers, positions, operator_name="Sbox") # Set model_version = "LINEAR_PR" for all Sbox operators
        set_model_versions(cipher, "LINEAR_PR", functions, rounds, layers, positions, operator_name="AESround") # Preserve S-box correlation semantics inside AESround

    elif goal == "TRUNCATEDLINEAR_SBOXCOUNT":
        set_model_versions(cipher, "TRUNCATEDLINEAR", functions, rounds, layers, positions) # Set model_version = "TRUNCATEDLINEAR" for all operators
        set_model_versions(cipher, "TRUNCATEDLINEAR_A", functions, rounds, layers, positions, operator_name="Sbox") # Set model_version = "TRUNCATEDLINEAR_A" for all Sbox operators
        set_model_versions(cipher, "TRUNCATEDLINEAR_A", functions, rounds, layers, positions, operator_name="AESround") # Preserve S-box active-count semantics inside AESround

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
    """Return constraints forcing the input mask to be non-zero (at least one active bit/word)."""
    cons_vars = [var for cons in cipher.inputs_constraints for var in cons.input_vars]
    model_type = config_model.get("model_type", "milp").lower()
    encoding = config_model.get("atleast_encoding_sat", "SEQUENTIAL") if model_type == "sat" else None
    bitwise = "TRUNCATEDLINEAR" not in goal
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

def _gen_fixed_input_output_constraints(in_out, fix_mask, cipher, config_model):
    """Return constraints fixing the input or output mask to ``fix_mask``."""
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
    s = fix_mask.strip().lower()
    if s.startswith("0b"):
        mask = s[2:].zfill(n)
    elif s.startswith("0x"):
        mask = bin(int(s, 16))[2:].zfill(n)
    else:
        raise ValueError(f"Invalid fix_mask format: {fix_mask}. Expected binary (0b...) or hexadecimal (0x...) string.")
    if len(mask) > n:
        raise ValueError(f"fix_mask {fix_mask} has {len(mask)} bits but the {in_out} state has only {n}.")

    model_type = config_model.get("model_type", "milp").lower()
    constraints = []
    if cons_vars[0].bitsize == 1:
        for i in range(len(cons_vars)):
            if model_type == "sat":
                if mask[i] == '1':
                    constraints.append(f"{cons_vars[i].ID}")
                elif mask[i] == '0':
                    constraints.append(f"-{cons_vars[i].ID}")
            elif model_type == "milp":
                constraints.append(f"{cons_vars[i].ID} = {mask[i]}")
                constraints.append("Binary\n" + f"{cons_vars[i].ID}")
        return constraints
    for i in range(len(cons_vars)):
        for j in range(cons_vars[i].bitsize):
            if model_type == "sat":
                if mask[i*cons_vars[i].bitsize+j] == '1':
                    constraints.append(f"{cons_vars[i].ID}_{j}")
                elif mask[i*cons_vars[i].bitsize+j] == '0':
                    constraints.append(f"-{cons_vars[i].ID}_{j}")
            elif model_type == "milp":
                constraints.append(f"{cons_vars[i].ID}_{j} = {mask[i*cons_vars[i].bitsize+j]}")
                constraints.append("Binary\n" + f"{cons_vars[i].ID}_{j}")
    return constraints


# ------------------------ Linear Trail Search -------------------------
def search_linear_trail(cipher, goal="LINEARPATH_CORR", constraints=None,
                        objective_target="OPTIMAL", show_mode=0, config_model=None,
                        config_solver=None):
    """Search for linear trails of the specified cipher.

    Args:
        cipher: The cipher object to analyze.
        goal (str): Cryptanalysis goal, one of ``"LINEAR_SBOXCOUNT"``,
            ``"LINEARPATH_CORR"``, ``"LINEARHULL_CORR"``,
            ``"TRUNCATEDLINEAR_SBOXCOUNT"``.
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
        list: The linear trail objects found.
    """
    if constraints is None:
        constraints = ["INPUT_NOT_ZERO"]

    if not any(goal.startswith(prefix) for prefix in ("LINEAR_SBOXCOUNT", "LINEARPATH_CORR", "LINEARHULL_CORR", "TRUNCATEDLINEAR_SBOXCOUNT")):
        raise ValueError(f"Invalid goal: {goal}. Expected one of ['LINEAR_SBOXCOUNT', 'LINEARPATH_CORR', 'LINEARHULL_CORR', 'TRUNCATEDLINEAR_SBOXCOUNT'].")
    if not isinstance(constraints, list):
        raise ValueError(f"Invalid constraints: {constraints}. Expected a list of strings.")
    if not any(objective_target.startswith(prefix) for prefix in ("OPTIMAL", "AT MOST", "EXACTLY", "AT LEAST", "EXISTENCE")):
        raise ValueError(f"Invalid objective_target: {objective_target}. Expected one of ['OPTIMAL', 'AT MOST X', 'EXACTLY X', 'AT LEAST X', 'EXISTENCE'].")
    if show_mode not in (0, 1, 2, 3):
        raise ValueError(f"Invalid show_mode: {show_mode}. Expected one of [0, 1, 2, 3].")
    if not (isinstance(config_model, dict) or config_model is None):
        raise ValueError(f"Invalid config_model: {config_model}. Expected a dictionary or None.")
    if not (isinstance(config_solver, dict) or config_solver is None):
        raise ValueError(f"Invalid config_solver: {config_solver}. Expected a dictionary or None.")

    # Generate a new cipher instance with added copy layer after each operator.
    cipher.add_copy_operators()

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

    # For the goal of searching for linear hulls, fix the input and output masks
    if goal == "LINEARHULL_CORR":
        input_mask = config_model.get("input_mask", None)
        output_mask = config_model.get("output_mask", None)
        if input_mask is None and output_mask is None:
            raise ValueError("For goal='LINEARHULL_CORR', either input_mask or output_mask must be specified in config_model.")
        if input_mask is not None:
            model_cons += _gen_fixed_input_output_constraints("input", input_mask, cipher, config_model)
        if output_mask is not None:
            model_cons += _gen_fixed_input_output_constraints("output", output_mask, cipher, config_model)


    # Step 4: Modeling and Solving.
    if model_type == "milp":
        solutions = milp_search.modeling_solving_milp(objective_target, model_cons, obj_fun, config_model, config_solver)

    elif model_type == "sat":
        if goal in ["LINEARPATH_CORR", "LINEARHULL_CORR"] and model_objective.has_Sbox_with_decimal_weights(cipher, goal):
            config_model["decimal_objective_function"] = {}
            Sbox = model_objective.detect_Sbox(cipher)
            config_model["decimal_objective_function"]["Sbox"] = Sbox
            config_model["decimal_objective_function"]["table"] = Sbox.computeLAT()

        solutions = sat_search.modeling_solving_sat(objective_target, model_cons, obj_fun, config_model, config_solver)

    else:
        raise ValueError(f"Invalid model_type: {model_type}. Expected one of ['milp', 'sat'].")

    # Step 5: Build the trails from the solutions, then print and save them.
    if isinstance(solutions, list):
        return _extract_and_save_linear_trails(cipher, goal, config_model, config_solver, show_mode, solutions)

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


def _extract_and_save_linear_trails(cipher, goal, config_model, config_solver, show_mode, solutions):
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
                "linear_weight": sol.get("obj_fun_value"),
                "rounds_linear_weight": sol.get("rounds_obj_fun_values")}
        trail = LinearTrail(data, solution_trace=sol)
        if i > 0:
            print(f"[INFO] Saving trail #{i+1}.")
            trail.json_filename = _add_index(trail.json_filename, i)
            trail.txt_filename = _add_index(trail.txt_filename, i)
        _persist_trail(trail, show_mode)
        trails.append(trail)
    if trails and goal == "LINEARHULL_CORR":
        # The additive hull quantity is the expected linear potential 
        # ELP = sum c_i^2 = sum 2^(-2w) (independent-round-key assumption).
        elp = sum(2 ** (-2 * t.data['linear_weight']) for t in trails if t.data['linear_weight'] is not None)
        if elp > 0:
            print(f"[INFO] Expected linear potential (ELP) over {len(trails)} trails: 2^{log2(elp):.3f}")
    return trails

def _extract_trail_structures(cipher, goal, solution):
    """Extract a structured linear trail (``trail_struct``) from a solver assignment.

    Returns:
        dict: A nested structure with keys ``bitwise``, ``inputs``, ``outputs``, and
        ``functions`` (each function maps to ``rounds``, ``nbr_words``,
        ``nbr_temp_words``, and one entry per round mapping a layer index to a list
        of per-variable nodes).
    """
    bitwise = "TRUNCATEDLINEAR" not in goal
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
