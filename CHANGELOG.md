# Changelog

## 2026-08-02 — guess-and-determine follows the OCP attack convention

**Breaking.** `guess_and_determine_attack` / `search_guess_basis` now take the
same arguments as every other OCP attack entry point, instead of `*args,
**kwargs` over two dataclasses. Behaviour is unchanged: the kwargs reaching
`generate_relations` and `run_autoguess` are identical before and after for all
seven scripts in `test/autoguess/`.

**New signature:**

```python
guess_and_determine_attack(cipher, goal="GUESSBASIS", known_vars=None,
                           target_vars=None, not_guessed_vars=None,
                           protect_all_targets=False, objective_target="EXISTENCE",
                           show_mode=0, config_model=None, config_solver=None)
```

**Migration:**

- `relgen_cfg=RelGenConfig(**kw)` → `config_model={**kw}`
- `solver_cfg=SolverConfig(solver=F)` → `config_model={"model_type": F}`
- `solver_cfg=SolverConfig(satsolver=B)` → `config_solver={"solver": B}`
- `SolverConfig(maxguess=N)` → `objective_target="AT MOST N"`
- `SolverConfig(findmin=True)` → `objective_target="OPTIMAL"`
- `SolverConfig(reducebasis=True)` → `goal="REDUCEBASIS"`
- `SolverConfig(maxsteps=N)` → `config_model={"maxsteps": N}`
- `name_prefix=P` / `output_file=F` → `config_model={"name_prefix": P}` / `{"filename": F}`
- `drawgraph` / `tikz` / `log` → `show_mode` (0 results, 1 +graph, 2 +log, 3 +tikz).
  The old defaults (`drawgraph=True`, `log=0`) correspond to `show_mode=1`.

`RelGenConfig` and `SolverConfig` still exist but are internal plumbing;
callers no longer import them.

**Also:**

- Unknown `config_model` / `config_solver` keys now raise `ValueError` listing
  the accepted keys, instead of being silently ignored.
- The relation-file path is resolved once up front rather than derived in two
  places; it is named from the cipher and modelling options only, so runs
  differing only in objective reuse it.
- `test/autoguess/files/` is now gitignored.
- `autoguess_usage_guide.md` rewritten. Beyond the API change it also corrected
  pre-existing errors: `flat_sbox` / `canonical` / `cross_round_dir` were listed
  as `RelGenConfig` fields but do not exist (the real ones are `sbox_form` and
  `cleaning_direction`); the graph artifacts are `*_graph` and `*_graph.pdf`,
  not `*_graph.gv` / `*_graph.gv.pdf`; `MatrixLayer` covers `Matrix` only, with
  `GF2Linear_Trans` under `LFSRLayer`; and the quick-start example returned no
  solution because it relied on the default `maxguess`.

## 2026-05-13 — audit fixes in cleaner + emitter

