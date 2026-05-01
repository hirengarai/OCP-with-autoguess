"""
Relation Emitter — walk an OCP cipher and emit raw AutoGuess relations.

Each OCP operator (XOR, Sbox, Equal, …) has a _gen_constr_autoguess() method
that returns relation strings like "a, b, c" (connection) or "a + b + c"
(algebraic). This module walks the cipher's round/layer/operator structure
and collects all those strings.

Key concepts:
  - LAYER_PATTERN_MAPPING: maps friendly names like "SboxLayer" to the
    operator classes and ID prefixes that belong to that layer type.
  - Skipping: you can skip layers, operations, rounds, or functions.
  - Algebraic mode: force specific layers to emit algebraic relations.
  - NONRENAME markers: tag Equal ops from permutations/rotations so the
    cleaner doesn't collapse them as simple renames.
  - Gap-linking: when layers or rounds are skipped, we add explicit
    rename relations to keep the variable chain connected.
"""

import inspect
from typing import Any, Dict, Iterable, List, Optional, Set

# ---------------------------------------------------------------------------
# Layer pattern mapping — maps friendly names to operator detection rules
# ---------------------------------------------------------------------------

LAYER_PATTERN_MAPPING = {
    # Layers with unique operation classes (match by class name)
    "AddConstantLayer": {"op_class": ["ConstantXOR", "ConstantAdd"]},
    "RotationLayer": {"op_class": ["Rot"]},
    "ShiftLayer": {"op_class": ["Shift"]},
    "XORLayer": {"op_class": ["XOR", "N_XOR"]},
    "ANDLayer": {"op_class": ["AND"]},
    "ORLayer": {"op_class": ["OR"]},
    "NOTLayer": {"op_class": ["NOT"]},
    "SboxLayer": {
        "op_class": [
            "Sbox",
            "AES_Sbox",
            "Skinny_4bit_Sbox",
            "Skinny_8bit_Sbox",
            "GIFT_Sbox",
            "ASCON_Sbox",
            "TWINE_Sbox",
            "PRESENT_Sbox",
            "KNOT_Sbox",
            "PRINCE_Sbox",
            "Equal",
        ],
        "id_contains": ["SB_EQ_", "SBOX_EQ_", "SBX_EQ_"],
    },
    "MatrixLayer": {"op_class": ["Matrix", "GF2Linear"]},
    "ModAddLayer": {"op_class": ["ModAdd"]},
    "ModMulLayer": {"op_class": ["ModMul"]},
    "CopyLayer": {"op_class": ["CopyOperator", "COPY"]},
    # Layers that create Equal ops (matched by ID pattern)
    "PermutationLayer": {
        "op_class": ["Equal"],
        "id_starts_with": [
            "K_P_EQ_",
            "K_PERM_EQ_",
            "K_SHIFT_EQ_",
            "Key_Perm_EQ_",
            "P_EQ_",
            "PERM_EQ_",
            "PERM1_EQ_",
            "PERM2_EQ_",
            "Perm_EQ_",
            "SR_EQ_",
            "k_PERM_EQ_",
        ],
    },
    "AddIdentityLayer": {"op_class": ["Equal"], "id_starts_with": "ID_"},
}


# ---------------------------------------------------------------------------
# Matching helpers — one function replaces three in the original
# ---------------------------------------------------------------------------


def _id_matches_pattern(opid: str, pattern: dict) -> bool:
    """Check if an operation ID matches id_starts_with or id_contains rules."""
    # Check id_contains
    contains = pattern.get("id_contains", [])
    if isinstance(contains, str):
        contains = [contains]
    if any(val in opid for val in contains):
        return True

    # Check id_starts_with
    starts = pattern.get("id_starts_with", [])
    if isinstance(starts, str):
        starts = [starts]
    if any(opid.startswith(val) for val in starts):
        return True

    return False


def _matches_filter(clsname: str, opid: str, filters: Set[str]) -> bool:
    """
    Check if an operation matches any filter.

    Filters can be:
      1. Friendly layer names (e.g. "SboxLayer") — matched via LAYER_PATTERN_MAPPING
      2. Direct class names (e.g. "XOR", "Equal")
      3. Operation ID prefixes (e.g. "K_PERM")
    """
    if not filters:
        return False

    for f in filters:
        # 1. Try as a friendly layer name
        if f in LAYER_PATTERN_MAPPING:
            pattern = LAYER_PATTERN_MAPPING[f]
            if clsname not in pattern.get("op_class", []):
                continue  # wrong class for this layer
            # If no ID rules, class match is enough
            has_id_rules = "id_contains" in pattern or "id_starts_with" in pattern
            if not has_id_rules:
                return True
            # Equal ops require ID match (to avoid matching ALL Equals)
            if clsname == "Equal":
                if _id_matches_pattern(opid, pattern):
                    return True
            else:
                return True
            continue

        # 2. Try as a direct class name
        if clsname == f:
            return True

        # 3. Try as an ID prefix
        if opid.startswith(f):
            return True

    return False


