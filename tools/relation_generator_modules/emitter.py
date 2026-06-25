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
import warnings
from typing import Any, Dict, Iterable, List, Literal, Optional, Set


# Sentinel for deprecated-kwarg detection (distinguishes "user passed True/False"
# from "user did not pass it"). The real kwarg is now sbox_form.
_UNSET: Any = object()

SboxForm = Literal["rename", "implication"]

# Layer pattern mapping — maps friendly names to operator detection rules

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
    # MatrixLayer is the cipher-state MDS layer (MixColumns-style). Algebraic
    # mode emits one XOR equation per output row — only meaningful for binary
    # matrices on multiple variables.
    "MatrixLayer": {"op_class": ["Matrix"]},
    # LFSRLayer is the byte-/word-level invertible binary matrix used in
    # tweakey schedules. At word level this is a rename (mutually-determining
    # via the inverse matrix); GF2Linear_Trans does NOT support algebraic_mode
    # because expressing the bit-mixing algebraically would require bit-IDs
    # that aren't part of the variable-level relation model.
    "LFSRLayer": {"op_class": ["GF2Linear_Trans"]},
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


# Matching helpers — one function replaces three in the original


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


# Calling _gen_constr_autoguess with the right kwargs


_PERMUTATION_EQ_PREFIXES = tuple(
    LAYER_PATTERN_MAPPING["PermutationLayer"]["id_starts_with"]
)


def _infer_sbox_form(op: Any) -> SboxForm:
    """Pick the S-box emission form from the wiring shape.

    "rename"      — one wide variable in, one wide variable out (each strictly
                    multi-bit). The cipher is treating the S-box as a single
                    bijection on a multi-bit word; emit a 2-variable line that
                    the cleaner can collapse safely (the S-box is bijective).
    "implication" — anything else (multiple 1-bit vars, mixed widths, etc).
                    The cipher has unpacked the S-box into bit-level wiring;
                    each output bit depends nonlinearly on all inputs, so emit
                    one ``ins => out_bit`` line per output bit.
    """
    in_vars = op.input_vars
    out_vars = op.output_vars
    if (
        len(in_vars) == 1
        and len(out_vars) == 1
        and getattr(in_vars[0], "bitsize", 1) > 1
        and getattr(out_vars[0], "bitsize", 1) > 1
    ):
        return "rename"
    return "implication"


def _is_permutation_equal(opid: str) -> bool:
    """Equal ops whose ID matches the permutation-layer prefix set.

    Used so that the `nonrename_perm` toggle reaches *permutation* Equals
    (which are renames the user may want to keep) without leaking into
    LINK_EQ_ / ID_ / other Equals, which are pure equality assertions and
    must always be treated as renames.
    """
    return any(opid.startswith(p) for p in _PERMUTATION_EQ_PREFIXES)


def _call_gen_autoguess(
    op: Any,
    *,
    algebraic: bool,
    sbox_form: Optional[SboxForm],
    nonrename_perm: bool,
    nonrename_rot: bool,
    nonrename_gf2: bool,
) -> List[str]:
    """
    Call ``op.gen_autoguess_constr()`` with whatever kwargs it supports.


    Toggles that target an operator without the matching code path raise
    ``ValueError`` instead of silently no-op'ing — surfacing the mismatch
    is the whole point of having a public toggle.

    The Equal "only Perm_*_EQ_ ids" rule keeps LINK_EQ_ / ID_ / other
    structural Equals as renames regardless of ``perm_rename=False``; only
    permutation-layer Equals (identified by ID prefix) honor the flag.
    """
    gen = op.gen_autoguess_constr
    supported = set(inspect.signature(gen).parameters.keys())
    clsname = op.__class__.__name__
    opid = getattr(op, "ID", "")

    kwargs = {}
    if "flat_sbox_mode" in supported:
        form: SboxForm = sbox_form if sbox_form is not None else _infer_sbox_form(op)
        if form not in ("rename", "implication"):
            raise ValueError(
                f"sbox_form must be 'rename' or 'implication'; got {form!r}."
            )
        if form == "rename":
            in_total = sum(getattr(v, "bitsize", 0) for v in op.input_vars)
            out_total = sum(getattr(v, "bitsize", 0) for v in op.output_vars)
            if in_total != out_total:
                raise ValueError(
                    f"Sbox {clsname} (op id {opid!r}): sbox_form='rename' "
                    f"requires equal input/output widths, got {in_total} vs "
                    f"{out_total}. Use sbox_form='implication' or fix the "
                    f"wiring."
                )
        kwargs["flat_sbox_mode"] = (form == "rename")
    if "non_square_strategy" in supported:
        kwargs["non_square_strategy"] = "bidirectional"

    # ---- algebraic_mode routing ----
    if algebraic and "algebraic_mode" not in supported:
        raise ValueError(
            f"algebraic_layers requested for {clsname} (op id {opid!r}), but "
            f"{clsname}.gen_autoguess_constr does not accept algebraic_mode. "
            f"Either remove the matching layer from algebraic_layers or extend "
            f"{clsname} with an algebraic_mode code path."
        )
    if "algebraic_mode" in supported:
        kwargs["algebraic_mode"] = algebraic

    # ---- treat_as_nonrename routing ----
    if clsname == "Rot":
        target_nonrename = nonrename_rot
        which_flag = "rot_rename=False"
    elif clsname == "GF2Linear_Trans":
        target_nonrename = nonrename_gf2
        which_flag = "gf2linear_rename=False"
    elif clsname == "Equal":
        target_nonrename = nonrename_perm if _is_permutation_equal(opid) else False
        which_flag = "perm_rename=False"
    else:
        target_nonrename = nonrename_perm
        which_flag = "perm_rename=False"

    if target_nonrename and "treat_as_nonrename" not in supported:
        raise ValueError(
            f"{which_flag} requested for {clsname} (op id {opid!r}), but "
            f"{clsname}.gen_autoguess_constr does not accept treat_as_nonrename. "
            f"Either flip the flag back to default or extend {clsname}."
        )
    if "treat_as_nonrename" in supported:
        kwargs["treat_as_nonrename"] = target_nonrename

    result = gen(**kwargs)

    # Normalize to list of strings
    if result is None:
        return []
    if isinstance(result, str):
        return [result]
    return list(result)


