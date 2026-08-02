# AutoGuess Usage Guide

A minimal reference for running guess-and-determine attacks via OCP's AutoGuess integration.

The entry point follows the same shape as every other OCP attack (`diff_attacks`,
`linear_attacks`, `integral_attacks`): a cipher, a `goal`, an `objective_target`,
a `show_mode`, and two plain configuration dicts.

## Quick start

```python
from attacks import attacks
import primitives.aes as aes

cipher = aes.AES_BLOCKCIPHER(2, [128, 128])
func   = cipher.functions["PERMUTATION"]

# Known: the plaintext (round-1 input) and the ciphertext (last-round output).
known_vars = [v.ID for v in func.vars[1][0]] + [v.ID for v in func.vars[func.nbr_rounds][1]]

result = attacks.guess_and_determine_attack(
    cipher,
    known_vars=known_vars,
    objective_target="AT MOST 6",
    config_model={"skip_rounds": [2], "maxsteps": 14},
)
```

Recovers the full 96-variable state from 6 guesses in 14 steps.
`result["guessed_variables"]`, `result["determination_steps"]`, and the output
files (below) are everything you need.

Both bounds matter. Left to their defaults, `maxguess` is the number of targets
and `maxsteps` is the number of variables; on most ciphers the first is too
tight and the search returns no solution. If you get "no feasible solution
found", raise `objective_target` and `config_model["maxsteps"]` before
concluding anything.

## Function signature

`attacks.guess_and_determine_attack` is a thin timing wrapper over
`attacks.guess_and_determine.search_guess_basis`; both take the same arguments:

```python
guess_and_determine_attack(
    cipher,                         # cipher (has .functions) or single function
    goal="GUESSBASIS",              # GUESSBASIS | REDUCEBASIS
    known_vars=None,                # list[str] of variable IDs initially known
    target_vars=None,               # list[str] of IDs to determine
    not_guessed_vars=None,          # list[str] forbidden from being guessed
    protect_all_targets=False,      # True = key recovery (no target may be guessed)
    objective_target="EXISTENCE",   # EXISTENCE | OPTIMAL | "AT MOST X"
    show_mode=0,                    # 0-3 output detail
    config_model=None,              # dict: relation-generation / encoding options
    config_solver=None,             # dict: solver backend options
)
```

Unlike the trail searches there is no `constraints` argument: the problem is
stated through the `known_vars` / `target_vars` / `not_guessed_vars` roles.

### `goal`

`goal` is which question you are asking AutoGuess — the same slot that
`"DIFFERENTIALPATH_PROB"` and friends occupy in the other OCP attacks.

| Value | Meaning |
|---|---|
| `"GUESSBASIS"` | Find a set of variables whose values, once guessed, let every remaining variable be deduced by propagation (default) |
| `"REDUCEBASIS"` | Start from the basis passed in `known_vars` and drop the members that turn out to be redundant. Requires `known_vars`, and forces the `propagate` backend regardless of `config_model["model_type"]` |

### `objective_target`

| Value | Meaning |
|---|---|
| `"EXISTENCE"` | One solve: return any guess basis that fits the automatic bound (`maxguess` = number of targets), no minimisation (default) |
| `"OPTIMAL"` | Repeated solves: iterate the guess count down to the smallest one that is still satisfiable |
| `"AT MOST X"` | One solve with `maxguess = X`: return any basis of size ≤ X, or nothing if none exists |

Mechanically these set just two AutoGuess flags — `(findmin, maxguess)` =
`(False, None)`, `(True, None)`, `(False, X)`.

OCP's `"EXACTLY X"` and `"AT LEAST X"` have no AutoGuess counterpart and raise `ValueError`.

### `show_mode`

| Value | Output |
|---|---|
| `0` | Results only |
| `1` | + determination-flow graph |
| `2` | + solver log |
| `3` | + TikZ source |

## Configuration

