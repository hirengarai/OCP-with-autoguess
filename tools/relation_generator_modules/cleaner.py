"""
Relation Cleaner — simplify raw relations by collapsing renames.

When the emitter walks an OCP cipher, it produces many 2-variable "rename"
relations like "vs_1_2_3, vs_1_3_0" where both variables represent the same
value. This module collapses them using Union-Find so AutoGuess sees fewer,
cleaner variables.

Pipeline (clean_relations):
    parsed = parse_input(lines)
    same   = collapse_same_round(parsed, config)
    cross  = collapse_cross_round(parsed, same.substitution, config)
    final  = SubstitutionMap.compose(same.substitution, cross.substitution)
    return rewrite_and_format(parsed, final,
                              same.preserved + cross.preserved, config)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Literal, Optional, Set, Tuple

CleaningDirection = Literal["input", "output", "default", "opp_default"]


# Public configuration

# `cleaning_direction` picks one of four corners. Each value sets BOTH the
# same-round and cross-round rep choice in lockstep:
#
#   "input"       — uniform input boundary  (earliest layer + later round).
#                   Every survivor lands at vk_<k+1>_0_*.
#   "output"      — uniform output boundary (latest layer + earlier round).
#                   Every survivor lands at vk_<k>_<max>_*.
#   "default"     — mixed: earliest layer + earlier round.          [DEFAULT]
#                   Legacy default; histogram splits between layer 0 and
#                   max_layer.
#   "opp_default" — mixed the other way: latest layer + later round.
#                   Rarely useful; here for completeness.
#
# `_DIRECTION_TO_PAIR` is the internal map from cleaning_direction to the
# (layer_side, round_side) pair the rep-picker consumes. Not part of the
# public surface.


_DIRECTION_TO_PAIR: Dict[
    str, Tuple[Literal["input", "output"], Literal["earlier", "later"]]
] = {
    "input":       ("input",  "later"),
    "output":      ("output", "earlier"),
    "default":     ("input",  "earlier"),
    "opp_default": ("output", "later"),
}


@dataclass(frozen=True)
class CleanerConfig:
    """Configuration surface for :func:`clean_relations`.

    cleaning_direction : which round boundary the canonical reps land on.
        One of ``"input"``, ``"output"``, ``"default"``, ``"opp_default"``.
        See the comment block above for what each value means.
    debug_cross_renames : if True, emit the surviving cross-round rename pairs
        alongside the relations (debug aid only).
    strict_anchored : if True, raise when 2+ anchored variables share a class
        instead of preserving an equality chain.
    var_describer : if True, emit a glossary block after the ``end`` marker
        describing every unique representative variable that survives in the
        output. Uses the built-in describer which decomposes the OCP variable
        ID (``prefix_round_layer_word``) into a human-readable label. Cleaner
        stays cipher-agnostic — the label is based purely on the variable
        name.
    emit_debug_chains : if True, emit a ``# ---- cleaner debug: substitution
        chains ----`` block after the ``end`` marker showing how each watched
        variable (known/target/not_guessed) moved through the same-round and
        cross-round substitutions. Off by default so the file ends cleanly at
        ``end``.
    """

    cleaning_direction: CleaningDirection = "default"
    debug_cross_renames: bool = False
    strict_anchored: bool = False
    var_describer: bool = False
    emit_debug_chains: bool = False

    def __post_init__(self) -> None:
        if self.cleaning_direction not in _DIRECTION_TO_PAIR:
            raise ValueError(
                f"cleaning_direction must be one of "
                f"{sorted(_DIRECTION_TO_PAIR)}; got {self.cleaning_direction!r}"
            )

    def _resolve(self) -> Tuple[
        Literal["input", "output"], Literal["earlier", "later"]
    ]:
        """Internal: translate cleaning_direction into the (layer_side, round_side)
        pair that the rep-picker consumes."""
        return _DIRECTION_TO_PAIR[self.cleaning_direction]


_DEFAULT_CONFIG = CleanerConfig()


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


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_rename(line: str) -> bool:
    """
    A rename is a line with exactly 2 identifier-shaped variables, no '+',
    no '=>', no 'NONRENAME'.

    Example rename:    "vs_1_2_0, vs_1_3_0"
    NOT a rename:      "vs_1_2_0, vs_1_3_0, NONRENAME"
    NOT a rename:      "a, b => c"
    NOT a rename:      "a + b + c"
    NOT a rename:      "foo bar, baz qux"           — non-identifier tokens
    NOT a rename:      "0x1234, 0x5678"             — numeric literals
    """
    if "+" in line or "=>" in line or "NONRENAME" in line:
        return False
    tokens = [t.strip() for t in line.split(",") if t.strip()]
    if len(tokens) != 2:
        return False
    return all(_IDENT_RE.match(t) for t in tokens)


def _is_algebraic(line: str) -> bool:
    """Algebraic lines contain '+' but not '=>'."""
    return "+" in line and "=>" not in line


def _round_of(var: str) -> Optional[int]:
    p = parse_var(var)
    return None if p is None else p[0]


def _is_cross_round(a: str, b: str) -> bool:
    ra, rb = _round_of(a), _round_of(b)
    if ra is None or rb is None:
        return False
    return ra != rb


# ---------------------------------------------------------------------------
# ParsedInput — single result of the input-parsing step
# ---------------------------------------------------------------------------


@dataclass
class ParsedInput:
    """All structured pieces of one relation file.

    Replaces the chain _parse_sections + _separate_relations + _split_rename_pairs.
    """

    same_round_renames: List[Tuple[str, str]] = field(default_factory=list)
    cross_round_renames: List[Tuple[str, str]] = field(default_factory=list)
    non_rename_relations: List[str] = field(default_factory=list)
    known: List[str] = field(default_factory=list)
    target: List[str] = field(default_factory=list)
    not_guessed: List[str] = field(default_factory=list)


_SECTION_HEADERS = {
    "connection relations": "connection",
    "algebraic relations": "algebraic",
    "known": "known",
    "target": "target",
    "not guessed": "not guessed",
}


def parse_input(lines: List[str]) -> ParsedInput:
    """Parse raw input lines into a ParsedInput.

    Steps (preserves the original semantics exactly):
      1. Walk lines, dispatch by section header.
      2. In `connection`, split each line into rename vs non-rename.
      3. Each rename is further classified same- vs cross-round by round number.
      4. `algebraic` lines flow into non_rename_relations.
    """
    raw = {key: [] for key in _SECTION_HEADERS.values()}
    current: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lower = stripped.lower()
        if lower in _SECTION_HEADERS:
            current = _SECTION_HEADERS[lower]
            continue
        if lower == "end":
            break
        if current is not None:
            raw[current].append(stripped)

    same: List[Tuple[str, str]] = []
    cross: List[Tuple[str, str]] = []
    non_rename: List[str] = []
    for line in raw["connection"]:
        if _is_rename(line):
            tokens = [t.strip() for t in line.split(",") if t.strip()]
            if len(tokens) == 2:
                a, b = tokens
                if _is_cross_round(a, b):
                    cross.append((a, b))
                else:
                    same.append((a, b))
            continue
        non_rename.append(line)
    non_rename.extend(raw["algebraic"])

    return ParsedInput(
        same_round_renames=same,
        cross_round_renames=cross,
        non_rename_relations=non_rename,
        known=list(raw["known"]),
        target=list(raw["target"]),
        not_guessed=list(raw["not guessed"]),
    )


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------


class UnionFind:
    """Simple Union-Find with path compression."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        # Iterative two-pass find: walk to root, then compress the path.
        # Iterative form avoids Python's recursion-limit landmine on long
        # unbalanced chains (the first lookup before compression).
        if x not in self.parent:
            self.parent[x] = x
            return x
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        cur = x
        while self.parent[cur] != root:
            nxt = self.parent[cur]
            self.parent[cur] = root
            cur = nxt
        return root

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
# SubstitutionMap — typed wrapper around the rename dict
# ---------------------------------------------------------------------------

