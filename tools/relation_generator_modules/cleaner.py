"""
Relation Cleaner — simplify raw relations by collapsing renames.

When the emitter walks an OCP cipher, it produces many 2-variable "rename"
relations like "vs_1_2_3, vs_1_3_0" where both variables represent the same
value. This module collapses them using Union-Find so AutoGuess sees fewer,
cleaner variables.

Pipeline:
  1. Parse lines into sections (connection, algebraic, known, target, …)
  2. Separate renames (2-var lines) from real relations
  3. Split renames into same-round and cross-round pairs
  4. Same-round: Union-Find → pick representative → build substitution map
  5. Cross-round: separate Union-Find with configurable direction
  6. Apply substitutions to all real relations and variable lists
  7. Format output with section headers
"""

import re
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_var(var: str) -> Optional[Tuple[int, int, int]]:
    """
    Parse 'prefix_round_layer_word' into (round, layer, word).

    OCP variables look like 'vs_1_2_3' or 'vk_2_0_1'.
    We split on '_' from the right to get the last 3 numeric parts.
    """
    parts = var.rsplit("_", 3)
    if len(parts) != 4:
        return None
    try:
        return (int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def _parse_sections(lines: List[str]) -> Dict[str, List[str]]:
    """Parse input lines into named sections."""
    sections = {
        "connection": [],
        "algebraic": [],
        "known": [],
        "target": [],
        "not guessed": [],
    }
    current = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        lower = stripped.lower()
        if lower == "connection relations":
            current = "connection"
        elif lower == "algebraic relations":
            current = "algebraic"
        elif lower == "known":
            current = "known"
        elif lower == "target":
            current = "target"
        elif lower == "not guessed":
            current = "not guessed"
        elif lower == "end":
            break
        elif current is not None:
            sections[current].append(stripped)

    return sections


def _is_rename(line: str) -> bool:
    """
    A rename is a line with exactly 2 variables, no '+', no '=>', no 'NONRENAME'.

    Example rename:    "vs_1_2_0, vs_1_3_0"
    NOT a rename:      "vs_1_2_0, vs_1_3_0, NONRENAME"
    NOT a rename:      "a, b => c"
    NOT a rename:      "a + b + c"
    """
    if "+" in line or "=>" in line or "NONRENAME" in line:
        return False
    tokens = [t.strip() for t in line.split(",") if t.strip()]
    return len(tokens) == 2


def _is_algebraic(line: str) -> bool:
    """Algebraic lines contain '+' but not '=>'."""
    return "+" in line and "=>" not in line


def _separate_relations(connection: List[str], algebraic: List[str]):
    """Split connection lines into renames and non-renames, merge algebraic."""
    renames = []
    non_renames = []
    for line in connection:
        if _is_rename(line):
            renames.append(line)
        else:
            non_renames.append(line)
    non_renames.extend(algebraic)
    return renames, non_renames


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------


class UnionFind:
    """Simple Union-Find with path compression."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def get_classes(self) -> List[Set[str]]:
        """Return all equivalence classes."""
        classes: Dict[str, Set[str]] = {}
        for x in self.parent:
            root = self.find(x)
            classes.setdefault(root, set()).add(x)
        return list(classes.values())


# ---------------------------------------------------------------------------
# Representative selection
# ---------------------------------------------------------------------------


def _rank_var(
    var: str,
    *,
    prefer_vk: bool = False,
    desc_round: bool = False,
    desc_layer: bool = False,
) -> tuple:
    """
    Return a sortable tuple for picking representatives.

    Smaller rank = "better" candidate to be the representative.

    prefer_vk:  if True, vk_* variables sort first (rank 0 vs 1)
    desc_round: if True, later rounds sort first (for cross-round direction)
    desc_layer: if True, later layers sort first (sink-canonical)
    """
    is_vk = 1 if not var.startswith("vk_") else 0  # 0 = vk (preferred)
    p = parse_var(var)
    if p is None:
        big = 10**9
        if prefer_vk:
            return (is_vk, big, big, big, var)
        return (big, big, big, var)

    r, layer, word = p
    r_key = -r if desc_round else r
    l_key = -layer if desc_layer else layer
    w_key = -word if desc_layer else word

    if prefer_vk:
        return (is_vk, r_key, l_key, w_key, var)
    return (r_key, l_key, w_key, var)


def _choose_rep(var_set: Set[str], canonical: bool, cross_round: bool = False) -> str:
    """
    Pick a representative from a set of equivalent variables.

    For same-round classes: prefer vk_*, then earliest (canonical=True)
      or latest (canonical=False) layer/word.

    For cross-round classes: prefer vk_* in the winning round
      (determined by cross_round direction flag used upstream).
    """
    desc_layer = not canonical

    # For same-round: prefer vk, use layer/word ordering
    vks = [v for v in var_set if v.startswith("vk_")]
    pool = set(vks) if vks else var_set

    candidates = sorted(
        pool, key=lambda v: _rank_var(v, prefer_vk=True, desc_layer=desc_layer)
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# Rename pair handling
# ---------------------------------------------------------------------------


def _round_of(var: str) -> Optional[int]:
    p = parse_var(var)
    return None if p is None else p[0]


def _is_cross_round(a: str, b: str) -> bool:
    ra, rb = _round_of(a), _round_of(b)
    if ra is None or rb is None:
        return False
    return ra != rb


def _split_rename_pairs(renames: List[str]):
    """Split rename lines into same-round and cross-round pairs."""
    same = []
    cross = []
    for line in renames:
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        if len(tokens) == 2:
            a, b = tokens
            if _is_cross_round(a, b):
                cross.append((a, b))
            else:
                same.append((a, b))
    return same, cross


# ---------------------------------------------------------------------------
# Same-round processing
# ---------------------------------------------------------------------------


def _build_same_round_map(
    eq_classes: List[Set[str]],
    anchored: Set[str],
    canonical: bool,
    strict: bool,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Process same-round equivalence classes.

    Returns:
      sub_map:  {old_var: representative} for substitution
      preserved:  rename lines to keep in output (when 2+ anchored vars clash)

    Rules for each class:
      - 0 or 1 anchored vars: collapse everything to representative
      - 2+ anchored vars:
          - strict=True: raise error
          - strict=False: keep anchored vars distinct, collapse non-anchored,
                          output equality chain among anchored + rep
    """
    sub_map: Dict[str, str] = {}
    preserved: List[str] = []

    for cls in eq_classes:
        if not cls:
            continue

        anchored_in_cls = cls & anchored
        rep = _choose_rep(cls, canonical)

        # Simple case: 0 or 1 anchored — collapse everything to rep
        if len(anchored_in_cls) <= 1:
            for v in cls:
                if v != rep:
                    sub_map[v] = rep
            continue

        # 2+ anchored variables in same class
        if strict:
            raise RuntimeError(
                f"Anchored conflict: {sorted(anchored_in_cls)} "
                f"in class {sorted(cls)}"
            )

        # --- FIX (2026-04): collapse everything to rep, same as 0/1-anchored case. ---
        # The original "preserved equality chain" logic (commented out below) was
        # designed for SPARSE anchored sets. Under DENSE anchoring — e.g. when
        # trail_to_key_recovery stuffs every state variable into `not_guessed` —
        # it fails to coordinate with the cross-round substitution pass, leaving
        # orphaned variable names (like `vs_2_0_0`) in preserved rename lines
        # that were never substituted in the not_guessed section. Autoguess then
        # sees those orphaned names as free variables and "guesses" state cells,
        # producing spurious state-variable leakage in the guess set.
        #
        # TO REVERT: delete the 4 lines below marked "# NEW" and uncomment the
        # block further down.
        for v in cls:  # NEW
            if v != rep:  # NEW
                sub_map[v] = rep  # NEW
        continue  # NEW

        # --- ORIGINAL PRESERVED-CHAIN LOGIC (kept commented for easy revert) ---
        # # Collapse non-anchored to rep, keep anchored distinct
        # for v in cls:
        #     if v not in anchored_in_cls and v != rep:
        #         sub_map[v] = rep
        #
        # # Output equality chain among anchored + rep
        # keep = sorted(anchored_in_cls | {rep}, key=lambda v: _rank_var(v))
        # for i in range(len(keep) - 1):
        #     preserved.append(f"{keep[i]}, {keep[i+1]}")

    return sub_map, preserved


# ---------------------------------------------------------------------------
# Cross-round processing
# ---------------------------------------------------------------------------


def _build_cross_round_map(
    cross_pairs: List[Tuple[str, str]],
    same_map: Dict[str, str],
    cross_dir: bool,
    canonical: bool,
) -> Dict[str, str]:
    """
    Build substitution map for cross-round renames.

    cross_dir: False = prefer earlier round (later→earlier substitution)
               True  = prefer later round (earlier→later substitution)
    """
    uf = UnionFind()
    for a, b in cross_pairs:
        ra = _resolve(a, same_map)
        rb = _resolve(b, same_map)
        if ra != rb:
            uf.union(ra, rb)

    cross_map: Dict[str, str] = {}
    for cls in uf.get_classes():
        if not cls:
            continue

        # Find vk variables with known rounds
        vks = [v for v in cls if v.startswith("vk_") and _round_of(v) is not None]

        if vks:
            # Pick winning round among vk vars
            vk_rounds = [_round_of(v) for v in vks]
            winning_round = max(vk_rounds) if cross_dir else min(vk_rounds)
            vks_in_round = [v for v in vks if _round_of(v) == winning_round]

            # Within winning round, use canonical layer/word ordering
            desc_layer = not canonical
            rep = sorted(
                vks_in_round,
                key=lambda v: _rank_var(v, prefer_vk=True, desc_layer=desc_layer),
            )[0]
        else:
            # No vk: pick by round direction
            desc_round = cross_dir
            rep = sorted(cls, key=lambda v: _rank_var(v, desc_round=desc_round))[0]

        for v in cls:
            if v != rep:
                cross_map[v] = rep

    return cross_map


# ---------------------------------------------------------------------------
# Substitution
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _resolve(var: str, sub_map: Dict[str, str]) -> str:
    """Follow substitution chain to final value."""
    seen = set()
    current = var
    while current in sub_map and current not in seen:
        seen.add(current)
        current = sub_map[current]
    return current


def _apply_sub(lines: List[str], sub_map: Dict[str, str]) -> List[str]:
    """Apply substitution map to all variables in lines."""
    if not sub_map:
        return lines

    def replacer(match):
        var = match.group(0)
        final = _resolve(var, sub_map)
        return final if final != var else var

    return [_VAR_RE.sub(replacer, line) for line in lines]


def _apply_sub_to_varlist(
    var_list: List[str],
    sub_maps: List[Dict[str, str]],
) -> List[str]:
    """Apply multiple substitution maps to a variable list, deduplicate."""
    seen = set()
    result = []
    for v in var_list:
        cur = v
        for sm in sub_maps:
            cur = _resolve(cur, sm)
        if cur not in seen:
            seen.add(cur)
            result.append(cur)
    return result


def _substitution_chain(var: str, sub_maps: List[Dict[str, str]]) -> List[str]:
    """Return chain [var, ..., final] for debug output."""
    chain = [var]
    cur = var
    for sm in sub_maps:
        seen = set()
        while cur in sm and cur not in seen:
            seen.add(cur)
            cur = sm[cur]
            chain.append(cur)
    return chain


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _remove_trivial(lines: List[str]) -> List[str]:
    """Remove relations like 'x, x' (but keep implications and algebraic)."""
    result = []
    for line in lines:
        if "=>" in line or "+" in line:
            result.append(line)
            continue
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        if len(tokens) >= 2 and len(set(tokens)) > 1:
            result.append(line)
    return result


def _strip_nonrename_markers(lines: List[str]) -> List[str]:
    """Remove ', NONRENAME' markers from all lines."""
    return [line.replace(", NONRENAME", "") for line in lines]


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _format_output(
    non_rename: List[str],
    preserved: List[str],
    known: List[str],
    target: List[str],
    not_guessed: List[str],
) -> List[str]:
    """Build final output with section headers."""
    output = []

    # Split non-rename into connection and algebraic
    connection = []
    algebraic = []
    for line in non_rename:
        if _is_algebraic(line):
            algebraic.append(line)
        else:
            connection.append(line)

    # Add preserved renames to connection
    connection.extend(preserved)

    # Strip NONRENAME markers
    connection = _strip_nonrename_markers(connection)
    algebraic = _strip_nonrename_markers(algebraic)

    if connection:
        output.append("connection relations")
        output.extend(connection)
    if algebraic:
        output.append("algebraic relations")
        output.extend(algebraic)
    if known:
        output.append("known")
        output.extend(known)
    if target:
        output.append("target")
        output.extend(target)
    if not_guessed:
        output.append("not guessed")
        output.extend(not_guessed)

    output.append("end")
    return output


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def clean_relations(
    lines: List[str],
    *,
    canonical: bool = True,
    cross_round_dir: bool = False,
    debug_cross_renames: bool = False,
    strict_anchored: bool = False,
) -> List[str]:
    """
    Clean relations by collapsing renames.

    Parameters
    ----------
    lines : raw relation lines (with section headers)
    canonical : True = earliest layer/word as rep, False = latest
    cross_round_dir : False = later→earlier, True = earlier→later
    debug_cross_renames : if True, include cross-round rename lines in output
    strict_anchored : if True, error on 2+ anchored vars in same class

    Returns
    -------
    Cleaned relation lines with section headers and debug comments.
    """
    # Step 1: Parse sections
    sections = _parse_sections(lines)
    known = sections["known"]
    target = sections["target"]
    not_guessed = sections["not guessed"]

    # Step 2: Separate renames from real relations
    renames, non_rename = _separate_relations(
        sections["connection"], sections["algebraic"]
    )

    # Step 3: Split renames into same-round and cross-round
    same_pairs, cross_pairs = _split_rename_pairs(renames)

    # Step 4: Build same-round equivalence classes and substitution map
    uf = UnionFind()
    for a, b in same_pairs:
        uf.union(a, b)

    anchored = set(known) | set(target) | set(not_guessed)

    same_map, preserved_same = _build_same_round_map(
        uf.get_classes(), anchored, canonical, strict_anchored
    )

    # Step 5: Apply same-round substitutions to real relations
    non_rename = _apply_sub(non_rename, same_map)

    # Step 6: Build and apply cross-round substitutions
    cross_map = _build_cross_round_map(
        cross_pairs, same_map, cross_round_dir, canonical
    )
    non_rename = _apply_sub(non_rename, cross_map)
    non_rename = _remove_trivial(non_rename)

    # Step 7: Rewrite known/target/not_guessed through substitutions
    sub_maps = [same_map, cross_map]
    known = _apply_sub_to_varlist(known, sub_maps)
    target = _apply_sub_to_varlist(target, sub_maps)
    not_guessed = _apply_sub_to_varlist(not_guessed, sub_maps)

    # Post-substitution: known takes precedence over not_guessed.
    # After rename-collapse, a not_guessed state var can end up sharing a
    # canonical rep with a known var (e.g. a bottom-row cell at a deeper
    # layer collapsing to its layer-0 plaintext rep). Emitting both
    # creates contradictory unit clauses in the SAT encoding (var is
    # forced TRUE by `known` and FALSE by `not_guessed` at step 0).
    known_set = set(known)
    not_guessed = [v for v in not_guessed if v not in known_set]

    # Step 8: Optionally preserve cross-round renames (debug only)
    preserved_cross = []
    if debug_cross_renames:
        edges = set()
        for a, b in cross_pairs:
            ra = _resolve(_resolve(a, same_map), cross_map)
            rb = _resolve(_resolve(b, same_map), cross_map)
            if ra != rb:
                pair = (ra, rb) if ra <= rb else (rb, ra)
                edges.add(pair)
        preserved_cross = [f"{x}, {y}" for x, y in sorted(edges)]

    # Step 9: Format output
    preserved = preserved_same + preserved_cross
    output = _format_output(non_rename, preserved, known, target, not_guessed)

    # Step 10: Append debug substitution chains (after 'end')
    watch = list(
        dict.fromkeys(sections["known"] + sections["target"] + sections["not guessed"])
    )
    debug = []
    debug.append("# ---- cleaner debug: substitution chains ----")
    debug.append(f"# canonical={canonical} cross_round_dir={cross_round_dir}")
    debug.append("# format: old -> ... -> new")
    for v in watch:
        chain = _substitution_chain(v, sub_maps)
        if len(chain) >= 2:
            debug.append("# " + " -> ".join(chain))
    debug.append("# ---- end debug ----")
    output.extend(debug)

    return output