Both configs are plain dicts. An unrecognised key raises `ValueError` listing the accepted ones.

### `config_model` — relation generation and encoding

| Key | Default | Description |
|---|---|---|
| `model_type` | `"sat"` | `sat \| milp \| smt \| cp \| mark \| elim \| propagate` — the framework the problem is encoded into |
| `filename` | auto | Relation-file path; relative paths resolve under `test/autoguess/files/` |
| `name_prefix` | `None` | Prefix for the auto-generated filename |
| `maxsteps` | `None` | Determination depth (auto = #variables) |
| `skip_layers` | `None` | Layers to skip (friendly names below, or class names like `XOR`, `Equal`) |
| `skip_ops` | `None` | Operation class names to skip |
| `skip_rounds` | `None` | Round indices to skip; gaps auto-bridged |
| `skip_functions` | `None` | Function names to skip (full-cipher mode only) |
| `sbox_form` | `None` | `"rename"` or `"implication"`; `None` infers from the wiring shape |
| `algebraic_layers` | `None` | Class names emitted algebraically (e.g. `["MatrixLayer"]`) |
| `perm_rename` | `True` | Collapse permutation Equals via renaming |
| `rot_rename` | `True` | Same for rotations |
| `gf2linear_rename` | `True` | Same for GF2-linear ops |
| `cleaning_direction` | `None` | `"input"` / `"output"` / `"default"` / `"opp_default"`; which round boundary the canonical reps land on |
| `bridge_skipped_rounds` | `True` | Equate values across skipped rounds |
| `emit_debug_chains` | `False` | Emit rename-chain diagnostics |

### `config_solver` — backend

| Key | Default | Description |
|---|---|---|
| `solver` | `"DEFAULT"` | Concrete backend. Resolves per `model_type`: `cadical153` (sat), `z3` (smt), `cp-sat` (cp). Ignored (with a warning) for `milp` / `mark` / `elim` / `propagate`, which expose no backend choice |
| `timelimit` | `-1` | Per-solve timeout in seconds; `-1` = none |
| `threads` | `0` | `0` = auto |
| `preprocess` | `0` | Macaulay preprocess |
| `milpdirection` | `"min"` | `min` or `max` |
| `cpoptimization` | `1` | `1` = optimize, `0` = decision |
| `dglayout` | `"dot"` | Determination-graph layout |

`findmin`, `maxguess`, `reducebasis`, `drawgraph`, `tikz` and `log` are **not** set
here — they are derived from `objective_target`, `goal` and `show_mode`.

Solver picker (general guidance): `sat` for most problems; `cp` when SAT is too rigid; `propagate` for pure deduction without optimization; `mark` / `elim` for the marking and elimination algorithms; `milp` for weighted/optimization-shaped problems.

## Output files

All artifacts land under `test/autoguess/files/` (gitignored). For `cipher.name="AES128"`, 3 modeling rounds:

| Artifact | Path |
|---|---|
| Dirty (uncleaned) relations | `test/autoguess/files/temp/dirty_relations_AES128_3r.txt` |
| Cleaned relations (input to AutoGuess) | `test/autoguess/files/relations_AES128_3r.txt` |
| Text report | `test/autoguess/files/output_AES128_3r` *(no extension)* |
| Graphviz source | `test/autoguess/files/output_AES128_3r_graph` *(no extension)* |
| Determination-flow PDF | `test/autoguess/files/output_AES128_3r_graph.pdf` |
| TikZ (only at `show_mode=3`) | `test/autoguess/files/output_AES128_3r_graph.tex` |
| Solver intermediates (only at `show_mode>=2`) | `test/autoguess/files/temp/…` |

Setting `config_model["name_prefix"]` inserts the prefix: `relations_<prefix>_AES128_3r.txt`.
The output stem is derived from the relation filename by replacing `relations_` with `output_`.

Graph node colors: blue = known, red = guessed, green = derived.

## Returned dict

```python
{
    "outputfile":          "<absolute path>",
    "cipher":              <input cipher/function>,
    "known_variables":     [Variable, ...],
    "target_variables":    [Variable, ...],
    "guessed_variables":   [Variable, ...],
    "determination_steps": [{"step": 0, "determined_vars": [Variable, ...]}, ...],
}
```

## Common patterns

**Key-schedule analysis (single function, custom name):**

```python
ks = cipher.functions["KEY_SCHEDULE"]
result = attacks.guess_and_determine_attack(
    ks,
    target_vars=[ks.vars[r][0][j].ID for (r, j) in known_pairs],
    objective_target="AT MOST 60",
    config_model={
        "model_type": "cp",
        "name_prefix": "present_ks",
        "sbox_form": "implication",
        "maxsteps": 10,
    },
    config_solver={"preprocess": 1},
)
```

**Skip rounds / focus on the non-linear core:**

```python
config_model={"skip_rounds": [1, 2, 20], "skip_layers": ["MatrixLayer", "RotationLayer"]}
```

**Find the minimum guess basis (incremental SAT):**

```python
objective_target="OPTIMAL", config_model={"model_type": "sat"}
```

**Reduce a known basis via propagation:**

```python
result = attacks.guess_and_determine_attack(
    cipher,
    goal="REDUCEBASIS",
    known_vars=initial_basis,
)
```

**Publication-quality TikZ:**

```python
show_mode=3, config_solver={"dglayout": "dot"}
```

## Skip-layer reference

Friendly names accepted by `skip_layers` / `skip_ops`:

| Friendly name | Underlying op classes |
|---|---|
| `AddConstantLayer` | `ConstantXOR`, `ConstantAdd` |
| `AddIdentityLayer` | `Equal` (IDs starting `ID_`) |
| `PermutationLayer` | `Equal` (IDs starting `PERM_EQ_`, `SR_EQ_`, `K_PERM_EQ_`, …) |
| `RotationLayer` / `ShiftLayer` | `Rot` / `Shift` |
| `XORLayer` / `ANDLayer` / `ORLayer` / `NOTLayer` | `XOR`/`N_XOR`, `AND`, `OR`, `NOT` |
| `SboxLayer` | All S-box classes, plus `Equal` with `SB_EQ_`/`SBOX_EQ_`/`SBX_EQ_` IDs |
| `MatrixLayer` | `Matrix` (the MDS state layer) |
| `LFSRLayer` | `GF2Linear_Trans` (tweakey-schedule word matrix) |
| `ModAddLayer` / `ModMulLayer` | `ModAdd` / `ModMul` |
| `CopyLayer` | `CopyOperator`, `COPY` |

Direct class names (e.g. `"XOR"`, `"Matrix"`) and ID prefixes (e.g. `"K_PERM"`) are also accepted.

## Lower-level entry points

If you need to drive the two stages independently:

```python
from tools.relation_generator import generate_relations
from tools.autoguess_wrapper   import run_autoguess
```

`generate_relations` produces the `relations_*.txt` file; `run_autoguess` consumes it and writes the report and graph. `search_guess_basis` is orchestration over these two: it translates `config_model` into `generate_relations` keywords and `config_solver` + `goal` + `objective_target` + `show_mode` into `run_autoguess` keywords.

## Notes / gotchas

- The Groebner-basis solver is **not** available in this no-Sage variant. Use the upstream AutoGuess if you need it.
- If `target_vars` is set and `not_guessed_vars` doesn't already exclude them, the first target is auto-protected so the trivial all-targets-guessed solution can't win. Set `protect_all_targets=True` to protect every target (key-recovery mode).
- Relative paths in `config_model["filename"]` are resolved against `test/autoguess/files/`.
- The relation file is named from the cipher and modelling options only, not from `goal` or `objective_target` — runs that differ only in objective deliberately reuse it.