# Matches any identifier-shaped token in a relation line and rewrites it via
# the SubstitutionMap. Safe today because the emitter writes only OCP variable
# IDs (vk_*, vsk_*, vs_*, ...) into relations — never Python keywords or
# operator names. .resolve() no-ops on tokens absent from the map, so unknown
# tokens pass through unchanged. CAVEAT: if a future emitter feature ever
# writes identifier-shaped tokens that are NOT OCP variables (e.g. operator
# markers, function names) directly into relation text, this regex will
# substitute them blindly. Such tokens should either be marked structurally
# (e.g. with a leading sigil) or kept out of relation lines entirely.
_VAR_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SubstitutionMap:
    """Dict-backed var-renaming map with utility application methods."""

    __slots__ = ("_data",)

    def __init__(self, data: Optional[Dict[str, str]] = None):
        self._data: Dict[str, str] = dict(data) if data else {}

    def __bool__(self) -> bool:
        return bool(self._data)

    def __contains__(self, var: str) -> bool:
        return var in self._data

    def __getitem__(self, var: str) -> str:
        return self._data[var]

    def __setitem__(self, var: str, target: str) -> None:
        self._data[var] = target

    def as_dict(self) -> Dict[str, str]:
        """Return the raw mapping (do not mutate)."""
        return self._data

    def resolve(self, var: str) -> str:
        """Follow the substitution chain until a fixpoint."""
        seen: Set[str] = set()
        current = var
        while current in self._data and current not in seen:
            seen.add(current)
            current = self._data[current]
        return current

    def apply_to_lines(self, lines: List[str]) -> List[str]:
        """Apply substitution to every identifier-like token in each line."""
        if not self._data:
            return lines

        def replacer(match: re.Match) -> str:
            var = match.group(0)
            return self.resolve(var)

        return [_VAR_RE.sub(replacer, line) for line in lines]

    def apply_to_varlist(self, var_list: List[str]) -> List[str]:
        """Apply substitution to a list of bare variable IDs, dedup-preserving order."""
        seen: Set[str] = set()
        result: List[str] = []
        for v in var_list:
            cur = self.resolve(v)
            if cur not in seen:
                seen.add(cur)
                result.append(cur)
        return result

    @classmethod
    def compose(cls, *maps: "SubstitutionMap") -> "SubstitutionMap":
        """Compose multiple maps left-to-right.

        compose(m1, m2).resolve(v) is equivalent to m2.resolve(m1.resolve(v)).
        Returned map is independent of the inputs.
        """
        composed = cls()
        # All keys that may need resolution across the chain.
        keys: Set[str] = set()
        for m in maps:
            keys.update(m._data.keys())
        for k in keys:
            cur = k
            for m in maps:
                cur = m.resolve(cur)
            if cur != k:
                composed[k] = cur
        return composed


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


