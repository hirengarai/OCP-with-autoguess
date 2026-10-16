# AutoGuess Usage Guide

A minimal reference for running guess-and-determine attacks via OCP's AutoGuess integration.

The entry point follows the same shape as every other OCP attack (`diff_attacks`,
`linear_attacks`, `integral_attacks`): a cipher, a `goal`, an `objective_target`,
a `show_mode`, and two plain configuration dicts.

## Installation

From the repository root, using Python 3.12:

```sh
python3.12 -m venv env312
source env312/bin/activate
python -m pip install -r requirements-autoguess.txt
```

SAT, MaxSAT and Sage-free preprocessing use these runtime requirements. Install
the packages for any optional backend you want to use:

```sh
python -m pip install minizinc==0.10.0                  # CP
python -m pip install PySMT==0.9.6 z3-solver==4.16.0.0  # SMT/Z3
python -m pip install gurobipy==13.0.2                 # MILP
```

CP also needs a MiniZinc executable and a solver backend. MILP needs a suitable
Gurobi license. Graph rendering needs the Graphviz system executable; use
`show_mode=0` to run without images. Normal tool use does not require SageMath.

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

The final console summary includes:

```text
STATUS: SAT
Termination: solution_found
Targets covered: 96 / 96
Guess cost: 6
Optimal: not established
```

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

When targets are supplied, the first target is protected from guessing unless
`not_guessed_vars` already protects a target. Set `protect_all_targets=True`
to protect every target.

### `goal`

`goal` is which question you are asking AutoGuess — the same slot that
`"DIFFERENTIALPATH_PROB"` and friends occupy in the other OCP attacks.

| Value | Meaning |
|---|---|
| `"GUESSBASIS"` | Find guesses that recover every requested target; without explicit targets, recover all modeled variables (default) |
| `"REDUCEBASIS"` | Find a smallest sufficient subset of the basis in `known_vars` using solver-free propagation; use the default model type |

### `objective_target`

| Value | Meaning |
|---|---|
| `"EXISTENCE"` | Return a basis within the default unknown-variable cost cap; MaxSAT and the default CP/MILP settings minimize |
| `"OPTIMAL"` | Minimize within the configured relation model and propagation depth; check `optimal` to distinguish a proven minimum from a feasible incumbent |
| `"AT MOST X"` | Set the guess-cost cap to X; check `status` for a feasible basis, infeasibility or an inconclusive search |

SAT and SMT use iterative minimization for `OPTIMAL`. CP and MILP use their
native minimization settings. MaxSAT always minimizes, including when a cost
cap is supplied. Costs count modeled variables, or explicit weights in a
relation file; they are not automatically key bits.

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
| `model_type` | `"sat"` | `sat \| maxsat \| milp \| smt \| cp \| mark \| elim \| propagate` — the framework the problem is encoded into |
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
| `solver` | `"DEFAULT"` | Concrete backend. SAT uses `cadical153` without a limit and `glucose3` with a finite limit; MaxSAT uses `glucose3`; SMT uses `z3`; CP uses `cp-sat`. Ignored (with a warning) for `milp` / `mark` / `elim` / `propagate` |
| `time_limit` | `-1` | One AutoGuess search budget in seconds, shared across optimization attempts; `-1` = unlimited, `0` = no search time. Positive fractions are accepted. Existing `timelimit` spelling is also accepted |
| `threads` | `0` | `0` = auto |
| `preprocess` | `0` | Macaulay preprocess |
| `D` | `2` | Macaulay degree when preprocessing is enabled |
| `milpdirection` | `"min"` | `min` or `max` |
| `cpoptimization` | `1` | `1` = optimize, `0` = decision |
| `dglayout` | `"dot"` | Determination-graph layout |
| `graph_view` | `"original"` | Original AutoGuess topology or `"deduction"` layers |
| `graph_scope` | `"targets"` | `"targets"` or `"full"` for the optional deduction view |
| `seed_basis` | `None` | Fully paid starting guesses, using IDs from the cleaned relation model |
| `seed_basis_file` | `None` | JSON ID list or a result containing `guessed_variable_ids` / `guessed_variables`; alternative to `seed_basis` |
| `lower_bound` | `False` | Generate and independently verify a guess-cost lower-bound certificate |
| `refine_basis` | `False` | Refine a paid seed for lower cost, then fewer propagation steps |
| `refine_time` | automatic | Refinement phase cap inside the shared search budget |
| `refine_trials` | `1000` | Maximum refinement trials |
| `random_seed` | `0` | Seed for optional refinement |