# Gap-linking — reconnect variables when layers/rounds are skipped


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

        # If first active layer > 0, link layer 0 vars to it.
        # We only swallow index/attribute errors from `func.vars[...]`
        # (defensive against ill-formed function objects). The
        # zip(..., strict=True) ValueError MUST propagate — a width
        # mismatch is a real structural problem worth surfacing.
        if layers[0] > 0:
            try:
                in_vars = func.vars[r][0]
                out_vars = func.vars[r][layers[0]]
            except (IndexError, KeyError, AttributeError):
                in_vars = out_vars = None
            if in_vars is not None and out_vars is not None:
                for iv, ov in zip(in_vars, out_vars, strict=True):
                    links.append(f"{iv.ID}, {ov.ID}")

        # Link across gaps within the round
        for i in range(len(layers) - 1):
            prev_l = layers[i]
            next_l = layers[i + 1]
            if next_l > prev_l + 1:
                try:
                    in_vars = func.vars[r][prev_l + 1]
                    out_vars = func.vars[r][next_l]
                except (IndexError, KeyError, AttributeError):
                    continue
                for iv, ov in zip(in_vars, out_vars, strict=True):
                    links.append(f"{iv.ID}, {ov.ID}")

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
            except (IndexError, KeyError, AttributeError):
                continue
            for iv, ov in zip(in_vars, out_vars, strict=True):
                links.append(f"{iv.ID}, {ov.ID}")

    return links


# Main entry points