def pick_representative(
    class_: Set[str],
    *,
    same_round: bool,
    layer_side: Literal["input", "output"],
    round_side: Literal["earlier", "later"],
) -> str:
    """Choose one variable from an equivalence class to be the representative.

    Both same-round and cross-round selection share the same vk-preference and
    layer-ordering rules. They differ in how the round dimension is handled:

      * same_round=True  — every var in the class is in the same round; round
        dimension is irrelevant. Prefer vk_*; sort by (layer, word) with the
        layer ordering picked by `layer_side`.
      * same_round=False — class spans rounds. If vk_* are present, first
        filter to the winning round (earliest / latest as per `round_side`),
        then sort within that round by (layer, word) with `layer_side`. If no
        vk_* in the class, fall back to sorting the full class by round with
        the same `round_side` direction.
    """
    desc_layer = layer_side == "output"
    desc_round = round_side == "later"

    if same_round:
        vks = [v for v in class_ if v.startswith("vk_")]
        pool: Iterable[str] = vks if vks else class_
        return sorted(
            pool,
            key=lambda v: _rank_var(v, prefer_vk=True, desc_layer=desc_layer),
        )[0]

    # cross-round
    vks_with_round: List[Tuple[str, int]] = []
    for v in class_:
        if not v.startswith("vk_"):
            continue
        r = _round_of(v)
        if r is not None:
            vks_with_round.append((v, r))
    if vks_with_round:
        rounds = [r for _, r in vks_with_round]
        winning_round = max(rounds) if desc_round else min(rounds)
        vks_in_round = [v for v, r in vks_with_round if r == winning_round]
        return sorted(
            vks_in_round,
            key=lambda v: _rank_var(v, prefer_vk=True, desc_layer=desc_layer),
        )[0]

    return sorted(
        class_,
        key=lambda v: _rank_var(v, desc_round=desc_round, desc_layer=desc_layer),
    )[0]


# ---------------------------------------------------------------------------
# CollapseResult — same shape for same-round and cross-round phases
# ---------------------------------------------------------------------------