def _layer_matches_filter(ops: list, filters: Set[str]) -> bool:
    """Check if ANY operation in a layer matches a filter (for whole-layer skipping)."""
    for op in ops:
        clsname = op.__class__.__name__
        opid = getattr(op, "ID", "")
        if _matches_filter(clsname, opid, filters):
            return True
    return False


# ---------------------------------------------------------------------------
# Calling _gen_constr_autoguess with the right kwargs
# ---------------------------------------------------------------------------


def _call_gen_autoguess(
    op: Any,
    *,
    algebraic: bool,
    flat_sbox: bool,
    nonrename_perm: bool,
    nonrename_rot: bool,
    nonrename_gf2: bool,
) -> List[str]:
    """
    Call op._gen_constr_autoguess() with whatever kwargs it supports.

    Different operators accept different subsets of parameters.
    We use inspect.signature to only pass what the method accepts.
    """
    gen = op._gen_constr_autoguess
    supported = set(inspect.signature(gen).parameters.keys())

    kwargs = {}
    if "flat_sbox_mode" in supported:
        kwargs["flat_sbox_mode"] = flat_sbox
    if "algebraic_mode" in supported:
        kwargs["algebraic_mode"] = algebraic
    if "non_square_strategy" in supported:
        kwargs["non_square_strategy"] = "bidirectional"
    if "treat_as_nonrename" in supported:
        clsname = op.__class__.__name__
        if clsname == "Rot":
            kwargs["treat_as_nonrename"] = nonrename_rot
        elif clsname == "GF2Linear_Trans":
            kwargs["treat_as_nonrename"] = nonrename_gf2
        else:
            kwargs["treat_as_nonrename"] = nonrename_perm

    result = gen(**kwargs)

    # Normalize to list of strings
    if result is None:
        return []
    if isinstance(result, str):
        return [result]
    return list(result)


# ---------------------------------------------------------------------------
# Gap-linking — reconnect variables when layers/rounds are skipped
# ---------------------------------------------------------------------------