`findmin`, `maxguess`, `reducebasis`, `drawgraph`, `tikz` and `log` are **not** set
here — they are derived from `objective_target`, `goal` and `show_mode`.

`time_limit` uses the same name as the upstream solver attribute. The existing
`timelimit` key remains supported; if both keys are supplied, their values must
match. They configure one shared budget, not separate time limits.

MaxSAT uses PySAT's RC2 optimizer, included in the existing requirements.
Paid seeds, lower bounds and refinement support SAT, MaxSAT, SMT, CP and
minimizing MILP. Supply a paid seed when enabling refinement.

## Output files

By default, artifacts land under `test/autoguess/files/` (gitignored).
An absolute `config_model["filename"]` places the relations, report and graphs
in that file's directory. For `cipher.name="AES128"`, 3 modeling rounds:

| Artifact | Path |
|---|---|
| Dirty (uncleaned) relations | `test/autoguess/files/temp/dirty_relations_AES128_3r.txt` |
| Cleaned relations (input to AutoGuess) | `test/autoguess/files/relations_AES128_3r.txt` |
| Text report | `test/autoguess/files/output_AES128_3r` *(no extension)* |
| Graphviz source | `test/autoguess/files/output_AES128_3r_graph.gv` |
| Determination-flow PDF | `test/autoguess/files/output_AES128_3r_graph.pdf` |
| Scalable SVG | `test/autoguess/files/output_AES128_3r_graph.svg` |
| TikZ (only at `show_mode=3`) | `test/autoguess/files/output_AES128_3r_graph.tex` |
| Solver intermediates (only at `show_mode>=2`) | `test/autoguess/files/temp/…` |

Setting `config_model["name_prefix"]` inserts the prefix: `relations_<prefix>_AES128_3r.txt`.
The output stem is derived from the relation filename by replacing `relations_` with `output_`.

Graphs include a legend: red targets, green paid guesses, blue known variables
and grey derived variables. A guessed target has red fill and a green border.
The default preserves the original AutoGuess deduction topology. The optional
`graph_view="deduction"` shows synchronous deduction layers and AND junctions
for jointly required premises. PDF, SVG and TikZ share the same deduction edges.
`graph_files` lists only artifacts produced by the current run; format failures
are reported through `graph_warnings`.

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
    "cost":                6,
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
    "graph_files":         {"gv": "..._graph.gv", "pdf": "..._graph.pdf", "svg": "..._graph.svg"},
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

Optimization workflows also return `lower_bound`, `upper_bound`, `proof_method`,
`proof_scope` and `propagation_steps`. Seeded runs include `seed_cost` and
`seed_propagation_steps`, with refinement metadata when requested. A local
improvement establishes feasibility; `optimal=True` requires a minimum-cost
proof for the prepared model and selected depth.

## Time-limited optimization

