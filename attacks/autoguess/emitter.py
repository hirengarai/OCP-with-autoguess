import re
import inspect
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# =========================================================
# Internal regex cache for token replacement
# =========================================================

_RE_CACHE: Dict[str, re.Pattern] = {}


# =========================================================
# Small helpers: classify lines, parse variable IDs
# =========================================================

def _is_algebraic_line(line: str) -> bool:
    """
    Decide whether a given constraint line should be treated as "algebraic".

    A line is considered algebraic if:
      - it contains '+' (sum-like), AND
      - it does NOT contain '=>', AND
      - it is not a comment line starting with '#'.
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    return ("+" in s) and ("=>" not in s)


def parse_r_l_b(var: str) -> Optional[Tuple[int, int, int]]:
    """
    Parse a variable name of the form '*_r_l_b' into (r, l, b).

    Examples
    --------
    "vs_1_3_13" -> (1, 3, 13)
    "vk_2_0_7"  -> (2, 0, 7)
    """
    parts = var.rsplit("_", 3)
    if len(parts) != 4:
        return None
    _, r, l, b = parts
    try:
        return int(r), int(l), int(b)
    except Exception:
        return None


# def _extract_tokens(line: str) -> List[str]:
#     """Extract all variable tokens from a line."""
#     return re.findall(r'[A-Za-z_][A-Za-z0-9_]*', line)


# =========================================================
# Rename detection logic
# =========================================================

def is_layer_rename_pair(a: str, b: str, *, loose: bool = False) -> Optional[Tuple[str, str]]:
    """
    Determine whether (a, b) define a layer-based rename relation.

    Strict mode (loose=False)
    -------------------------
    We require both the same bit index and adjacency in layer or round:
        - v_r_l_b  , v_r_(l+1)_b
        - v_r_l_b  , v_(r+1)_0_b

    Loose mode (loose=True)
    -----------------------
    We ignore the bit index and only require adjacency in layer / round.
    """
    p1 = parse_r_l_b(a)
    p2 = parse_r_l_b(b)
    if not p1 or not p2:
        return None

    r1, l1, bit1 = p1
    r2, l2, bit2 = p2

    if not loose and bit1 != bit2:
        return None

    # same round, adjacent layer
    if r1 == r2 and l2 == l1 + 1:
        return (a, b)   # old -> new
    if r1 == r2 and l1 == l2 + 1:
        return (b, a)

    # cross-round: v_r_l_* , v_(r+1)_0_*
    if r2 == r1 + 1 and l2 == 0:
        return (a, b)
    if r1 == r2 + 1 and l1 == 0:
        return (b, a)

    return None


def detect_layer_renames(lines: Sequence[str], *, loose: bool = False) -> List[Tuple[str, str]]:
    """
    Detect all rename candidate pairs from a list of connection lines.

    Only lines of the form 'x, y' (exactly 2 comma-separated variables,
    ignoring any '=> ...' suffix) are used for rename detection.
    """
    renames: List[Tuple[str, str]] = []

    for line in lines:
        if "=>" in line:
            continue  # skip implication lines entirely
        toks = [t.strip() for t in line.split(",") if t.strip()]
        if len(toks) != 2:
            continue

        a, b = toks
        pair = is_layer_rename_pair(a, b, loose=loose)
        if pair:
            old, new = pair
            renames.append((old, new))

    return renames


# =========================================================
# Text replacement helpers
# =========================================================

def _safe_replace_token(line: str, old_var: str, new_var: str) -> str:
    """
    Replace `old_var` with `new_var` in `line` as a full token.
    Tokens are bounded by characters that are NOT [0-9A-Za-z_].
    """
    pat = _RE_CACHE.get(old_var)
    if pat is None:
        pat = re.compile(r'(?<![0-9A-Za-z_])' + re.escape(old_var) + r'(?![0-9A-Za-z_])')
        _RE_CACHE[old_var] = pat
    return pat.sub(new_var, line)


def replace_var_everywhere(
    relations: Sequence[str],
    old_var: str,
    new_var: str,
    drop_trivial: bool = False,
) -> List[str]:
    """
    Replace a variable name everywhere in a list of constraint lines.
    """
    out: List[str] = []
    for line in relations:
        newline = _safe_replace_token(line, old_var, new_var)

        if drop_trivial and "=>" not in newline:
            toks = [t.strip() for t in newline.split(",")]
            if len(toks) == 2 and toks[0] == toks[1]:
                continue

        out.append(newline)
    return out


# =========================================================
# Union-Find (DSU) for key schedule cleaning
# =========================================================

class DSU:
    """Disjoint Set Union for building equivalence classes."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        p = self.parent.setdefault(x, x)
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def get_all_elements(self) -> Set[str]:
        return set(self.parent.keys())