def _add_gap_links(
    func: Any,
    active_layers: Dict[int, List[int]],
    kept_rounds: List[int],
    nlayers: int,
    link_eq_skipped: bool = False,
    bridge_skipped_rounds: bool = True,
) -> List[str]:
    """
    Generate rename relations to bridge gaps from skipped layers/rounds.

    When layers or rounds are skipped, variables become disconnected.
    We fix this by adding explicit "var_a, var_b" lines linking:
      - Layer 0 to the first active layer (if layer 0 was skipped)
      - Consecutive active layers that have a gap between them
      - Last layer of round N to first layer of round N+1
    """
    links = []

    for r in kept_rounds:
        layers = active_layers.get(r, [])
        if not layers:
            continue

        # If first active layer > 0, link layer 0 vars to it
        if layers[0] > 0:
            try:
                in_vars = func.vars[r][0]
                out_vars = func.vars[r][layers[0]]
                for iv, ov in zip(in_vars, out_vars):
                    links.append(f"{iv.ID}, {ov.ID}")
            except Exception:
                pass

        # Link across gaps within the round
        for i in range(len(layers) - 1):
            prev_l = layers[i]
            next_l = layers[i + 1]
            if next_l > prev_l + 1:
                try:
                    in_vars = func.vars[r][prev_l + 1]
                    out_vars = func.vars[r][next_l]
                    for iv, ov in zip(in_vars, out_vars):
                        links.append(f"{iv.ID}, {ov.ID}")
                except Exception:
                    pass

    # Link across rounds
    for i in range(len(kept_rounds) - 1):
        prev_r = kept_rounds[i]
        next_r = kept_rounds[i + 1]
        prev_layers = active_layers.get(prev_r, [])
        next_layers = active_layers.get(next_r, [])
        if not prev_layers:
            continue

        last_layer = min(prev_layers[-1] + 1, nlayers)
        first_layer = next_layers[0] if next_layers else 0

        # Don't bridge across skipped rounds when disabled (key recovery:
        # the distinguisher guarantees a *difference* relation, not a value
        # equality, so linking values across it is wrong).
        if not bridge_skipped_rounds and (next_r - prev_r > 1):
            continue

        # Add links if: layer 0 was skipped, rounds were skipped between
        # these two, LINK_EQ ops were stripped, or next round has no
        # active layers (its layer-0 vars may be referenced by other functions)
        if (
            first_layer > 0
            or (next_r - prev_r > 1)
            or link_eq_skipped
            or not next_layers
        ):
            try:
                in_vars = func.vars[prev_r][last_layer]
                out_vars = func.vars[next_r][first_layer]
                for iv, ov in zip(in_vars, out_vars):
                    links.append(f"{iv.ID}, {ov.ID}")
            except Exception:
                continue

    return links


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def emit_function(
    func: Any,
    *,
    skip_layers: Optional[Iterable[str]] = None,
    skip_ops: Optional[Iterable[str]] = None,
    skip_rounds: Optional[Iterable[int]] = None,
    flat_sbox: bool = True,
    algebraic_layers: Optional[Iterable[str]] = None,
    nonrename_perm: bool = False,
    nonrename_rot: bool = False,
    nonrename_gf2: bool = False,
    bridge_skipped_rounds: bool = True,
) -> List[str]:
    """
    Walk one OCP function and return raw relation strings.

    Parameters
    ----------
    func : OCP Function object (Permutation, Block_cipher function, etc.)
    skip_layers : layer names, class names, or ID prefixes to skip
    skip_ops : operation class names to skip entirely
    skip_rounds : round numbers to skip
    flat_sbox : use flat S-box representation
    algebraic_layers : layers to force into algebraic mode
    nonrename_perm : mark permutation Equals as NONRENAME
    nonrename_rot : mark rotation ops as NONRENAME
    nonrename_gf2 : mark GF2Linear ops as NONRENAME
    """
    nrounds = getattr(func, "nbr_rounds", 0)
    nlayers = getattr(func, "nbr_layers", -1)

    # Build filter sets
    skip_filter = set(skip_layers or [])
    # Separate friendly layer names (for whole-layer skipping) from other tokens
    layer_names = {name for name in skip_filter if name in LAYER_PATTERN_MAPPING}
    other_skip = skip_filter - layer_names
    skip_op_set = set(skip_ops or [])
    alg_filter = set(algebraic_layers or [])
    skip_round_set = {
        r for r in (skip_rounds or []) if isinstance(r, int) and 1 <= r <= nrounds
    }

    relations: List[str] = []
    active_layers: Dict[int, List[int]] = {}  # r -> sorted list of layers that emitted

    kept_rounds = [r for r in range(1, nrounds + 1) if r not in skip_round_set]

    for r in kept_rounds:
        layers_this_round: List[int] = []

        for l in range(0, nlayers + 1):
            try:
                ops = func.constraints[r][l]
            except (IndexError, KeyError, AttributeError):
                continue

            # Skip entire layer if any op matches a friendly layer name filter
            if _layer_matches_filter(ops, layer_names):
                continue

            layer_emitted = False

            for op in ops:
                clsname = op.__class__.__name__
                opid = getattr(op, "ID", "")

                # Skip by class name
                if clsname in skip_op_set:
                    continue

                # Skip by other filters (class names or ID prefixes not in LAYER_PATTERN_MAPPING)
                if _matches_filter(clsname, opid, other_skip):
                    continue

                # Skip built-in LINK_EQ when we need custom linking
                if opid.startswith("LINK_EQ_") and skip_round_set:
                    continue

                # Must have the method
                if not hasattr(op, "_gen_constr_autoguess"):
                    continue

                # Determine algebraic mode
                want_alg = _matches_filter(clsname, opid, alg_filter)

                # Generate constraints
                try:
                    lines = _call_gen_autoguess(
                        op,
                        algebraic=want_alg,
                        flat_sbox=flat_sbox,
                        nonrename_perm=nonrename_perm,
                        nonrename_rot=nonrename_rot,
                        nonrename_gf2=nonrename_gf2,
                    )
                except Exception as e:
                    lines = [f"# Error in {clsname} {opid} r{r}_l{l}: {e}"]

                for line in lines:
                    s = str(line).strip()
                    if s:
                        relations.append(s)
                        layer_emitted = True

            if layer_emitted:
                layers_this_round.append(l)

        if layers_this_round:
            active_layers[r] = sorted(layers_this_round)

    # Handle LINK_EQ skip for non-skipped-round case:
    # When a round's first active layer > 0, built-in LINK_EQ ops connecting
    # layer 0 vars to layer 0+1 vars may be wrong. We handle this via gap-linking.
    # (The skip_round_set check above handles the round-skip case.)

    # Add gap-linking relations
    # When any rounds are skipped, ALL LINK_EQ ops are stripped (line above),
    # so we must generate cross-round links for consecutive kept rounds too.
    gap_links = _add_gap_links(
        func,
        active_layers,
        kept_rounds,
        nlayers,
        link_eq_skipped=bool(skip_round_set),
        bridge_skipped_rounds=bridge_skipped_rounds,
    )
    relations.extend(gap_links)

    return relations


def emit_cipher(
    cipher: Any,
    *,
    skip_functions: Optional[Iterable[str]] = None,
    **kwargs,
) -> List[str]:
    """
    Walk all functions in a cipher and return combined raw relations.

    Parameters
    ----------
    cipher : OCP Cipher object with .functions dict
    skip_functions : function names to skip (e.g. ['KEY_SCHEDULE'])
    **kwargs : forwarded to emit_function()
    """
    skip_fn_set = set(skip_functions or [])
    all_relations: List[str] = []

    # skip_rounds can be a dict keyed by function name for per-function control
    global_skip_rounds = kwargs.get("skip_rounds", None)
    per_func_skip = isinstance(global_skip_rounds, dict)

    for fname, func in cipher.functions.items():
        if fname in skip_fn_set:
            continue
        if per_func_skip:
            kwargs["skip_rounds"] = global_skip_rounds.get(fname, None)
        func_relations = emit_function(func, **kwargs)
        all_relations.extend(func_relations)

    # Restore original skip_rounds in kwargs
    if per_func_skip:
        kwargs["skip_rounds"] = global_skip_rounds

    return all_relations
