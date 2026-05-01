"""
Relation Emitter - Generate dirty (uncleaned) cryptographic relations.

This module generates raw relations from cipher/function objects without any cleaning.
The relations can then be passed to relation_cleaner for simplification.

Usage:
    from relation_emitter import genRelationsForFunction, genRelations

    # For a single function
    relations = genRelationsForFunction(
        key_schedule_func,
        skip_layers=['MatrixLayer', 'AddConstantLayer'],
        skip_rounds=[3, 4],
        flat_sbox_mode=True,
        algebraic=True
    )

    # For a full cipher
    relations = genRelations(
        aes_cipher,
        skip_layers=['MatrixLayer', 'RotationLayer'],
        skip_functions=['PERMUTATION'],
        skip_rounds=[1, 2],
        flat_sbox_mode=True,
        algebraic=True
    )
"""

import inspect
from typing import Any, Dict, Iterable, List, Optional, Set


# Mapping from intuitive layer names to operator class names
LAYER_NAME_MAPPING = {
    "AddConstantLayer": {"ConstantXOR", "ConstantAdd"},
    "AddIdentityLayer": {"Equal"},
    "RotationLayer": {"Rot"},
    "ShiftLayer": {"Shift"},
    "XORLayer": {"XOR", "N_XOR"},
    "ANDLayer": {"AND"},
    "ORLayer": {"OR"},
    "NOTLayer": {"NOT"},
    "SboxLayer": {"Sbox", "AES_Sbox", "Skinny_4bit_Sbox", "Skinny_8bit_Sbox",
                  "GIFT_Sbox", "ASCON_Sbox", "TWINE_Sbox", "PRESENT_Sbox",
                  "KNOT_Sbox", "PRINCE_Sbox"},
    "MatrixLayer": {"Matrix", "GF2Linear"},
    "ModAddLayer": {"ModAdd"},
    "ModMulLayer": {"ModMul"},
    "CopyLayer": {"CopyOperator", "COPY"},
}