# =========================================================
# Key schedule cleaning logic
# =========================================================

def _parse_lines_for_cleaning(
    lines: Sequence[str],
) -> Tuple[List[str], List[str], List[str]]:
    """
    Parse lines into:
      - rename_lines: 2-item comma relations (used for building equivalence)
      - connection_lines: 3+ item relations (the actual constraints)
      - other_lines: comments, headers, algebraic relations, etc.
    """
    rename_lines: List[str] = []
    connection_lines: List[str] = []
    other_lines: List[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines, comments, headers
        if not stripped or stripped.startswith('#'):
            other_lines.append(line)
            continue

        # Check for algebraic relations (contain '+')
        if _is_algebraic_line(stripped):
            other_lines.append(line)
            continue

        # Parse comma-separated items (ignore '=>' part for counting)
        left_part = stripped.split('=>')[0] if '=>' in stripped else stripped
        toks = [t.strip() for t in left_part.split(',') if t.strip()]

        if len(toks) == 2:
            rename_lines.append(line)
        elif len(toks) >= 3:
            connection_lines.append(line)
        else:
            other_lines.append(line)

    return rename_lines, connection_lines, other_lines


def _find_anchor_variables(
    dsu: DSU,
    anchor_prefix: str = 'vsk_',
) -> Set[str]:
    """
    Find all anchor variables (vsk_*) that exist in the equivalence classes.
    
    Anchors are simply any variable with anchor_prefix that has been added
    to the DSU. These are the preferred representatives because they are
    the subkey variables used in the block cipher.
    """
    anchors: Set[str] = set()

    for var in dsu.get_all_elements():
        if var.startswith(anchor_prefix):
            anchors.add(var)

    return anchors


def _build_equivalence(
    rename_lines: Sequence[str],
    var_prefixes: Tuple[str, ...] = ('vk_', 'vsk_'),
) -> DSU:
    """
    From 2-item comma relations, build equivalence classes
    among variables with the specified prefixes.
    """
    dsu = DSU()

    for line in rename_lines:
        left_part = line.split('=>')[0] if '=>' in line else line
        toks = [t.strip() for t in left_part.split(',') if t.strip()]

        if len(toks) != 2:
            continue

        a, b = toks

        a_match = any(a.startswith(p) for p in var_prefixes)
        b_match = any(b.startswith(p) for p in var_prefixes)

        if a_match and b_match:
            dsu.union(a, b)

    return dsu


def _choose_representatives(
    dsu: DSU,
    anchors: Set[str],
    anchor_prefix: str = 'vsk_',
    fallback_prefix: str = 'vk_',
) -> Dict[str, str]:
    """
    For each equivalence class, choose a canonical representative.

    Priority:
        1) An anchor variable (vsk_* that appears in connection relations)
        2) Any vsk_* variable
        3) Any vk_* variable (prefer higher layer numbers)
        4) Anything else
    """
    classes: Dict[str, List[str]] = defaultdict(list)
    for v in dsu.get_all_elements():
        root = dsu.find(v)
        classes[root].append(v)

    def priority(v: str) -> Tuple:
        if v in anchors:
            return (0, v)
        if v.startswith(anchor_prefix):
            return (1, v)
        if v.startswith(fallback_prefix):
            parts = v.split('_')
            try:
                layer = int(parts[2]) if len(parts) >= 4 else 0
                return (2, -layer, v)
            except (ValueError, IndexError):
                return (2, 0, v)
        return (3, v)

    rep: Dict[str, str] = {}
    for root, vars_ in classes.items():
        chosen = min(vars_, key=priority)
        for v in vars_:
            rep[v] = chosen

    return rep


def _rewrite_lines_with_representatives(
    lines: Sequence[str],
    rep_map: Dict[str, str],
) -> List[str]:
    """
    Rewrite variables according to rep_map.
    Drop trivial x, x lines.
    """
    out: List[str] = []
    for line in lines:
        new_line = line
        for old, new in rep_map.items():
            if old != new:
                new_line = _safe_replace_token(new_line, old, new)

        # Drop trivial "x, x" connection lines (no '=>')
        stripped = new_line.strip()
        if stripped and '=>' not in new_line:
            left_part = stripped
            toks = [t.strip() for t in left_part.split(',') if t.strip()]
            if len(toks) == 2 and toks[0] == toks[1]:
                continue

        out.append(new_line)

    return out


def clean_key_schedule_relations(
    lines: Sequence[str],
    var_prefixes: Tuple[str, ...] = ('vk_', 'vsk_'),
    anchor_prefix: str = 'vsk_',
    verbose: bool = True,
) -> List[str]:
    """
    High-level key schedule cleaning:
      1) Parse lines into rename/connection/other
      2) Build equivalence classes from rename relations (2-item vk_/vsk_ pairs)
      3) Find anchor variables (any vsk_* in the equivalence classes)
      4) Choose representatives (prioritize vsk_* anchors)
      5) Rewrite all lines (replace vk_* with vsk_* everywhere)

    Parameters
    ----------
    lines :
        All constraint lines (connection + algebraic + comments).

    var_prefixes :
        Variable prefixes to consider for equivalence building.

    anchor_prefix :
        Prefix for anchor variables (those used in block cipher).

    verbose :
        If True, print progress information.

    Returns
    -------
    list[str]
        Cleaned lines with vk_* collapsed onto vsk_* anchors.
    """
    rename_lines, connection_lines, other_lines = _parse_lines_for_cleaning(lines)

    if verbose:
        print(f"[KeyScheduleCleaner] Found {len(rename_lines)} rename relations (2-item)")
        print(f"[KeyScheduleCleaner] Found {len(connection_lines)} connection relations (3+ items)")

    # Build equivalence from rename lines
    dsu = _build_equivalence(rename_lines, var_prefixes=var_prefixes)

    if not dsu.get_all_elements():
        if verbose:
            print("[KeyScheduleCleaner] No equivalences found, returning original lines")
        return list(lines)

    # Find anchors: any vsk_* in the equivalence classes
    anchors = _find_anchor_variables(dsu, anchor_prefix=anchor_prefix)

    if verbose:
        print(f"[KeyScheduleCleaner] Found {len(anchors)} anchor variables ({anchor_prefix}* in equivalence)")
        if anchors:
            examples = sorted(anchors)[:5]
            print(f"[KeyScheduleCleaner] Anchor examples: {examples}{'...' if len(anchors) > 5 else ''}")

    # Choose representatives
    rep_map = _choose_representatives(
        dsu,
        anchors,
        anchor_prefix=anchor_prefix,
        fallback_prefix=var_prefixes[0] if var_prefixes else 'vk_',
    )

    # Count substitutions
    substitutions = sum(1 for old, new in rep_map.items() if old != new)
    if verbose:
        print(f"[KeyScheduleCleaner] Will substitute {substitutions} variables")

    # Rewrite all lines (rename + connection + other)
    all_lines = rename_lines + connection_lines + other_lines
    cleaned = _rewrite_lines_with_representatives(all_lines, rep_map)

    # Filter out empty lines
    final = [ln for ln in cleaned if ln.strip()]

    if verbose:
        print(f"[KeyScheduleCleaner] Output: {len(final)} lines (was {len(lines)})")

    return final


# =========================================================
# Function-level generator
# =========================================================

def genAutoGuessRelationsForFunction(
    func: Any,
    *,
    skip_layers: Optional[Iterable[str]] = None,
    skip_operations: Optional[Iterable[str]] = None,
    save_to_file: bool = True,
    filename: Optional[str] = None,
    known_vars: Optional[Iterable[str]] = None,
    target_vars: Optional[Iterable[str]] = None,
    flat_sbox_mode: bool = True,
    algebraic: bool = True,
    rename_loose: bool = False,
    clean_layers: bool = True,
) -> List[str]:
    """
    Generate AutoGuess-style relations for a single `Function` instance.

    This walks through all rounds and layers of `func.constraints[r][l]`,
    calls each op's `gen_autoguess_constr`, and splits the result into
    connection and algebraic relations, with optional layer-based
    variable renaming to collapse trivial identity layers.

    Parameters
    ----------
    func :
        A `Function`-like object from OCP.

    skip_layers :
        Optional iterable of ID prefixes to skip by layer name.

    skip_operations :
        Optional iterable of operation class names to skip entirely.

    save_to_file :
        If True, write the resulting relations to `filename`.

    filename :
        Output filename. If None, a default is derived.

    known_vars :
        Optional iterable of variable IDs for the "known" section.

    target_vars :
        Optional iterable of variable IDs for the "target" section.

    flat_sbox_mode :
        If True, S-boxes emit flat lines.

    algebraic :
        Global switch for algebraic-mode generation.

    rename_loose :
        If True, allow renames between different bit indices.

    clean_layers :
        If True, perform layer cleaning and rename collapsing.

    Returns
    -------
    list[str]
        Combined list of all generated constraints.
    """
    fname = getattr(func, "name", "FUNCTION")
    nrounds = getattr(func, "nbr_rounds", 0)
    nlayers = getattr(func, "nbr_layers", -1)

    if filename is None:
        filename = f"relations_{fname}_{nrounds}r.txt"

    skip_layer_set: Set[str] = set(skip_layers or [])
    skip_op_set: Set[str] = set(skip_operations or [])

    conn: List[str] = []
    alg: List[str] = []

    print(f"[AutoGuess] Generating constraints for function: {fname}")
    if skip_layer_set:
        print(f"  Skipping layers (by ID prefix): {sorted(skip_layer_set)}")
    if skip_op_set:
        print(f"  Skipping operation classes: {sorted(skip_op_set)}")

    for r in range(1, nrounds + 1):
        for l in range(0, nlayers + 1):
            try:
                ops = func.constraints[r][l]
            except (IndexError, KeyError, AttributeError):
                continue

            new_conn_lines: List[str] = []

            for op in ops:
                clsname = op.__class__.__name__
                opid = getattr(op, "ID", "")

                if clsname in skip_op_set:
                    continue

                if _should_skip_layer(opid, skip_layer_set):
                    continue

                if not hasattr(op, "gen_autoguess_constr"):
                    print(f"  Warning: {clsname} {opid} has no gen_autoguess_constr method")
                    continue

                want_alg = _determine_algebraic_mode(clsname, algebraic, fname, opid)

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

                lines = constraints if isinstance(constraints, list) else [constraints]

                for line in lines:
                    line_str = str(line).strip()
                    if not line_str:
                        continue

                    if _is_algebraic_line(line_str):
                        alg.append(line_str)
                    else:
                        new_conn_lines.append(line_str)

            if clean_layers and new_conn_lines:
                renames = detect_layer_renames(new_conn_lines, loose=rename_loose)

                for old, new in renames:
                    conn = replace_var_everywhere(conn, old, new, drop_trivial=True)
                    alg = replace_var_everywhere(alg, old, new, drop_trivial=True)
                    new_conn_lines = replace_var_everywhere(new_conn_lines, old, new, drop_trivial=True)

            conn.extend(new_conn_lines)

    total = len(conn) + len(alg)
    print(
        f"[AutoGuess] Extracted {total} constraints from function {fname} "
        f"({len(conn)} connection, {len(alg)} algebraic)."
    )

    if save_to_file:
        _write_relations_file(
            filename,
            conn,
            alg,
            known_vars,
            target_vars,
            algebraic,
        )

    return conn + alg


# =========================================================
# Helper utilities used by the generators
# =========================================================

def _should_skip_layer(opid: str, skip_layers: Set[str]) -> bool:
    """Decide whether an operation should be skipped based on its ID prefix."""
    if not skip_layers:
        return False

    for pattern in skip_layers:
        if opid.startswith(pattern):
            return True
    return False


def _determine_algebraic_mode(
    clsname: str,
    algebraic: bool,
    fname: str,
    opid: str,
) -> bool:
    """Decide whether to request algebraic-mode output for a given operation."""
    if not algebraic:
        return False

    if clsname == "ConstantXOR":
        return False

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
    """Call op.gen_autoguess_constr() in a robust, introspection-based way."""
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


def _write_relations_file(
    filename: str,
    conn: Sequence[str],
    alg: Sequence[str],
    known_vars: Optional[Iterable[str]],
    target_vars: Optional[Iterable[str]],
    algebraic: bool,
) -> None:
    """Write relations to an output file in AutoGuess text format."""
    path = Path(filename)
    with path.open("w") as f:
        if conn:
            f.write("connection relations\n")
            for ln in conn:
                f.write(ln + "\n")

        if algebraic and alg:
            f.write("algebraic relations\n")
            for ln in alg:
                f.write(ln + "\n")

        if known_vars:
            f.write("known\n")
            for k in known_vars:
                f.write(str(k).strip() + "\n")

        if target_vars:
            f.write("target\n")
            for t in target_vars:
                f.write(str(t).strip() + "\n")

        f.write("end\n")

    print(f"[AutoGuess] Saved → {path.resolve()}")


# =========================================================
# Cipher-level wrapper
# =========================================================

def genAutoGuessRelations(
    cipher: Any,
    *,
    include_equal: bool = True,
    include_rot: bool = True,
    skip_layers: Optional[Iterable[str]] = None,
    skip_operations: Optional[Iterable[str]] = None,
    skip_functions: Optional[Iterable[str]] = None,
    filename: Optional[str] = None,
    known_vars: Optional[Iterable[str]] = None,
    target_vars: Optional[Iterable[str]] = None,
    flat_sbox_mode: bool = True,
    algebraic: bool = False,
    rename_loose: bool = False,
    clean_layers: bool = True,
    clean_key_schedule: bool = False,
    key_schedule_functions: Optional[Iterable[str]] = None,
    key_var_prefixes: Tuple[str, ...] = ('vk_', 'vsk_'),
    key_anchor_prefix: str = 'vsk_',
) -> List[str]:
    """
    Generate AutoGuess-style relations for an entire cipher / primitive.

    This iterates over `cipher.functions.items()`, optionally skipping
    some functions by name, and calls `genAutoGuessRelationsForFunction`
    for each one. All per-function relations are merged into one combined file.

    Parameters
    ----------
    cipher :
        Primitive-like object with:
          - `name`
          - optional `nbr_rounds`
          - `functions` dict mapping function names to Function objects

    include_equal :
        If False, skip all operations of class "Equal".

    include_rot :
        If False, skip all operations of class "Rot".

    skip_layers :
        Optional iterable of ID prefixes used to skip layers.

    skip_operations :
        Optional iterable of operation class names to skip entirely.

    skip_functions :
        Optional iterable of function names to skip entirely.

    filename :
        Output filename. If None, auto-generated.

    known_vars :
        Optional iterable of variable IDs for the "known" section.

    target_vars :
        Optional iterable of variable IDs for the "target" section.

    flat_sbox_mode :
        Passed through to `genAutoGuessRelationsForFunction`.

    algebraic :
        Global algebraic flag.

    rename_loose :
        Controls strict vs loose rename detection.

    clean_layers :
        If True, per-layer rename cleaning is applied inside each function.

    clean_key_schedule :
        If True, after all functions are processed, run the key schedule
        cleaner to collapse vk_* variables onto vsk_* anchors. This is
        useful for block ciphers where key schedule variables should be
        expressed in terms of subkey variables used in the block cipher.

    key_var_prefixes :
        Variable prefixes to consider for key schedule equivalence.
        Default: ('vk_', 'vsk_')

    key_anchor_prefix :
        Prefix for anchor variables in key schedule cleaning.
        Default: 'vsk_'

    key_schedule_functions :
        Function names that should skip layer cleaning when clean_key_schedule
        is enabled. These are the functions that contain vk_*/vsk_* variables.
        Default: {'KEY_SCHEDULE', 'SUBKEYS'}

    Returns
    -------
    list[str]
        Combined list of all constraints across all processed functions.
    """
    if filename is None:
        try:
            cname = getattr(cipher, "name", None) or cipher.__class__.__name__
            rounds = getattr(cipher, "nbr_rounds", None)
            filename = f"relations_{cname}"
            if rounds is not None:
                filename += f"_{rounds}r"
            filename += ".txt"
        except Exception:
            filename = "relations_unknown.txt"

    skip_function_set: Set[str] = set(skip_functions or [])

    # Build skip_operations from flags
    skip_op_set: Set[str] = set(skip_operations or [])
    if not include_equal:
        skip_op_set.add("Equal")
    if not include_rot:
        skip_op_set.add("Rot")

    all_relations: List[str] = []

    print(f"[AutoGuess] Generating constraints for cipher: {cipher.name}")
    if skip_function_set:
        print(f"  Skipping functions: {sorted(skip_function_set)}")

    # Functions that should skip layer cleaning when clean_key_schedule is enabled
    key_sched_func_set: Set[str] = set(key_schedule_functions or {"KEY_SCHEDULE", "SUBKEYS"})

    for fname, func in cipher.functions.items():
        if fname in skip_function_set:
            print(f"  Skipping function: {fname}")
            continue

        print(f"\n  Processing function: {fname}")
        
        # If clean_key_schedule is enabled, disable layer cleaning for key-related functions
        # to preserve vk_*/vsk_* pairs for the key schedule cleaner
        func_clean_layers = clean_layers
        if clean_key_schedule and fname in key_sched_func_set:
            func_clean_layers = False
            print(f"    (layer cleaning disabled - will use key schedule cleaner)")
        
        func_relations = genAutoGuessRelationsForFunction(
            func,
            skip_layers=skip_layers,
            skip_operations=skip_op_set,
            save_to_file=False,
            flat_sbox_mode=flat_sbox_mode,
            algebraic=algebraic,
            rename_loose=rename_loose,
            clean_layers=func_clean_layers,
        )
        all_relations.extend(func_relations)

    # ---- Key schedule cleaning (optional) ----
    if clean_key_schedule:
        print("\n[AutoGuess] Running key schedule cleaner...")
        all_relations = clean_key_schedule_relations(
            all_relations,
            var_prefixes=key_var_prefixes,
            anchor_prefix=key_anchor_prefix,
            verbose=True,
        )

    # Final classification for writing
    conn: List[str] = [r for r in all_relations if not _is_algebraic_line(r)]
    alg: List[str] = [r for r in all_relations if _is_algebraic_line(r)]

    _write_relations_file(
        filename,
        conn,
        alg,
        known_vars,
        target_vars,
        algebraic,
    )

    total = len([r for r in all_relations if not r.strip().startswith('#')])
    print(f"\n[AutoGuess] Total: {total} constraints across all functions")

    return all_relations