```python
optimized = attacks.guess_and_determine_attack(
    cipher,
    known_vars=known_vars,
    objective_target="OPTIMAL",
    config_model={"model_type": "sat", "skip_rounds": [2], "maxsteps": 14},
    config_solver={"time_limit": 30},
)
if optimized["status"] == "sat":
    print("Guess cost:", optimized["cost"])
    print("Proven minimum:", optimized["optimal"])
else:
    print("No complete basis:", optimized["status"])
print("Stopped because:", optimized["termination_reason"])
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

Finite limits are supported by interruptible SAT backends, MaxSAT, native CP and MILP,
and SMT with `solver="z3"`. Other PySMT backends reject finite limits because
their portable interface does not enforce them. Marking, elimination,
propagation, and `REDUCEBASIS` also reject finite limits; use their unlimited
default until they have an interruptible implementation.

## Reuse and improve a paid basis

Reuse IDs from a successful result with the same relation model, knowledge and
deduction depth. Keep `known_vars` for actual knowledge assumptions: a paid
seed is supplied separately and retains its guess cost.

```python
if result["status"] == "sat":
    improved = attacks.guess_and_determine_attack(
        cipher,
        known_vars=known_vars,
        objective_target="OPTIMAL",
        config_model={"model_type": "maxsat", "skip_rounds": [2], "maxsteps": 14},
        config_solver={
            "time_limit": 30,
            "seed_basis": result["guessed_variable_ids"],
            "lower_bound": True,
            "refine_basis": True,
            "refine_time": 1,
            "random_seed": 17,
        },
    )
    print(improved["cost"], improved["optimal"])
```

The supplied basis must cover every target within `maxsteps`, fit the cost cap
and obey forbidden-guess restrictions. Previous IDs apply to the same cleaned
model; changing relation-generation options can change their meaning. A
validated seed remains available if optimization times out. Propagation steps
are deduction layers, not cipher rounds or measured attack runtime.

## Common patterns

For key-schedule analysis, pass `cipher.functions["KEY_SCHEDULE"]` as the
first argument and supply its variable IDs through the usual known, target
and forbidden-guess roles.

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

Boolean Macaulay preprocessing (`preprocess=1`, `D=2`) runs without SageMath
using exact Boolean arithmetic over GF(2), with `x*x=x`. Increase `D` to try
a higher preprocessing degree. The separate Gröbner-basis backend is unavailable.

Binary algebraic matrix equations are supported; general GF(2^n) polynomial
arithmetic is not. Use the ordinary AES matrix connection model for its
nonbinary MixColumns coefficients. Unsupported operators raise an error.
Explicitly skipping operations changes the relation model being searched.

Connection models can collapse bijections as knowledge equivalents. Algebraic
models retain distinct values across nonlinear S-boxes, word rotations and
nonzero constants.

## Tests (optional)

Install pytest separately from the runtime requirements. SAT, relation-generation
and Boolean-algebra checks:

```sh
python -m pip install pytest==9.0.3
python -m pytest -q test/autoguess/test_integration_regressions.py test/autoguess/test_relation_regressions.py test/autoguess/test_sage_free_algebra.py
```

For the complete suite, install the optional CP, SMT and MILP packages listed
under Installation and configure their native backends:

```sh
python -m pytest -q test/autoguess
```

The native checks use installed solver backends; some backend-specific cases
skip when unavailable. Sage comparisons use a separate optional environment.

<details>
<summary>Optional Sage-library comparison</summary>

These reference packages are for tests only. Keep them in a separate environment:

```sh
python3.12 -m venv files/native-sage-env
files/native-sage-env/bin/python -m pip install passagemath-brial==10.8.13 'passagemath-modules[gf2]==10.8.13'
python -m pytest -q test/autoguess/test_native_sage.py
```

This uses compiled Sage libraries distributed by PassageMath. An existing Sage
installation can be selected with `OCP_SAGE_COMMAND="sage -python"` or
`OCP_SAGE_PYTHON=/path/to/python`.

To include comparisons with the pinned upstream mathematical methods, download
their source before running the Sage tests; that case skips when the file is absent:

```sh
mkdir -p files/autoguess-native-validation-2026-10-15
curl --fail --location https://raw.githubusercontent.com/hadipourh/autoguess/9ea002f14838bc43a0dcbea8fe2ae44074c09858/core/macaulay.py --output files/autoguess-native-validation-2026-10-15/upstream_macaulay.py
```

</details>