def _is_algebraic_line(line: str) -> bool:
    """
    Check if a line is an algebraic relation.

    A line is algebraic if it contains '+' (XOR) and no '=>' (implication).
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    return ("+" in s) and ("=>" not in s)


def _should_skip_layer(clsname: str, skip_layers: Set[str]) -> bool:
    """
    Check if an operation should be skipped based on its class name.

    Supports intuitive layer names (e.g., 'AddConstantLayer', 'RotationLayer')
    as well as direct class names (e.g., 'ConstantXOR', 'Rot').
    """
    if not skip_layers:
        return False

    for layer_name in skip_layers:
        # Check if it's a friendly layer name that needs mapping
        if layer_name in LAYER_NAME_MAPPING:
            if clsname in LAYER_NAME_MAPPING[layer_name]:
                return True
        # Otherwise treat it as a direct class name
        elif clsname == layer_name:
            return True

    return False


def _determine_algebraic_mode(
    clsname: str,
    algebraic: bool,
    fname: str,
    opid: str,
) -> bool:
    """Decide whether to request algebraic-mode output for an operation."""
    if not algebraic:
        return False

    # ConstantXOR should not be algebraic
    if clsname == "ConstantXOR":
        return False

    # Special handling for Equal in KEY_SCHEDULE
    if clsname == "Equal":
        if fname == "KEY_SCHEDULE" and opid.startswith("K_PERM_"):
            return True
        return False

    return True


def _generate_constraints_for_operation(
    op: Any,
    clsname: str,
    opid: str,
    r: int,
    l: int,
    *,
    want_alg: bool,
    flat_sbox_mode: bool,
) -> Optional[Iterable[str]]:
    """Call op.gen_autoguess_constr() with appropriate parameters."""
    gen = op.gen_autoguess_constr

    try:
        sig = inspect.signature(gen)
        supported = sig.parameters

        kwargs: Dict[str, Any] = {}

        if "flat_sbox_mode" in supported:
            kwargs["flat_sbox_mode"] = flat_sbox_mode

        if "algebraic" in supported:
            kwargs["algebraic"] = want_alg

        if "non_square_strategy" in supported:
            kwargs["non_square_strategy"] = "bidirectional"

        return gen(**kwargs)

    except Exception as e:
        return [f"# Error in {clsname} {opid} r{r}_l{l}: {e}"]


def genRelationsForFunction(
    func: Any,
    *,
    skip_layers: Optional[Iterable[str]] = None,
    skip_operations: Optional[Iterable[str]] = None,
    skip_rounds: Optional[Iterable[int]] = None,
    flat_sbox_mode: bool = True,
    algebraic: bool = True,
) -> List[str]:
    """
    Generate raw relations for a single function.

    This walks through all rounds and layers of the function, calls each
    operation's gen_autoguess_constr method, and returns the raw relations
    without any cleaning or simplification.

    Parameters
    ----------
    func : Function object
        A Function-like object from OCP with constraints[r][l] structure.

    skip_layers : iterable of str, optional
        Intuitive layer names to skip (e.g., ['AddConstantLayer', 'RotationLayer']).
        Also supports direct class names (e.g., ['ConstantXOR', 'Rot']).
        Operations of these types will be skipped.

    skip_operations : iterable of str, optional
        Operation class names to skip entirely (e.g., ['Equal', 'Rot']).
        All operations of these classes will be skipped.

    skip_rounds : iterable of int, optional
        Round numbers to skip entirely. If provided, round-to-round links
        are rebuilt to bypass skipped rounds so no variables from those
        rounds appear in the relations.

    flat_sbox_mode : bool, default=True
        If True, S-boxes emit flat (direct) constraint lines.
        If False, S-boxes may use nested representations.

    algebraic : bool, default=True
        If True, generate algebraic relations using '+' for XOR.
        If False, generate connection relations only.

    Returns
    -------
    list of str
        List of raw relation strings (connection + algebraic).
        No cleaning or simplification has been applied.

    Examples
    --------
    >>> relations = genRelationsForFunction(
    ...     key_schedule_func,
    ...     skip_layers=['MatrixLayer', 'AddConstantLayer'],
    ...     flat_sbox_mode=True,
    ...     algebraic=True
    ... )
    """
    fname = getattr(func, "name", "FUNCTION")
    nrounds = getattr(func, "nbr_rounds", 0)
    nlayers = getattr(func, "nbr_layers", -1)

    skip_layer_set: Set[str] = set(skip_layers or [])
    skip_op_set: Set[str] = set(skip_operations or [])
    skip_round_set: Set[int] = {
        r for r in (skip_rounds or []) if isinstance(r, int) and 1 <= r <= nrounds
    }

    conn: List[str] = []
    alg: List[str] = []

    # Removed verbose output for cleaner console
    # print(f"[RelationEmitter] Generating relations for function: {fname}")
    # if skip_layer_set:
    #     print(f"  Skipping layers: {sorted(skip_layer_set)}")
    # if skip_op_set:
    #     print(f"  Skipping operations: {sorted(skip_op_set)}")

    # Walk through all rounds and layers
    for r in range(1, nrounds + 1):
        if r in skip_round_set:
            continue

        for l in range(0, nlayers + 1):
            try:
                ops = func.constraints[r][l]
            except (IndexError, KeyError, AttributeError):
                continue

            # Process each operation in this layer
            for op in ops:
                clsname = op.__class__.__name__
                opid = getattr(op, "ID", "")

                # Skip if operation class is in skip list
                if clsname in skip_op_set:
                    continue

                # Skip if layer class name matches skip pattern
                if _should_skip_layer(clsname, skip_layer_set):
                    continue

                # Skip built-in round-link constraints when rebuilding links
                if skip_round_set and opid.startswith("LINK_EQ_"):
                    continue

                # Check if operation has the required method
                if not hasattr(op, "gen_autoguess_constr"):
                    # Silently skip operations without the required method
                    continue

                # Determine if this operation should use algebraic mode
                want_alg = _determine_algebraic_mode(clsname, algebraic, fname, opid)

                # Generate constraints for this operation
                constraints = _generate_constraints_for_operation(
                    op,
                    clsname,
                    opid,
                    r,
                    l,
                    want_alg=want_alg,
                    flat_sbox_mode=flat_sbox_mode,
                )

                if not constraints:
                    continue

                # Convert to list if needed
                lines = constraints if isinstance(constraints, list) else [constraints]

                # Classify each line as connection or algebraic
                for line in lines:
                    line_str = str(line).strip()
                    if not line_str:
                        continue

                    if _is_algebraic_line(line_str):
                        alg.append(line_str)
                    else:
                        conn.append(line_str)

    if skip_round_set:
        kept_rounds = [r for r in range(1, nrounds + 1) if r not in skip_round_set]
        prev_round = None
        for r in kept_rounds:
            if prev_round is None:
                prev_round = r
                continue
            try:
                in_vars = func.vars[prev_round][nlayers]
                out_vars = func.vars[r][0]
            except Exception:
                prev_round = r
                continue
            for in_var, out_var in zip(in_vars, out_vars):
                conn.append(f"{in_var.ID}, {out_var.ID}")
            prev_round = r

    total = len(conn) + len(alg)
    # Removed verbose output for cleaner console
    # print(f"[RelationEmitter] Generated {total} relations ({len(conn)} connection, {len(alg)} algebraic)")

    # Return combined list (connection first, then algebraic)
    return conn + alg


def genRelations(
    cipher: Any,
    *,
    skip_layers: Optional[Iterable[str]] = None,
    skip_operations: Optional[Iterable[str]] = None,
    skip_functions: Optional[Iterable[str]] = None,
    skip_rounds: Optional[Iterable[int]] = None,
    flat_sbox_mode: bool = True,
    algebraic: bool = True,
) -> List[str]:
    """
    Generate raw relations for an entire cipher.

    This iterates over all functions in the cipher, calls genRelationsForFunction
    for each one, and returns the combined raw relations without any cleaning.

    Parameters
    ----------
    cipher : Cipher object
        Cipher-like object with:
        - name : cipher name
        - functions : dict mapping function names to Function objects
        - optional nbr_rounds : number of rounds

    skip_layers : iterable of str, optional
        Intuitive layer names to skip (e.g., ['AddConstantLayer', 'RotationLayer']).
        Also supports direct class names (e.g., ['ConstantXOR', 'Rot']).
        Operations of these types will be skipped.

    skip_operations : iterable of str, optional
        Operation class names to skip entirely (e.g., ['Equal', 'Rot']).
        All operations of these classes will be skipped.

    skip_functions : iterable of str, optional
        Function names to skip entirely (e.g., ['KEY_SCHEDULE', 'PERMUTATION']).
        These functions will not be processed at all.

    skip_rounds : iterable of int, optional
        Round numbers to skip entirely. If provided, round-to-round links
        are rebuilt to bypass skipped rounds so no variables from those
        rounds appear in the relations.

    flat_sbox_mode : bool, default=True
        If True, S-boxes emit flat (direct) constraint lines.
        If False, S-boxes may use nested representations.

    algebraic : bool, default=True
        If True, generate algebraic relations using '+' for XOR.
        If False, generate connection relations only.

    Returns
    -------
    list of str
        List of raw relation strings from all functions.
        No cleaning or simplification has been applied.

    Examples
    --------
    >>> relations = genRelations(
    ...     aes_cipher,
    ...     skip_layers=['MatrixLayer', 'RotationLayer'],
    ...     skip_functions=['PERMUTATION'],
    ...     flat_sbox_mode=True,
    ...     algebraic=True
    ... )
    """
    skip_function_set: Set[str] = set(skip_functions or [])

    all_relations: List[str] = []

    # Removed verbose output for cleaner console
    # print(f"[RelationEmitter] Generating relations for cipher: {cipher.name}")
    # if skip_function_set:
    #     print(f"  Skipping functions: {sorted(skip_function_set)}")

    # Process each function in the cipher
    for fname, func in cipher.functions.items():
        if fname in skip_function_set:
            # Silently skip
            continue

        # Removed verbose output for cleaner console
        # print(f"\n  Processing function: {fname}")

        # Generate relations for this function
        func_relations = genRelationsForFunction(
            func,
            skip_layers=skip_layers,
            skip_operations=skip_operations,
            skip_rounds=skip_rounds,
            flat_sbox_mode=flat_sbox_mode,
            algebraic=algebraic,
        )

        all_relations.extend(func_relations)

    # Removed verbose output for cleaner console
    # total = len([r for r in all_relations if not r.strip().startswith('#')])
    # print(f"\n[RelationEmitter] Total: {total} relations across all functions")

    return all_relations