def emit_function(
    func: Any,
    *,
    skip_layers: Optional[Iterable[str]] = None,
    skip_ops: Optional[Iterable[str]] = None,
    skip_rounds: Optional[Iterable[int]] = None,
    sbox_form: Optional[SboxForm] = None,
    flat_sbox: Any = _UNSET,  # deprecated; use sbox_form
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
    sbox_form : per-S-box emission form. ``None`` (default) infers from
        wiring shape — see :func:`_infer_sbox_form`. ``"rename"`` emits a
        single 2-variable rename line per S-box (correct only when the
        S-box is a bijection on a multi-bit word). ``"implication"`` emits
        one ``ins => out_bit`` per output bit (correct for bit-level
        wirings). Explicit values override the inference.
    flat_sbox : DEPRECATED. ``True`` ↔ ``sbox_form='rename'``;
        ``False`` ↔ ``sbox_form='implication'``. Kept for one release as a
        backward-compat shim that emits a DeprecationWarning.
    algebraic_layers : layers to force into algebraic mode
    nonrename_perm : mark permutation Equals as NONRENAME
    nonrename_rot : mark rotation ops as NONRENAME
    nonrename_gf2 : mark GF2Linear ops as NONRENAME
    """
    if flat_sbox is not _UNSET:
        warnings.warn(
            "flat_sbox is deprecated; use sbox_form=('rename'|'implication'|None) "
            "instead. flat_sbox=True ↔ sbox_form='rename'; "
            "flat_sbox=False ↔ sbox_form='implication'. None lets the emitter "
            "infer the form from the S-box wiring shape.",
            DeprecationWarning,
            stacklevel=2,
        )
        if sbox_form is None:
            sbox_form = "rename" if flat_sbox else "implication"
    # Require nbr_rounds and nbr_layers. Previously these silently defaulted
    # to 0 and -1, producing an empty output without any signal to the user.
    nrounds = getattr(func, "nbr_rounds", None)
    nlayers = getattr(func, "nbr_layers", None)
    if nrounds is None or not isinstance(nrounds, int) or nrounds < 1:
        raise ValueError(
            f"emit_function: {getattr(func, 'name', func)!r} has invalid "
            f"nbr_rounds={nrounds!r} (expected positive int)."
        )
    if nlayers is None or not isinstance(nlayers, int) or nlayers < 0:
        raise ValueError(
            f"emit_function: {getattr(func, 'name', func)!r} has invalid "
            f"nbr_layers={nlayers!r} (expected non-negative int)."
        )

    # Build filter sets
    skip_filter = set(skip_layers or [])
    # Separate friendly layer names (for whole-layer skipping) from other tokens
    layer_names = {name for name in skip_filter if name in LAYER_PATTERN_MAPPING}
    other_skip = skip_filter - layer_names
    skip_op_set = set(skip_ops or [])
    alg_filter = set(algebraic_layers or [])

    # Validate skip_rounds entry types up front — string/bool/etc. entries
    # previously slipped through the isinstance(int) filter and were silently
    # dropped, leaving the user wondering why their skip didn't apply.
    skip_round_set: set = set()
    for r in (skip_rounds or []):
        if isinstance(r, bool) or not isinstance(r, int):
            raise TypeError(
                f"emit_function: skip_rounds entry {r!r} is not an int "
                f"(got {type(r).__name__}); cast or drop it."
            )
        if 1 <= r <= nrounds:
            skip_round_set.add(r)

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

                # Skip built-in LINK_EQ ONLY when one of its endpoints is in
                # skip_round_set. The LINK_EQ at round `r` connects
                # vars[r][max] ⇔ vars[r+1][0], so if either `r` or `r+1` is
                # skipped, the link is stale and must be re-emitted by the
                # gap-linker. The previous logic stripped ALL LINK_EQ whenever
                # any round was skipped, throwing away legitimate intra-active
                # links that the gap-linker then had to rebuild for no reason.
                if opid.startswith("LINK_EQ_") and skip_round_set:
                    parts = opid.rsplit("_", 3)
                    link_round = None
                    if len(parts) == 4:
                        try:
                            link_round = int(parts[1])
                        except ValueError:
                            link_round = None
                    if (
                        link_round is None
                        or link_round in skip_round_set
                        or (link_round + 1) in skip_round_set
                    ):
                        continue

                # Must have the method
                if not hasattr(op, "gen_autoguess_constr"):
                    continue

                # Determine algebraic mode
                want_alg = _matches_filter(clsname, opid, alg_filter)

                # Generate constraints. Previously a bare `except Exception`
                # buried any op-level failure as a `# Error ...` comment line,
                # which the cleaner then dropped — making real bugs invisible.
                # Re-raise so the user sees them.
                try:
                    lines = _call_gen_autoguess(
                        op,
                        algebraic=want_alg,
                        sbox_form=sbox_form,
                        nonrename_perm=nonrename_perm,
                        nonrename_rot=nonrename_rot,
                        nonrename_gf2=nonrename_gf2,
                    )
                except Exception as e:
                    raise RuntimeError(
                        f"gen_autoguess_constr failed for {clsname} {opid} "
                        f"at round={r}, layer={l}: {e}"
                    ) from e

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

    # Add gap-linking relations.
    # LINK_EQ stripping above is now precise (only ops with endpoints in
    # skip_round_set are dropped), so any redundant cross-round links the
    # gap-linker adds for *consecutive kept rounds* are harmless duplicates
    # — Union-Find merges them into the same class and _remove_trivial
    # drops the leftovers.
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

    # try/finally so the per-function skip_rounds key is restored even when
    # emit_function raises mid-loop — otherwise the caller's kwargs dict
    # ends up mutated with whatever the last-attempted function's value was.
    try:
        for fname, func in cipher.functions.items():
            if fname in skip_fn_set:
                continue
            if per_func_skip:
                kwargs["skip_rounds"] = global_skip_rounds.get(fname, None)
            func_relations = emit_function(func, **kwargs)
            all_relations.extend(func_relations)
    finally:
        if per_func_skip:
            kwargs["skip_rounds"] = global_skip_rounds

    return all_relations