Eleven issues from an external review were addressed. The one rejected
item (audit #5: dedup target ∩ not_guessed) is intentionally NOT a bug —
`protect_all_targets=True` requires the overlap to forbid targets from
being guessed; deduping it would silently disable that protection
(already documented in the 2026-05-09 entry).

**Cleaner (`tools/relation_generator_modules/cleaner.py`):**

- [#1] `strict_anchored` is now enforced in `collapse_cross_round` too,
  matching `collapse_same_round`. Cross-round equivalence classes
  containing 2+ anchored variables raise `RuntimeError` when the
  flag is on.
- [#4] `_is_rename` now requires both tokens to be identifier-shaped
  (matching `[A-Za-z_][A-Za-z0-9_]*`). Numeric literals or other
  2-token comma lines that slipped past the old length-only check
  are no longer misclassified as renames.
- [#7] `_remove_trivial` deduplicates tokens within a line and emits
  the deduped form. `a, a, b` (which can arise post-substitution)
  now becomes `a, b` instead of surviving verbatim.
- [#8] `_strip_nonrename_markers` now uses a whitespace-tolerant
  regex (`,\s*NONRENAME\s*$`) instead of an exact-string `.replace`.

**Emitter (`tools/relation_generator_modules/emitter.py`):**

- [#2] `gen_autoguess_constr` exceptions are no longer swallowed into
  a `# Error …` comment line. They now propagate as `RuntimeError`
  with op/round/layer context, so genuine op bugs become visible
  instead of disappearing.
- [#3] `Equal` ops are routed as always-rename
  (`treat_as_nonrename=False`) regardless of the
  `perm_rename`/`rot_rename`/`gf2linear_rename` toggles. Previously
  `Equal` was bucketed with permutations, so `perm_rename=False`
  also forced LINK_EQ and identity-layer ops to NONRENAME — wrong,
  because `Equal` is an equality by definition.
- [#6] Built-in `LINK_EQ` is now stripped **only** when one of its
  round endpoints is in `skip_round_set`. The previous logic
  stripped ALL `LINK_EQ` whenever any round was skipped, throwing
  away legitimate intra-active connections that the gap-linker had
  to rebuild for no reason.
- [#9] `emit_function` raises `ValueError` when `nbr_rounds` or
  `nbr_layers` is missing/invalid instead of silently emitting an
  empty relation list (defaults were `0` / `-1`).
- [#10] Non-int entries in `skip_rounds` now raise `TypeError`. The
  old `isinstance(int)` filter silently dropped string/bool entries,
  so a typo like `skip_rounds=["3"]` produced no skip and no warning.
- [#11] `zip(..., strict=True)` in the gap-linker's three loops, with
  the surrounding `try/except` narrowed to
  `(IndexError, KeyError, AttributeError)` so a width mismatch
  surfaces as `ValueError` instead of being silently truncated.
- [#12] `emit_cipher` restores the caller's `kwargs["skip_rounds"]`
  inside a `try/finally`, so the mapping isn't left mutated when
  `emit_function` raises mid-loop.

**Smoke-tested with `/tmp/relgen_sweep.py` after the changes: 400 OK,
1 pre-existing SHACAL2 primitive bug unrelated to these fixes.**
SKINNY-TK2 boundary diagnostic histograms unchanged: `default {0:4,3:15}`,
`input {0:19}`, `output {3:19}`, `opp_default {0:16,2:3}`.

## 2026-05-12 — single-knob `cleaning_direction` + legacy removal

**Breaking.** `RelGenConfig`, `generate_relations`, and `CleanerConfig`
now expose only `cleaning_direction` — the four-way enum that selects
which round boundary the canonical reps land on. The legacy trio
(`canonical`, `cross_round_dir`, `boundary_naming`) has been removed.

- `CleanerConfig`:
    - Removed fields: `layer_side`, `round_side`.
    - New field: `cleaning_direction: Literal["input", "output", "default",
      "opp_default"] = "default"`.
    - `__post_init__` validates the value; `_resolve()` maps it to the
      internal `(layer_side, round_side)` pair the rep-picker consumes.
- `clean_relations(lines, *, config=...)`:
    - Legacy kwargs (`canonical`, `cross_round_dir`, `boundary_naming`,
      `debug_cross_renames`, `strict_anchored`) **removed**. The
      `DeprecationWarning` shim from 2026-05-10 is gone.
    - Pass `config=CleanerConfig(...)` or omit for the default.
- `tools/relation_generator.generate_relations`:
    - Removed parameters: `canonical`, `cross_round_dir`, `boundary_naming`.
    - Kept: `cleaning_direction`, `debug_cross_renames`, `strict_anchored`.
- `RelGenConfig`:
    - Removed fields: `canonical`, `cross_round_dir`, `boundary_naming`.
    - Kept: `cleaning_direction`.
- `test/autoguess/boundary_diagnostic.py` updated to drive all four
  corners via `cleaning_direction`.

**Migration cheat sheet for user scripts:**

| Old | New |
|---|---|
| `boundary_naming="input"` | `cleaning_direction="input"` |
| `boundary_naming="output"` | `cleaning_direction="output"` |
| (default; no flag) | `cleaning_direction="default"` (or omit) |
| `canonical=True, cross_round_dir=True` | `cleaning_direction="input"` |
| `canonical=False, cross_round_dir=False` | `cleaning_direction="output"` |
| `canonical=False, cross_round_dir=True` | `cleaning_direction="opp_default"` |

`automated_key_recovery/` is **not** mirrored — it tracks its own
cleaner pipeline at user request.

## 2026-05-10 — cleaner.py refactor + caller migration

**The cleaner now has a structured `CleanerConfig` API and a 4-stage
pipeline (`parse_input` → `collapse_same_round` → `collapse_cross_round`
→ `rewrite_and_format`). Callers updated to the new surface; legacy
keyword arguments still work with a `DeprecationWarning`.**

- New public types in `tools/relation_generator_modules/cleaner.py`:
  `CleanerConfig`, `ParsedInput`, `SubstitutionMap`, `CollapseResult`.
- `CleanerConfig` fields:
    - `layer_side: "input" | "output"` — replaces the old `canonical`
      bool. `"input"` ≡ `canonical=True` (earliest layer wins);
      `"output"` ≡ `canonical=False` (latest layer wins).
    - `round_side: "earlier" | "later"` — replaces the old
      `cross_round_dir` bool. `"earlier"` ≡ `cross_round_dir=False`;
      `"later"` ≡ `cross_round_dir=True`.
    - `debug_cross_renames`, `strict_anchored`, `var_describer`.
- `clean_relations(lines, config=CleanerConfig(...))` is the preferred
  call. Legacy kwargs (`canonical`, `cross_round_dir`, `boundary_naming`,
  `debug_cross_renames`, `strict_anchored`) still work but emit a
  `DeprecationWarning`. Mixing `config=` with legacy kwargs raises
  `TypeError`.
- `decide_collapse` now preserves an equality chain only when **≥2
  distinct targets** share a class (previously: ≥2 anchored vars of any
  section). Other anchored mixes (e.g. known + not_guessed) collapse to
  one rep, since the SAT-level guarantees only matter for keeping
  distinct targets distinct.
- `UnionFind.find` is now iterative (was recursive) — removes the
  Python-recursion-limit landmine on long chains.
- `tools/relation_generator.py` and
  `automated_key_recovery/tools/relation_generator.py` both translate
  their legacy flags (`canonical`, `cross_round_dir`, `boundary_naming`)
  into a `CleanerConfig` and pass `config=` to `clean_relations`, so
  pipeline runs no longer trip the `DeprecationWarning`.
- `RelGenConfig` user-facing fields are unchanged.
  Existing scripts that pass `canonical=`, `cross_round_dir=`, or
  `boundary_naming=` to `RelGenConfig(...)` keep working with no
  changes.
- `automated_key_recovery/tools/relation_generator_modules/cleaner.py`
  is mirrored from the outer copy — no drift between the two trees.

## 2026-05-09 — `cleaner.py` (revert + proper orphan fix)

**Revert of the 2026-04 dense-anchor collapse — the original
preserved-equality-chain behavior is restored. The orphan-leak bug
that motivated the collapse is now patched at its true source.**

- `_build_same_round_map` (dense-anchor branch, 2+ anchored vars in one
  same-round class) once again keeps distinct anchored vars in the output
  via an explicit equality chain among `anchored_in_cls ∪ {rep}`. The
  collapse-everything behavior added in 2026-04 mis-merged distinct
  target IDs that happened to share a rename equivalence class —
  downstream verifiers that check per-ID derivability could not find
  the merged-away IDs.
- The orphan leak (e.g. `vs_2_0_0` surviving in a preserved rename line
  but renamed to a different rep in `not_guessed` via cross-round
  substitution) is fixed in `clean_relations` by running `preserved_same`
  through `cross_map` and `_remove_trivial` — same as `non_rename`. This
  keeps preserved chains in sync with the anchored sections instead of
  letting them go stale.



## 2026-04 — `relation_generator_modules/cleaner.py`

**Dense-anchor same-round equivalence classes now collapse to a single
representative instead of preserving an equality chain.**

- Affected function: `_build_same_round_map`.
- Previous behavior: when 2+ anchored variables (members of `known`,
  `target`, or `not_guessed`) landed in the same same-round equivalence
  class, the cleaner kept all of them distinct and emitted equality-chain
  rename lines among them.
- Problem: under dense anchoring (e.g. `trail_to_key_recovery` placing
  every state variable into `not_guessed`), the preserved-chain pass did
  not coordinate with the cross-round substitution pass. Orphaned IDs
  like `vs_2_0_0` survived in preserved rename lines but were never
  substituted in the `not_guessed` section, so AutoGuess saw them as
  free variables and "guessed" state cells, producing spurious state-
  variable leakage in the reported guess basis.
- New behavior: collapse the entire class to one representative, same as
  the 0/1-anchored case. Mathematically sound — anchored vars in the same
  rename class are asserted equal by construction, so distinguishing them
  was never information-bearing.
- Introduced in commit `0c03653` ("updated the code base").

## 2026-05 — `cleaner.py`, `relation_generator.py`, `RelGenConfig`

- New `boundary_naming: "input" | "output" | None` parameter on
  `clean_relations`, `generate_relations`, and `RelGenConfig`. When set,
  it pins `canonical` and `cross_round_dir` to a consistent pair so the
  boundary basis is reported under a single naming convention.
- Documented that the default raw flag pair
  (`canonical=True, cross_round_dir=False`) is a mixed convention.
- Removed dead `# ORIGINAL PRESERVED-CHAIN LOGIC` block from
  `_build_same_round_map` (rationale moved to the 2026-04 entry above).
- Removed unused `cross_round` parameter from `_choose_rep`.
- Post-substitution dedup: drops entries from `target` that collide with
  `known` (already-known targets are already achieved). The original
  `known` ∩ `not_guessed` dedup is preserved. Note: `target` ∩ `not_guessed`
  is intentionally NOT deduped because `protect_all_targets=True` in
  `search_guess_basis` adds every target to `not_guessed` on purpose;
  dropping the overlap would silently disable the protection.
- `canonical` and `cross_round_dir` are now `Optional[bool]` with default
  `None` ("use default") on `clean_relations`, `generate_relations`, and
  `RelGenConfig`. When `boundary_naming` is set, passing an explicit
  non-None value that conflicts with the forced setting issues a
  `UserWarning` instead of silently overriding. Default behavior unchanged
  for callers that don't explicitly set these flags.
