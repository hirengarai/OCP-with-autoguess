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

# Known: the plaintext and the output of the configured reduced relation system.
known_vars = [v.ID for v in func.vars[1][0]] + [v.ID for v in func.vars[func.nbr_rounds][1]]

result = attacks.guess_and_determine_attack(
    cipher,
    known_vars=known_vars,
    objective_target="AT MOST 6",
    config_model={"skip_rounds": [2], "maxsteps": 14},
)
assert result["status"] == "sat", result["status"]
assert result["targets_covered"]
```

This configuration deliberately skips encryption round 2 and bridges the gap.
Its six guesses are eight-bit words in that reduced relation system; it is not
a claim about recovery for the complete two-round cipher. The corrected model
recovers all 96 exported variables from those six guesses within 14 steps.
`result["guessed_variables"]`, `result["determination_steps"]`, and the output
files (below) describe the current successful run. Always check `status` first.

Both bounds matter. Left to their defaults, `maxguess` is the total cost of all
unknown variables (their count in an unweighted OCP model), and `maxsteps` is
the number of variables before preprocessing. Supply a smaller guess bound
when you want a useful feasibility question or a cheaper minimization start.
An UNSAT result only rules out a basis under the selected model, guess bound,
and propagation depth. At timeout, a validated complete basis is returned with
`status="sat"` and `optimal=False`; without one, the result is `status="unknown"`.

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
| `"EXISTENCE"` | One solve: return any guess basis within the total possible unknown-variable cost, no minimisation (default) |
| `"OPTIMAL"` | Minimize within the configured relation model and propagation depth; check `optimal` to distinguish a proven minimum from a feasible incumbent |
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
| `solver` | `"DEFAULT"` | Concrete backend. SAT uses `cadical153` without a limit and interruptible `glucose3` with a finite limit; SMT uses `z3`; CP uses `cp-sat`. Ignored (with a warning) for `milp` / `mark` / `elim` / `propagate`, which expose no backend choice |
| `time_limit` | `-1` | One AutoGuess search budget in seconds, shared across optimization attempts; `-1` = unlimited, `0` = no search time. Positive fractions are accepted. Existing `timelimit` spelling is also accepted |
| `threads` | `0` | `0` = auto |
| `preprocess` | `0` | Macaulay preprocess |
| `milpdirection` | `"min"` | `min` or `max` |
| `cpoptimization` | `1` | `1` = optimize, `0` = decision |
| `dglayout` | `"dot"` | Determination-graph layout |

`findmin`, `maxguess`, `reducebasis`, `drawgraph`, `tikz` and `log` are **not** set
here — they are derived from `objective_target`, `goal` and `show_mode`.

`time_limit` uses the same name as the upstream solver attribute. The existing
`timelimit` key remains supported; if both keys are supplied, their values must
match. They configure one shared budget, not separate time limits.

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
    "status":              "sat",  # sat | unsat | unknown
    "optimal":             False,
    "termination_reason":  "time_limit",
    "timed_out":           True,
    "elapsed_seconds":    30.012,
    "time_limit":          30.0,
    "time_limit_seconds":  30.0,  # compatibility alias
    "targets_covered":     True,
    "outputfile":          "<absolute path or None>",
    "cipher":              <input cipher/function>,
    "known_variables":     [Variable, ...],
    "target_variables":    [Variable, ...],
    "guessed_variables":   [Variable, ...],
    "known_variable_ids":   [str, ...],
    "target_variable_ids":  [str, ...],
    "guessed_variable_ids": [str, ...],
    "unresolved_variable_ids": [str, ...],
    "determination_steps": [{"step": 0, "determined_vars": [Variable, ...]}, ...],
    "relation_file":       "<absolute path>",
    "model_hash":          "<SHA-256 of the relation file>",
}
```