@dataclass
class CollapseResult:
    substitution: SubstitutionMap
    preserved: List[str]


# ---------------------------------------------------------------------------
# Per-class collapse policy (shared by same-round and cross-round phases)
# ---------------------------------------------------------------------------


def decide_collapse(
    class_: Set[str],
    rep: str,
    anchored: Set[str],
    targets: Set[str],
) -> Tuple[Dict[str, str], List[str]]:
    """Return (collapse_substitutions, preserved_chain_lines) for one class.

    Policy: when ≥2 distinct target variables share a class, aliasing them
    to one rep would corrupt per-S-box autoguess queries (AutoGuess would
    see the queries as a single target and return the same basis for all).
    In that case, collapse only non-anchored vars and emit an equality
    chain among the anchored ones. Otherwise collapse the whole class.

    The strict-anchored guard is *not* applied here — callers that want it
    must check `len(class_ & anchored) >= 2` and raise before calling.
    """
    sub: Dict[str, str] = {}
    preserved: List[str] = []

    anchored_in_cls = class_ & anchored
    targets_in_cls = class_ & targets

    if len(targets_in_cls) >= 2:
        for v in class_:
            if v not in anchored_in_cls and v != rep:
                sub[v] = rep
        keep = sorted(anchored_in_cls | {rep}, key=lambda v: _rank_var(v))
        for i in range(len(keep) - 1):
            preserved.append(f"{keep[i]}, {keep[i + 1]}")
    else:
        for v in class_:
            if v != rep:
                sub[v] = rep

    return sub, preserved


# ---------------------------------------------------------------------------
# Same-round collapse
# ---------------------------------------------------------------------------


def collapse_same_round(parsed: ParsedInput, config: CleanerConfig) -> CollapseResult:
    """Build same-round Union-Find, pick reps, apply per-class collapse policy.

    The only same-round-specific behavior here is the `strict_anchored` guard:
    raise if a class contains 2+ anchored variables (i.e., a SAT-level conflict
    the user wants surfaced rather than papered over by chain preservation).
    """
    uf = UnionFind()
    for a, b in parsed.same_round_renames:
        uf.union(a, b)

    anchored = set(parsed.known) | set(parsed.target) | set(parsed.not_guessed)
    targets = set(parsed.target)

    sub_map = SubstitutionMap()
    preserved: List[str] = []

    layer_side, round_side = config._resolve()
    for cls in uf.get_classes():
        if not cls:
            continue
        rep = pick_representative(
            cls,
            same_round=True,
            layer_side=layer_side,
            round_side=round_side,
        )

        if config.strict_anchored:
            anchored_in_cls = cls & anchored
            if len(anchored_in_cls) >= 2:
                raise RuntimeError(
                    f"Anchored conflict: {sorted(anchored_in_cls)} "
                    f"in class {sorted(cls)}"
                )

        cls_sub, cls_preserved = decide_collapse(cls, rep, anchored, targets)
        for k, v in cls_sub.items():
            sub_map[k] = v
        preserved.extend(cls_preserved)

    return CollapseResult(substitution=sub_map, preserved=preserved)


# ---------------------------------------------------------------------------
# Cross-round collapse
# ---------------------------------------------------------------------------


def collapse_cross_round(
    parsed: ParsedInput,
    same_substitution: SubstitutionMap,
    config: CleanerConfig,
) -> CollapseResult:
    """Cross-round equivalence classes after the same-round substitution.

    Walks the cross-round renames through `same_substitution`, unions the
    post-same images, picks a rep per class with `pick_representative`, then
    defers the collapse-or-preserve decision to `decide_collapse`.
    """
    uf = UnionFind()
    for a, b in parsed.cross_round_renames:
        ra = same_substitution.resolve(a)
        rb = same_substitution.resolve(b)
        if ra != rb:
            uf.union(ra, rb)

    anchored_post_same = {
        same_substitution.resolve(v)
        for v in set(parsed.known) | set(parsed.target) | set(parsed.not_guessed)
    }
    targets_post_same = {same_substitution.resolve(v) for v in parsed.target}

    sub_map = SubstitutionMap()
    preserved: List[str] = []

    layer_side, round_side = config._resolve()
    for cls in uf.get_classes():
        if not cls:
            continue

        rep = pick_representative(
            cls,
            same_round=False,
            layer_side=layer_side,
            round_side=round_side,
        )

        if config.strict_anchored:
            anchored_in_cls = cls & anchored_post_same
            if len(anchored_in_cls) >= 2:
                raise RuntimeError(
                    f"Anchored conflict (cross-round): {sorted(anchored_in_cls)} "
                    f"in class {sorted(cls)}"
                )

        cls_sub, cls_preserved = decide_collapse(
            cls, rep, anchored_post_same, targets_post_same
        )
        for k, v in cls_sub.items():
            sub_map[k] = v
        preserved.extend(cls_preserved)

    return CollapseResult(substitution=sub_map, preserved=preserved)


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------


