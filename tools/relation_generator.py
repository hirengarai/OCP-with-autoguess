"""
Relation Generator — public API for converting OCP ciphers to AutoGuess relations.

This is the only module you need to import. It orchestrates:
  1. Emitter: walk the cipher, collect raw relation strings
  2. Formatting: add section headers (connection relations, known, target, end)
  3. Dirty save: optionally save pre-cleaned version for debugging
  4. Cleaner: collapse renames via Union-Find
  5. Output: save cleaned relations to file

Usage:
    from tools.relation_generator import generate_relations

    relations = generate_relations(
        aes_cipher,
        known=['vs_1_0_0', 'vs_1_0_1'],
        target=['vs_2_4_0', 'vs_2_4_1'],
        output_file='relations_aes_2r.txt',
    )
"""

import warnings
from pathlib import Path
from typing import Any, Iterable, List, Optional, cast

from tools.relation_generator_modules import emitter, cleaner

_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the OCP project root (parent of tools/)."""
    return Path(__file__).resolve().parents[1]


def _auto_filename(obj: Any, function_mode: bool) -> str:
    """Generate a default output filename from the cipher/function name."""
    name = getattr(obj, "name", "cipher" if not function_mode else "function")
    rounds = getattr(obj, "nbr_rounds", None)
    filename = f"relations_{name}"
    if rounds is not None:
        filename += f"_{rounds}r"
    filename += ".txt"
    return filename


def _format_with_headers(
    raw_relations: List[str],
    known: Optional[Iterable[str]],
    target: Optional[Iterable[str]],
    not_guessed: Optional[Iterable[str]],
) -> List[str]:
    """Add section headers to raw relations for the cleaner."""
    formatted = []

    # Split raw relations into connection and algebraic
    conn = []
    alg = []
    for line in raw_relations:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Algebraic: has '+' but not '=>'
        if "+" in s and "=>" not in s:
            alg.append(s)
        else:
            conn.append(s)

    if conn:
        formatted.append("connection relations")
        formatted.extend(conn)
    if alg:
        formatted.append("algebraic relations")
        formatted.extend(alg)
    if known:
        formatted.append("known")
        formatted.extend([str(k).strip() for k in known])
    if target:
        formatted.append("target")
        formatted.extend([str(t).strip() for t in target])
    if not_guessed:
        formatted.append("not guessed")
        formatted.extend([str(v).strip() for v in not_guessed])
    formatted.append("end")

    return formatted


def _save_lines(lines: List[str], path: str):
    """Write lines to a file."""
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


def _count_relations(lines: List[str]) -> int:
    """Count relation lines (excluding headers and 'end')."""
    headers = {
        "connection relations",
        "algebraic relations",
        "known",
        "target",
        "not guessed",
    }
    count = 0
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.lower() == "end":
            break
        if s.lower() in headers:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_relations(
    cipher_or_function: Any,
    *,
    # Mode
    function_mode: bool = False,
    # Emitter controls
    skip_layers: Optional[Iterable[str]] = None,
    skip_ops: Optional[Iterable[str]] = None,
    skip_rounds: Optional[Iterable[int]] = None,
    skip_functions: Optional[Iterable[str]] = None,
    sbox_form: Optional[str] = None,
    flat_sbox: Any = _UNSET,  # deprecated; use sbox_form
    algebraic_layers: Optional[Iterable[str]] = None,
    perm_rename: bool = True,
    rot_rename: bool = True,
    gf2linear_rename: bool = True,
    # Variable sections
    known: Optional[Iterable[str]] = None,
    target: Optional[Iterable[str]] = None,
    not_guessed: Optional[Iterable[str]] = None,
    # Output
    output_file: Optional[str] = None,
    save_dirty: bool = True,
    # Cleaner controls
    enable_cleaning: bool = True,
    cleaning_direction: Optional[str] = None,
    debug_cross_renames: bool = False,
    strict_anchored: bool = False,
    emit_debug_chains: bool = False,
    bridge_skipped_rounds: bool = True,
) -> List[str]:
    """
    Generate AutoGuess-compatible relation file from an OCP cipher or function.

    Parameters
    ----------
    cipher_or_function : Cipher or Function object from OCP.

    function_mode : bool
        True = single function (e.g. key schedule), False = full cipher.

    skip_layers : list of str
        Layers to skip. Accepts friendly names ("SboxLayer", "PermutationLayer"),
        class names ("XOR", "Equal"), or ID prefixes ("K_PERM").

    skip_ops : list of str
        Operation class names to skip entirely.

    skip_rounds : list of int
        Round numbers to skip. Gap-linking is auto-generated.

    skip_functions : list of str
        Function names to skip (only used when function_mode=False).

    sbox_form : "rename" | "implication" | None
        Per-S-box emission form. ``None`` (default) infers from wiring shape:
        single multi-bit var in/out → "rename" (one ``a, b`` line);
        anything else → "implication" (one ``ins => out_bit`` per output bit).
        Pass an explicit value to override the inference.

    flat_sbox : bool
        DEPRECATED. ``True`` ↔ ``sbox_form='rename'``;
        ``False`` ↔ ``sbox_form='implication'``. Kept for one release with a
        DeprecationWarning. Will be removed.

    algebraic_layers : list of str
        Layers to force into algebraic mode.

    perm_rename : bool
        True = permutation Equals are renames (collapsible).
        False = mark as NONRENAME (kept as real relations).

    rot_rename, gf2linear_rename : bool
        Same as perm_rename but for rotations and GF2Linear ops.

    known, target, not_guessed : list of str
        Variables for the corresponding sections.

    output_file : str
        Output filename. Auto-generated if None.

    save_dirty : bool
        Save pre-cleaned version to files/autoguess/temp/ for debugging.

    enable_cleaning : bool
        If False, return raw formatted relations without cleaning.

    cleaning_direction : "input" | "output" | "default" | "opp_default" | None
        Selects which round-boundary side the canonical reps land on:
            "input"       — uniform input boundary; every survivor at
                            vk_<later_round>_0_*.
            "output"      — uniform output boundary; every survivor at
                            vk_<earlier>_<max>_*.
            "default"     — earliest layer + earlier round; histogram
                            splits between layer 0 and max_layer.
            "opp_default" — opposite mixed corner.
        When None, "default" is used.

    debug_cross_renames : bool
        Include cross-round rename lines in output (debug only).

    strict_anchored : bool
        Error if 2+ anchored vars in same equivalence class.

    emit_debug_chains : bool
        If True, the cleaner appends a substitution-chain debug block after
        the ``end`` marker (one chain per watched variable that actually
        moved through the substitutions). Off by default: the file ends at
        ``end``.

    Returns
    -------
    List of cleaned relation strings.
    """
    # Deprecation: translate flat_sbox → sbox_form when the user passed it.
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

    # Convert rename flags to nonrename flags (True rename = False nonrename)
    nonrename_perm = not perm_rename
    nonrename_rot = not rot_rename
    nonrename_gf2 = not gf2linear_rename

    # Step 1: Emit raw relations
    emitter_kwargs: dict = dict(
        skip_layers=skip_layers,
        skip_ops=skip_ops,
        skip_rounds=skip_rounds,
        sbox_form=sbox_form,
        algebraic_layers=algebraic_layers,
        nonrename_perm=nonrename_perm,
        nonrename_rot=nonrename_rot,
        nonrename_gf2=nonrename_gf2,
        bridge_skipped_rounds=bridge_skipped_rounds,
    )

    if function_mode:
        raw = emitter.emit_function(cipher_or_function, **emitter_kwargs)
    else:
        raw = emitter.emit_cipher(
            cipher_or_function,
            skip_functions=skip_functions,
            **emitter_kwargs,
        )

    # Step 2: Format with section headers
    formatted = _format_with_headers(raw, known, target, not_guessed)

    # Step 3: Determine output filename
    if output_file is None:
        output_file = _auto_filename(cipher_or_function, function_mode)

    # Resolve to test/autoguess/files/ directory
    output_dir = _project_root() / "test" / "autoguess" / "files"
    output_dir.mkdir(parents=True, exist_ok=True)
    if not Path(output_file).is_absolute():
        output_file = str(output_dir / output_file)

    # Step 4: Save dirty version for debugging
    if save_dirty:
        temp_dir = output_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        dirty_name = f"dirty_{Path(output_file).stem}.txt"
        _save_lines(formatted, str(temp_dir / dirty_name))

    # Step 5: Clean (or skip)
    if not enable_cleaning:
        _save_lines(formatted, output_file)
        return formatted

    print("Preparing final relations for Autoguess ...")

    _direction = cleaning_direction if cleaning_direction is not None else "default"
    cleaner_config = cleaner.CleanerConfig(
        cleaning_direction=cast(cleaner.CleaningDirection, _direction),
        debug_cross_renames=bool(debug_cross_renames),
        strict_anchored=bool(strict_anchored),
        emit_debug_chains=bool(emit_debug_chains),
    )
    cleaned = cleaner.clean_relations(formatted, config=cleaner_config)

    # Step 6: Save and report
    _save_lines(cleaned, output_file)

    count = _count_relations(cleaned)
    try:
        display = Path(output_file).relative_to(_project_root())
    except ValueError:
        display = Path(output_file)
    print(f"{count} relations prepared and written to {display}")

    return cleaned
