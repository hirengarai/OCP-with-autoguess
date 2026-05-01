# AutoGuess Usage Guide

A minimal reference for running guess-and-determine attacks via OCP's AutoGuess integration.

## Quick start

```python
from attacks import attacks
from attacks.guess_and_determine import RelGenConfig, SolverConfig
import primitives.aes as aes

cipher = aes.AES_block_cipher("aes", [128, 128], inp, key, outp, nbr_rounds=2)
func   = cipher.functions["PERMUTATION"]
known  = [v.ID for v in func.vars[1][0]]

result = attacks.guess_and_determine_attack(
    func,
    target_vars=known,
    solver_cfg=SolverConfig(solver="sat", maxguess=20, findmin=True),
)
```

That's it — `result["guessed_variables"]`, `result["determination_steps"]`, and the output files (below) are everything you need.

## Function signature

`attacks.guess_and_determine_attack(*args, **kwargs)` is a thin timing wrapper over `attacks.guess_and_determine.search_guess_basis`:

```python
search_guess_basis(
    cipher_or_function,             # cipher (has .functions) or single function
    *,
    known_vars=None,                # list[str] of variable IDs initially known
    target_vars=None,               # list[str] of IDs to determine
    not_guessed_vars=None,          # list[str] forbidden from being guessed
    protect_all_targets=False,      # True = key recovery (no target may be guessed)
    name_prefix=None,               # auto-generated filename prefix
    output_file=None,               # explicit relation-file path (overrides auto-naming)
    relgen_cfg=RelGenConfig(),      # relation-generation options
    solver_cfg=SolverConfig(),      # AutoGuess solver options
)
```

## Configuration

### `RelGenConfig` — relation generation

| Field | Default | Description |
|---|---|---|
| `skip_layers` | `None` | Layers to skip (friendly names: `MatrixLayer`, `RotationLayer`, …; or class names: `XOR`, `Equal`) |
| `skip_ops` | `None` | Operation class names to skip |
| `skip_rounds` | `None` | Round indices to skip; gaps auto-bridged |
| `skip_functions` | `None` | Function names to skip (full-cipher mode only) |
| `flat_sbox` | `True` | `True` = lookup table; `False` = boolean equations |
| `algebraic_layers` | `None` | Class names emitted algebraically (e.g. `["MatrixLayer"]`) |
| `perm_rename` | `True` | Collapse permutation Equals via renaming |
| `rot_rename` | `True` | Same for rotations |
| `gf2linear_rename` | `True` | Same for GF2-linear ops |
| `canonical` | `True` | Sort variables within each relation |
| `cross_round_dir` | `False` | `False` = later→earlier rename; `True` = earlier→later |
| `bridge_skipped_rounds` | `True` | Equate values across skipped rounds |

### `SolverConfig` — AutoGuess backend

| Field | Default | Description |
|---|---|---|
| `solver` | `"sat"` | `sat \| milp \| smt \| cp \| mark \| elim \| propagate` |
| `findmin` | `False` | Iterate to find the minimum guess count |
| `maxguess` | `None` | Upper bound on guesses (auto = #targets) |
| `maxsteps` | `None` | Determination depth (auto = #variables) |
| `reducebasis` | `False` | Run the propagation-based basis reducer (forces `solver=propagate`) |
| `drawgraph` | `True` | Render determination-flow graph |
| `tikz` | `0` | `1` to also emit a TikZ `.tex` |
| `satsolver` / `smtsolver` / `cpsolver` | `cadical153` / `z3` / `cp-sat` | Backend choice |
| `milpdirection` | `"min"` | `min` or `max` |
| `cpoptimization` | `1` | `1` = optimize, `0` = decision |
| `timelimit` | `-1` | Per-solve timeout in seconds; `-1` = none |
| `threads` | `0` | `0` = auto |
| `preprocess`, `dglayout`, `log` | `0`, `"dot"`, `0` | Macaulay preprocess / graph layout / verbose logs |

Solver picker (general guidance): `sat` for most problems; `cp` when SAT is too rigid; `propagate` for pure deduction without optimization; `mark` / `elim` for the marking and elimination algorithms; `milp` for weighted/optimization-shaped problems.

## Output files

All artifacts land under `test/autoguess/files/`. For `cipher.name="aes"`, 2 rounds:

| Artifact | Path |
|---|---|
| Dirty (uncleaned) relations | `test/autoguess/files/temp/dirty_relations_aes_2r.txt` |
| Cleaned relations (input to AutoGuess) | `test/autoguess/files/relations_aes_2r.txt` |
| Text report | `test/autoguess/files/output_aes_2r` *(no extension)* |
| Graphviz source | `test/autoguess/files/output_aes_2r_graph.gv` |
| Determination-flow PDF | `test/autoguess/files/output_aes_2r_graph.gv.pdf` |
| TikZ (only if `tikz=1`) | `test/autoguess/files/output_aes_2r_graph.tex` |
| Solver intermediates (only if `log=1`) | `test/autoguess/files/temp/…` |

The output stem is derived from `output_file` by replacing `relations_` with `output_`.

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
    name_prefix="present_ks",
    relgen_cfg=RelGenConfig(flat_sbox=False),
    solver_cfg=SolverConfig(solver="cp", preprocess=1, maxguess=60, maxsteps=10),
)
```

**Skip rounds / focus on non-linear core:**

```python
RelGenConfig(skip_rounds=[1, 2, 20], skip_layers=["MatrixLayer", "RotationLayer"])
```

**Find the minimum guess basis (incremental SAT):**

```python
SolverConfig(solver="sat", findmin=True, maxguess=30)
```

**Reduce a known basis via propagation:**

```python
result = attacks.guess_and_determine_attack(
    cipher,
    known_vars=initial_basis,
    solver_cfg=SolverConfig(reducebasis=True),
)
```

**Publication-quality TikZ:**

```python
SolverConfig(tikz=1, dglayout="dot")
```

## Skip-layer reference

Friendly names accepted by `skip_layers` / `skip_ops`:

| Friendly name | Underlying op classes |
|---|---|
| `AddConstantLayer` | `ConstantXOR`, `ConstantAdd` |
| `AddIdentityLayer` | `Equal` |
| `RotationLayer` / `ShiftLayer` | `Rot` / `Shift` |
| `XORLayer` / `ANDLayer` / `ORLayer` / `NOTLayer` | `XOR`/`N_XOR`, `AND`, `OR`, `NOT` |
| `SboxLayer` | All S-box classes |
| `MatrixLayer` | `Matrix`, `GF2Linear` |
| `ModAddLayer` / `ModMulLayer` | `ModAdd` / `ModMul` |
| `CopyLayer` | `CopyOperator`, `COPY` |

Direct class names (e.g. `"XOR"`, `"Matrix"`) and ID prefixes (e.g. `"K_PERM"`) are also accepted.

## Lower-level entry points

If you need to drive the two stages independently:

```python
from tools.relation_generator import generate_relations
from tools.autoguess_wrapper   import run_autoguess
```

`generate_relations` produces the `relations_*.txt` file; `run_autoguess` consumes it and writes the report and graph. The signatures match the dataclass fields above by name. The high-level `search_guess_basis` is just orchestration over these two.

## Notes / gotchas

- The Groebner-basis solver is **not** available in this no-Sage variant. Use the upstream AutoGuess if you need it.
- If `target_vars` is set and `not_guessed_vars` doesn't already exclude them, the first target is auto-protected so the trivial all-targets-guessed solution can't win. Set `protect_all_targets=True` to protect every target (key-recovery mode).
- File paths inside `output_file` may be relative; they're resolved against `test/autoguess/files/` if not absolute.