def _remove_trivial(lines: List[str]) -> List[str]:
    """Remove relations like 'x, x' (but keep implications and algebraic).

    Also rewrites lines whose tokens contain duplicates (e.g. ``a, a, b``
    after substitution) into their deduplicated form (``a, b``). Without
    this rewrite, the duplicate-token form survived to AutoGuess.
    """
    result = []
    for line in lines:
        if "=>" in line or "+" in line:
            result.append(line)
            continue
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        seen: Set[str] = set()
        uniq: List[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        if len(uniq) >= 2:
            result.append(", ".join(uniq) if len(uniq) != len(tokens) else line)
    return result


_NONRENAME_MARKER_RE = re.compile(r"\s*,\s*NONRENAME\s*$")


def _strip_nonrename_markers(lines: List[str]) -> List[str]:
    """Remove a trailing ", NONRENAME" marker from each line.

    Tolerant of surrounding whitespace (e.g. ``"a, b ,  NONRENAME "``) so we
    don't quietly leave the marker in place if the emitter ever changes the
    spacing.
    """
    return [_NONRENAME_MARKER_RE.sub("", line) for line in lines]


def _debug_cross_rename_lines(
    parsed: ParsedInput,
    same_sub: SubstitutionMap,
    cross_sub: SubstitutionMap,
) -> List[str]:
    """Compute the (debug-only) list of cross-round rename edges after both subs."""
    edges: Set[Tuple[str, str]] = set()
    for a, b in parsed.cross_round_renames:
        ra = cross_sub.resolve(same_sub.resolve(a))
        rb = cross_sub.resolve(same_sub.resolve(b))
        if ra != rb:
            pair = (ra, rb) if ra <= rb else (rb, ra)
            edges.add(pair)
    return [f"{x}, {y}" for x, y in sorted(edges)]


def _builtin_describer(var: str) -> Optional[str]:
    """Decompose an OCP variable ID into a human-readable label.

    Recognises the three OCP prefixes we encounter in cleaner inputs:
      vk_R_L_P   → "KS state round R, layer L, position P"
      vsk_R_L_P  → "subkey of round R, bit P" (subkey vars always L=0)
      vs_R_L_P   → "cipher state round R, layer L, position P"
    Falls back to a bare "(R, L, P)" tuple for any other prefix.
    Returns ``None`` if the variable doesn't parse as ``prefix_R_L_P``.
    """
    p = parse_var(var)
    if p is None:
        return None
    r, l, w = p
    if var.startswith("vk_"):
        return f"KS state round {r}, layer {l}, position {w}"
    if var.startswith("vsk_"):
        return f"subkey of round {r}, bit {w}"
    if var.startswith("vs_"):
        return f"cipher state round {r}, layer {l}, position {w}"
    return f"round {r}, layer {l}, position {w}"


def _collect_surviving_vars(
    non_rename: List[str],
    preserved: List[str],
    known: List[str],
    target: List[str],
    not_guessed: List[str],
) -> List[str]:
    """Return unique identifier-shaped tokens appearing in the final output.

    Order = first-appearance. Covers the same lines `_format_output` writes:
    relations (real + preserved), and the three bare-var sections.
    """
    seen: Set[str] = set()
    result: List[str] = []

    def visit(token: str) -> None:
        if token not in seen:
            seen.add(token)
            result.append(token)

    for line in non_rename:
        for m in _VAR_RE.finditer(line):
            visit(m.group(0))
    for line in preserved:
        for m in _VAR_RE.finditer(line):
            visit(m.group(0))
    for v in known:
        visit(v)
    for v in target:
        visit(v)
    for v in not_guessed:
        visit(v)
    return result


def _substitution_chain(var: str, maps: List[SubstitutionMap]) -> List[str]:
    """Return chain [var, after-map-1, after-map-2, ...] for debug output.

    One entry per stage, even when a stage is a no-op, so the reader can
    distinguish "stage didn't move this var" from "stage was skipped."
    Always returns ``len(maps) + 1`` entries.
    """
    chain = [var]
    cur = var
    for m in maps:
        cur = m.resolve(cur)
        chain.append(cur)
    return chain


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
    connection = []
    algebraic = []
    for line in non_rename:
        if _is_algebraic(line):
            algebraic.append(line)
        else:
            connection.append(line)

    connection.extend(preserved)
    connection = _strip_nonrename_markers(connection)
    algebraic = _strip_nonrename_markers(algebraic)

    output: List[str] = []
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


def rewrite_and_format(
    parsed: ParsedInput,
    substitution: SubstitutionMap,
    preserved: List[str],
    config: CleanerConfig,
    *,
    same_sub: SubstitutionMap,
    cross_sub: SubstitutionMap,
) -> List[str]:
    """Apply the composed substitution to all relations, format with headers.

    `same_sub` and `cross_sub` are kept around for debug_cross_renames and the
    end-of-file substitution-chain dump; pass them in rather than recomputing.
    """
    non_rename = substitution.apply_to_lines(parsed.non_rename_relations)
    non_rename = _remove_trivial(non_rename)

    known = substitution.apply_to_varlist(parsed.known)
    target = substitution.apply_to_varlist(parsed.target)
    not_guessed = substitution.apply_to_varlist(parsed.not_guessed)

    # Drop `not_guessed` entries that collide with `known` post-substitution
    # (contradictory at SAT level). We intentionally do NOT dedup target vs
    # known — silent target loss would mask a class of aliasing bugs.
    known_set = set(known)
    not_guessed = [v for v in not_guessed if v not in known_set]

    full_preserved = list(preserved)
    if config.debug_cross_renames:
        full_preserved.extend(_debug_cross_rename_lines(parsed, same_sub, cross_sub))

    output = _format_output(non_rename, full_preserved, known, target, not_guessed)

    # Variable glossary (optional, opt-in via CleanerConfig.var_describer=True).
    # Placed AFTER `end` and BEFORE the substitution-chain debug block so the
    # core relation file remains exactly what AutoGuess sees.
    if config.var_describer:
        glossary = ["# ---- variable glossary ----"]
        for v in _collect_surviving_vars(
            non_rename, full_preserved, known, target, not_guessed
        ):
            desc = _builtin_describer(v)
            if desc is not None:
                glossary.append(f"# {v} = {desc}")
        glossary.append("# ---- end glossary ----")
        output.extend(glossary)

    # Debug substitution chains after 'end' (off by default — file ends at 'end').
    if config.emit_debug_chains:
        watch = list(dict.fromkeys(parsed.known + parsed.target + parsed.not_guessed))
        debug = []
        debug.append("# ---- cleaner debug: substitution chains ----")
        debug.append(f"# cleaning_direction={config.cleaning_direction}")
        debug.append("# format: original -> after same-round -> after cross-round")
        for v in watch:
            chain = _substitution_chain(v, [same_sub, cross_sub])
            if chain[0] != chain[-1]:
                debug.append("# " + " -> ".join(chain))
        debug.append("# ---- end debug ----")
        output.extend(debug)
    return output


# Public entry point


def clean_relations(
    lines: List[str],
    *,
    config: Optional[CleanerConfig] = None,
) -> List[str]:
    """Clean relations by collapsing renames.

    Pass ``config=CleanerConfig(...)`` to control the cleaner. When None,
    the module-level default (``cleaning_direction="default"``) is used.
    """
    if config is None:
        config = _DEFAULT_CONFIG

    parsed = parse_input(lines)
    same = collapse_same_round(parsed, config)
    cross = collapse_cross_round(parsed, same.substitution, config)
    substitution = SubstitutionMap.compose(same.substitution, cross.substitution)
    return rewrite_and_format(
        parsed,
        substitution,
        same.preserved + cross.preserved,
        config,
        same_sub=same.substitution,
        cross_sub=cross.substitution,
    )