Results come directly from the current solver invocation. A failed invocation
does not parse an older report at the same filename. Algebraic preprocessing can
introduce auxiliary variables without OCP objects: their IDs remain available
in the ID lists and `unresolved_variable_ids`. Single-function objects such as
`cipher.functions["KEY_SCHEDULE"]` are supported.

`termination_reason` is one of `optimal`, `solution_found`, `infeasible`,
`time_limit`, `interrupted`, or `unknown`. A time limit does not establish
infeasibility or optimality. Check `status` before using a basis: `unknown`
means that no complete validated basis was obtained.

## Time-limited optimization

```python
result = attacks.guess_and_determine_attack(
    cipher,
    known_vars=known_vars,
    objective_target="OPTIMAL",
    config_model={"model_type": "sat", "maxsteps": 14},
    config_solver={"time_limit": 30},
)
if result["status"] == "sat":
    print("Guess cost:", result["cost"])
    print("Proven minimum:", result["optimal"])
else:
    print("No complete basis:", result["status"])
print("Stopped because:", result["termination_reason"])
```

The default timed SAT backend is `glucose3`. A single deadline covers AutoGuess's
default-bound calculation, preprocessing, model creation, and all optimization
attempts, rather than restarting the clock for each bound. The best validated
basis found before timeout is retained; `optimal=True` requires a completed
minimum-cost proof within the selected model and depth.

OCP relation generation runs before this AutoGuess budget starts. Preprocessing
and model creation check the deadline cooperatively and can finish their current
operation after it expires. Basis verification, report writing, graph rendering,
and cleanup can also extend the total call time. `elapsed_seconds` measures the
AutoGuess call, including its final result handling; this option is not a hard
process wall-clock limit. The result records the requested budget separately as
`time_limit`; `time_limit_seconds` remains available with the same value.

For direct relation-file searches, use `run_autoguess(..., time_limit=30)`.
Its existing `timelimit` keyword also works. The standalone/vendored CLI keeps
the upstream `--timelimit 30` and `-tl 30` options unchanged.

Finite limits are supported by interruptible SAT backends, native CP and MILP,
and SMT with `solver="z3"`. Other PySMT backends reject finite limits because
their portable interface does not enforce them. Marking, elimination,
propagation, and `REDUCEBASIS` also reject finite limits; use their unlimited
default until they have an interruptible implementation.

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
        "maxsteps": 11,
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

## Sage-free support

Normal SAT search does not require SageMath. Boolean Macaulay preprocessing
(`preprocess=1`) uses exact polynomial arithmetic over GF(2), with `x*x=x`, and
packed GF(2) Gaussian elimination in Python/NumPy/Numba. The regression suite
checks independent truth tables and elimination, and reproduces the paper's
Section 5.1 example: 3 guesses without preprocessing, 2 at degree 2, and 1 at
degree 3. This validates that example and the tested algebra, not every attack
or every Sage feature.

The separate Gröbner-basis search backend is unavailable and fails explicitly.
Boolean nonlinear preprocessing does not provide general polynomial arithmetic
over GF(2^n). Binary matrix equations are supported; requesting the binary
algebraic option for AES's nonbinary MixColumns coefficients raises an error.
The ordinary AES matrix connection model handles those field coefficients.

`requirements-autoguess.txt` records the Python package versions used for the
Sage-free SAT and algebra regression checks. CP additionally needs the MiniZinc
Python package, a MiniZinc binary, and a backend solver; SMT needs PySMT and its
selected backend; MILP needs Gurobi and a suitable license. Graph rendering
needs the Graphviz executable as well as its Python package.

Run the focused regressions with:

```sh
env312/bin/python -m pytest -q test/autoguess/test_integration_regressions.py test/autoguess/test_solver_regressions.py test/autoguess/test_relation_regressions.py test/autoguess/test_sage_free_algebra.py
```

Optional native CP/SMT checks use the versions recorded in
`requirements-autoguess-native.txt`:

```sh
env312/bin/python -m pip install -r requirements-autoguess-native.txt
env312/bin/python -m pytest -q test/autoguess/test_native_cp.py test/autoguess/test_native_smt.py
```

