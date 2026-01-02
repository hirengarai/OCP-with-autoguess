# AutoGuess Usage Guide

This guide explains how to use AutoGuess in the OCP framework after the integration.

## Table of Contents
1. [Quick Start](#quick-start)
2. [Three Ways to Use AutoGuess](#three-ways-to-use-autoguess)
3. [Understanding the Output Files](#understanding-the-output-files)
4. [Common Use Cases](#common-use-cases)
5. [Advanced Options](#advanced-options)

---

## Quick Start

**Simplest way** - Use the high-level API from `attacks.py`:

```python
from attacks import attacks
import primitives.aes as aes

# Build cipher
cipher = aes.AES_block_cipher(rounds=2, key_length=128)
func = cipher.functions["PERMUTATION"]

# Define known variables (input + output)
known = [v.ID for v in func.vars[1][0]] + \
        [v.ID for v in func.vars[2][4]]

# Run attack
attacks.gd_attack(
    cipher,
    known_vars=known,
    solver='sat',
    maxguess=20
)
```

**Output files location**:
- Relations: `files/relations_aes_2r.txt`
- AutoGuess report: `files/autoguess/autoguess_output_aes_2r`
- Determination graph (PDF): `files/autoguess/autoguess_output_aes_2r_graph.pdf`
- TikZ LaTeX code (optional): `files/autoguess/autoguess_output_aes_2r_graph.tex`

---

## Three Ways to Use AutoGuess

### 1. High-Level API: `attacks.gd_attack()` (RECOMMENDED)

**When to use**: Most cases - simple, consistent with other attack types

**Import**:
```python
from attacks import attacks
```

**Usage**:
```python
attacks.gd_attack(
    cipher,                     # OCP cipher object
    known_vars=['vs_1_0_0', ...],  # Variables you know
    target_vars=['vs_2_4_0', ...], # Variables you want to determine (optional)
    solver='sat',               # Solver type: sat, cp, smt, milp, groebner
    maxguess=50,                # Max guesses to search for
    maxsteps=20,                # Max determination steps
    outputfile='autoguess_output',  # Output filename base
    tikz=0,                     # 0=PDF only, 1=PDF+LaTeX
    dglayout='dot',             # Graph layout: dot, neato, fdp, etc.
    satsolver='cadical153'      # SAT solver backend (optional)
)
```

**Features**:
- ✅ Simplest interface
- ✅ Automatic file management
- ✅ Consistent with `diff_attacks()` and `linear_attacks()`
- ✅ Automatic timing output

**Example - Key Schedule Analysis**:
```python
import primitives.present as present
from attacks import attacks

cipher = present.PRESENT_block_cipher(rounds=27)
ks = cipher.functions["KEY_SCHEDULE"]

# Known: some key bits from multiple rounds
known = [ks.vars[1][0][i].ID for i in range(16, 48)]

attacks.gd_attack(
    ks,                         # Pass the key schedule function
    known_vars=known,
    solver='cp',
    maxguess=60
)
```

---

### 2. Mid-Level API: `AutoguessModel` Class

**When to use**: Need more control, custom relation generation, or step-by-step workflow

**Import**:
```python
from tools.ocp_autoguess import AutoguessModel
```

**Usage**:
```python
# Step 1: Create attack instance
attack = AutoguessModel(cipher)  # or AutoguessModel(func)

# Step 2: Set variables
attack.set_known_variables(['vs_1_0_0', 'vs_1_0_1', ...])
attack.set_target_variables(['vs_3_4_0', 'vs_3_4_1', ...])

# Step 3: Generate relations (with custom options)
attack.generate_relations(
    skip_layers=['MatrixLayer'],    # Skip matrix/linear layer operations
    flat_sbox_mode=True,            # Flatten S-box representation
    algebraic=True                  # Use algebraic form (XOR as +)
)

# Step 4: Solve
attack.solve(
    solver='sat',
    maxguess=10,
    maxsteps=20,
    tikz=1                      # Generate TikZ code
)
```

**Features**:
- ✅ Fine-grained control over relation generation
- ✅ Can skip specific layers/operations
- ✅ Reusable attack object

**Example - Custom Workflow**:
```python
from tools.ocp_autoguess import AutoguessModel
import primitives.aes as aes

cipher = aes.AES_block_cipher(rounds=3, key_length=128)
attack = AutoguessModel(cipher)

# Define attack scenario
func = cipher.functions["PERMUTATION"]
attack.set_known_variables([v.ID for v in func.vars[1][0]])
attack.set_target_variables([v.ID for v in func.vars[3][4]])

# Generate relations, skipping shift and rotation layers
attack.generate_relations(skip_layers=['ShiftLayer', 'RotationLayer'])

# Solve with CP solver
attack.solve(solver='cp', tool='or-tools')
```

---

### 3. Low-Level API: Direct `generate_relations()` + `solve_autoguess()`

**When to use**: Maximum control, batch processing, or research experiments

**Import**:
```python
from tools.autoguess_bridge import generate_relations
from tools.autoguess import solve_autoguess
```

**Usage**:
```python
from pathlib import Path
from variables.variables import Variable
import primitives.present as present

# Setup
ROOT = Path.cwd()
FILES_DIR = ROOT / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)

# Build cipher
cipher = present.PRESENT_block_cipher(rounds=27)
ks = cipher.functions["KEY_SCHEDULE"]

# Define variables
known_vars = [ks.vars[1][0][i].ID for i in range(16, 48)]
output_file = FILES_DIR / "relations_present_keysch_27r.txt"

# Step 1: Generate relations
relations = generate_relations(
    ks,
    known_vars=known_vars,
    target_vars=None,
    output_file=str(output_file),
    flat_sbox_mode=False,
    clean_key_schedule=False,
    algebraic=True,
    save_dirty=True,
    enable_cleaning=True
)

# Step 2: Solve
solve_autoguess(
    inputfile=str(output_file),
    solver="cp",
    maxguess=60,
    maxsteps=10,
    outputfile="files/autoguess/autoguess_output_present_27r",
    preprocess=1,
    D=2,
    log=0,
    tikz=1,
    dglayout='dot'
)
```

**Features**:
- ✅ Maximum flexibility
- ✅ Direct control over all parameters
- ✅ Can save intermediate files
- ✅ Good for research and experimentation

**See also**: `examples/autoguess/test_*.py` for complete low-level examples

---

## Understanding the Output Files

### File Structure
```
OCP-with-autoguess/
├── files/
│   ├── relations_<cipher>_<rounds>r.txt    # Generated relations (cleaned)
│   ├── temp/                                # Intermediate files (if save_dirty=True)
│   │   └── relations_<cipher>_<rounds>r_dirty.txt
│   └── autoguess/                           # AutoGuess output directory
│       ├── autoguess_output_<cipher>_<rounds>r           # Text report
│       ├── autoguess_output_<cipher>_<rounds>r_graph.pdf # Determination graph
│       └── autoguess_output_<cipher>_<rounds>r_graph.tex # TikZ code (if tikz=1)
```

### Output Files Explained

#### 1. **Relations file** (`relations_aes_1r.txt`)
- **Purpose**: Cleaned algebraic relations for AutoGuess
- **Format**: One relation per line, e.g., `vs_1_0_0 + vs_2_1_3 = vsk_1_0_5`
- **Location**: `files/`
- **When created**: During relation generation step

#### 2. **AutoGuess text report** (`autoguess_output_aes_1r`)
- **Purpose**: Detailed attack analysis
- **Contains**:
  - Number of guesses needed
  - List of variables in the guess basis
  - Step-by-step determination flow
  - Solver statistics (time, relations used, etc.)
- **Location**: `files/autoguess/`
- **When created**: After AutoGuess solver finishes

#### 3. **Determination graph PDF** (`autoguess_output_aes_1r_graph.pdf`)
- **Purpose**: Visual representation of the determination flow
- **Shows**:
  - 🔵 Blue nodes = Known variables
  - 🔴 Red nodes = Guessed variables
  - 🟢 Green nodes = Determined variables
  - Arrows = Determination dependencies
- **Location**: `files/autoguess/`
- **When created**: Always generated (automatically)
- **Layout**: Controlled by `dglayout` parameter ('dot', 'neato', 'fdp', etc.)

#### 4. **TikZ LaTeX code** (`autoguess_output_aes_1r_graph.tex`) [Optional]
- **Purpose**: Publication-quality LaTeX/TikZ code for the graph
- **Use case**: Include in research papers, presentations
- **Location**: `files/autoguess/`
- **When created**: Only if `tikz=1`

---

## Common Use Cases

### Use Case 1: AES Differential Attack

```python
from attacks import attacks
import primitives.aes as aes

# 2-round AES
cipher = aes.AES_block_cipher(rounds=2, key_length=128)
func = cipher.functions["PERMUTATION"]

# Known: input and output state
known = [v.ID for v in func.vars[1][0]] + \
        [v.ID for v in func.vars[2][4]]

attacks.gd_attack(
    cipher,
    known_vars=known,
    solver='sat',
    maxguess=20,
    tikz=1  # Generate LaTeX for paper
)
```

**Output**: Check `files/autoguess/autoguess_output_aes_2r_graph.pdf`

---

### Use Case 2: PRESENT Key Schedule Analysis

```python
from attacks import attacks
import primitives.present as present

cipher = present.PRESENT_block_cipher(rounds=27)
ks = cipher.functions["KEY_SCHEDULE"]

# Known key bits from specific rounds
def ridx(r_paper):
    return r_paper + 1

known_pairs = []
known_pairs += [(ridx(0), j) for j in range(16, 48)]
known_pairs += [(ridx(1), j) for j in range(20, 28)]
known_pairs += [(ridx(25), j) for j in [0, 2, 8, 10, 16, 18]]
known_pairs += [(ridx(26), 2*i) for i in range(32)]

known = [ks.vars[r][0][j].ID for (r, j) in known_pairs]

attacks.gd_attack(
    ks,
    known_vars=known,
    solver='cp',
    maxguess=60,
    dglayout='neato'  # Better for complex graphs
)
```

---

### Use Case 3: Custom Cipher Analysis with Skip Options

```python
from tools.ocp_autoguess import AutoguessModel
import primitives.custom_cipher as custom

cipher = custom.CustomCipher(rounds=5)
attack = AutoguessModel(cipher)

# Define scenario
func = cipher.functions["PERMUTATION"]
attack.set_known_variables([v.ID for v in func.vars[1][0]])
attack.set_target_variables([v.ID for v in func.vars[5][4]])

# Generate relations, but skip linear layers to focus on non-linear
attack.generate_relations(
    skip_layers=['MatrixLayer', 'AddIdentityLayer'],
    flat_sbox_mode=True
)

attack.solve(solver='sat', maxguess=30)
```

---

## Advanced Options

### Skip Layers: Intuitive Layer Names

When generating relations, you can skip specific layer types using intuitive names:

```python
attack.generate_relations(
    skip_layers=['AddConstantLayer', 'RotationLayer'],  # Skip constant additions and rotations
    skip_operations=['Equal'],                          # Skip specific operation classes
    flat_sbox_mode=True
)
```

**Available Layer Names**:

| Layer Name | Skips Operator Classes | Description |
|------------|----------------------|-------------|
| `AddConstantLayer` | `ConstantXOR`, `ConstantAdd` | Constant additions (round constants) |
| `AddIdentityLayer` | `Equal` | Identity/equality constraints |
| `RotationLayer` | `Rot` | Rotation operations |
| `ShiftLayer` | `Shift` | Shift operations |
| `XORLayer` | `XOR`, `N_XOR` | XOR operations |
| `ANDLayer` | `AND` | AND operations |
| `ORLayer` | `OR` | OR operations |
| `NOTLayer` | `NOT` | NOT operations |
| `SboxLayer` | All S-box classes | S-box operations (AES, PRESENT, etc.) |
| `MatrixLayer` | `Matrix`, `GF2Linear` | Matrix/linear transformations |
| `ModAddLayer` | `ModAdd` | Modular addition |
| `ModMulLayer` | `ModMul` | Modular multiplication |
| `CopyLayer` | `CopyOperator`, `COPY` | Copy/duplication operations |

**Direct Class Names**: You can also use the actual operator class names directly:
```python
skip_layers=['ConstantXOR', 'Rot', 'Matrix']  # Direct class names
```

**Use Cases**:
- Skip `AddConstantLayer` to ignore round constants in key schedule analysis
- Skip `MatrixLayer` to focus on non-linear operations (S-boxes)
- Skip `RotationLayer` to simplify ARX cipher analysis
- Skip `SboxLayer` to analyze linear components only

### Solver Types and When to Use Them

| Solver | Best For | Speed | Memory |
|--------|----------|-------|--------|
| `sat` | Most cases, fast for moderate problems | ⚡⚡⚡ | Medium |
| `cp` | Large search spaces, complex constraints | ⚡⚡ | High |
| `smt` | Mixed theories, bit-vector operations | ⚡⚡ | Medium |
| `milp` | Optimization problems | ⚡ | High |
| `groebner` | Algebraic systems, polynomial ideals | ⚡ | Very High |

**Recommendation**: Start with `solver='sat'` (fastest in most cases)

### Graph Layout Algorithms

| Layout | Best For | Description |
|--------|----------|-------------|
| `dot` | Hierarchical flows (default) | Top-down tree layout |
| `neato` | Small to medium graphs | Spring model layout |
| `fdp` | Large graphs with clusters | Force-directed placement |
| `sfdp` | Very large graphs | Scalable force-directed |
| `circo` | Cyclic structures | Circular layout |
| `twopi` | Radial hierarchies | Radial layout |

**Recommendation**: Use `dot` for most cases, `neato` or `fdp` for complex determination flows

### Solver-Specific Options

#### SAT Solver
```python
attacks.gd_attack(
    cipher,
    known_vars=known,
    solver='sat',
    satsolver='cadical153',  # Options: cadical153, glucose3, minisat22
    maxguess=20
)
```

#### CP Solver with Preprocessing
```python
attacks.gd_attack(
    cipher,
    known_vars=known,
    solver='cp',
    cpsolver='or-tools',  # Options: or-tools, gecode, chuffed
    preprocess=1,         # Enable preprocessing
    D=2,                  # Degree of Macaulay matrix
    maxguess=60
)
```

#### Generate TikZ for Publications
```python
attacks.gd_attack(
    cipher,
    known_vars=known,
    solver='sat',
    tikz=1,               # Generate LaTeX/TikZ code
    dglayout='dot',       # Clean hierarchical layout
    maxguess=20
)
# Output: files/autoguess/autoguess_output_*_graph.tex
```

---

## Quick Reference Card

### Most Common Commands

```python
# Simple attack (recommended for most users)
from attacks import attacks
attacks.gd_attack(cipher, known_vars=known, solver='sat', maxguess=20)

# Check output files
# - Text report: files/autoguess/autoguess_output_<cipher>_<rounds>r
# - Graph PDF:   files/autoguess/autoguess_output_<cipher>_<rounds>r_graph.pdf

```

### File Locations Summary

| File Type | Location | Purpose |
|-----------|----------|---------|
| Relations | `files/relations_*.txt` | Cleaned algebraic relations |
| Text Report | `files/autoguess/autoguess_output_*` | Detailed attack analysis |
| Graph PDF | `files/autoguess/autoguess_output_*_graph.pdf` | Determination flow diagram |
| TikZ Code | `files/autoguess/autoguess_output_*_graph.tex` | LaTeX code (if tikz=1) |
| Temp Files | `files/temp/` | Debug files (if save_dirty=True) |

---

## Summary

**For most users**: Use `attacks.gd_attack()` - it's simple, consistent, and handles everything automatically.

**For advanced users**: Use `AutoguessModel` for fine control over relation generation.

**For researchers**: Use low-level API for maximum flexibility and batch experiments.

**All output files** are now organized in `files/autoguess/` for easy management.

---

**Next Steps**:
- See `examples/autoguess/` for complete working examples
- Read `docs/WIKI_AUTOGUESS_INTEGRATION.md` for technical details
- Check `test/autoguess/` for low-level API examples