The CP tests run actual CP-SAT, Gecode, and Chuffed processes when available;
the SMT tests run PySMT/Z3 and the direct Z3 backend. They compare finite-depth
answers and weighted costs with SAT and independent exhaustive enumeration.
Missing optional dependencies cause skips, so inspect the test summary.

The direct Sage-library reference uses a separate environment:

```sh
env312/bin/python -m venv files/native-sage-env
files/native-sage-env/bin/python -m pip install -r requirements-autoguess-sage-oracle.txt
env312/bin/python -m pytest -q test/autoguess/test_native_sage.py
```

This installs compiled Sage mathematical libraries distributed by PassageMath,
a SageMath fork, rather than the full upstream Sage application. The oracle
runs those native libraries in a separate process and does not import OCP.
The tests also accept a full Sage installation through
`OCP_SAGE_COMMAND="sage -python"`, or a Sage-capable Python through
`OCP_SAGE_PYTHON`. OCP's normal
runtime remains independent of these reference packages.

The native reference matched 169 polynomial pairs, both monomial orders,
27 GF(2) matrices, and 98 Macaulay systems. A further 24 comparisons run the
original upstream AutoGuess mathematical methods at commit
`9ea002f14838bc43a0dcbea8fe2ae44074c09858`, with an explicit shared variable order
and native imports replacing its broad `sage.all` import. Its symbolic input
parser is bypassed; lifting, matrix construction, elimination, and basis writing
run unchanged. The full Sage application and its separate Gröbner backend are
outside these comparisons.

To enable those upstream-source cases on another checkout, download the pinned
source before running `test_native_sage.py` (otherwise that one test skips):

```sh
mkdir -p files/autoguess-native-validation-2026-10-15
curl --fail --location https://raw.githubusercontent.com/hadipourh/autoguess/9ea002f14838bc43a0dcbea8fe2ae44074c09858/core/macaulay.py --output files/autoguess-native-validation-2026-10-15/upstream_macaulay.py
```

## Notes / gotchas

- The Groebner-basis solver is **not** available in this no-Sage variant. Use the upstream AutoGuess if you need it.
- Unsupported operators now raise an error instead of disappearing from the
  model. Use an explicit skip option only when the resulting abstraction is
  intentional. SKINNY TK2/TK3 tweakey LFSRs are modeled.
- Bijective transformations may be collapsed as knowledge equivalents in a
  connection model. Algebraic models retain distinct values across nonlinear
  S-boxes, word rotations, and nonzero constants.
- `AT MOST X` finds a feasible basis and does not promise the smallest one.
  `REDUCEBASIS` finds a smallest subset of the supplied basis; it does not search
  for every possible replacement basis. In this mode `known_vars` means
  removable guesses. Low-level relation files can separately supply fixed knowns.
- Finite SAT time limits select `glucose3` when `config_solver["solver"]` is
  `"DEFAULT"`. Explicitly selected unsupported backends, including CaDiCaL,
  reject the request rather than ignoring the limit. A timed-out optimization
  returns the best validated complete basis with `optimal=False`, or `unknown`
  if none was found. See the time-limited optimization example above.
- The PRESENT example uses 11 steps: replaying its saved 60-guess basis under
  corrected value-preserving algebraic modeling covers 94/96 targets at step
  10 and all 96 at step 11. The guess count remains feasible; the old depth
  claim does not hold for that saved basis under the corrected model.
- If `target_vars` is set and `not_guessed_vars` doesn't already exclude them, the first target is auto-protected so the trivial all-targets-guessed solution can't win. Set `protect_all_targets=True` to protect every target (key-recovery mode).
- Relative paths in `config_model["filename"]` are resolved against `test/autoguess/files/`.
- The relation file is named from the cipher and modelling options only, not from `goal` or `objective_target` — runs that differ only in objective deliberately reuse it.
