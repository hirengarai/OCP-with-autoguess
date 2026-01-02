"""
Relation Generator - Convert OCP cipher definitions to relation format.

This module generates cryptographic relations from OCP (Observational Constraint Programming)
cipher structures. Relations can be used with solvers like AutoGuess for cryptanalysis.

Components:
-----------
- relation_emitter.py: Generates raw relations from OCP objects
- relation_cleaner.py: Removes redundant variables from relations
- This file (__init__.py): Wrapper combining emitter + cleaner

Usage:
------
    from tools.relation_generator import generate_relations

    # For block ciphers
    relations = generate_relations(
        cipher,
        known_vars=['vs_1_0_0', ...],
        target_vars=['vs_2_4_0', ...],
        output_file='relations_aes_2r.txt'
    )

    # For key schedules or permutations
    relations = generate_relations(
        function,
        function_mode=True,
        function_type='KEY_SCHEDULE',
        known_vars=[...],
        target_vars=[...],
        output_file='relations_ks.txt'
    )
"""

from pathlib import Path
from typing import Any, Iterable, List, Optional

# Import emitter and cleaner
from . import relation_emitter
from . import relation_cleaner


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_temp_directory() -> Path:
    """Create the files/autoguess/temp directory if it doesn't exist."""
    temp_dir = _project_root() / "files" / "autoguess" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _save_dirty_relations(
    relations: List[str],
    output_file: str,
    temp_dir: Path
) -> Path:
    """Save dirty (uncleaned) relations to temp file for debugging."""
    # Extract base filename without extension
    base_name = Path(output_file).stem
    dirty_filename = f"dirty_{base_name}.txt"
    dirty_path = temp_dir / dirty_filename

    # Write dirty relations
    with dirty_path.open('w') as f:
        for line in relations:
            f.write(line + '\n')

    return dirty_path


def _format_relations_for_cleaning(
    relations: List[str],
    known_vars: Optional[Iterable[str]],
    target_vars: Optional[Iterable[str]]
) -> List[str]:
    """Format relations for cleaning by adding section headers."""
    formatted = []

    # Separate connection and algebraic
    conn_lines = [r for r in relations if not relation_emitter._is_algebraic_line(r)]
    alg_lines = [r for r in relations if relation_emitter._is_algebraic_line(r)]

    # Add connection relations section
    if conn_lines:
        formatted.append("connection relations")
        formatted.extend(conn_lines)

    # Add algebraic relations section
    if alg_lines:
        formatted.append("algebraic relations")
        formatted.extend(alg_lines)

    # Add known variables section
    if known_vars:
        formatted.append("known")
        formatted.extend([str(k).strip() for k in known_vars])

    # Add target variables section
    if target_vars:
        formatted.append("target")
        formatted.extend([str(t).strip() for t in target_vars])

    # Add end marker
    formatted.append("end")

    return formatted


def _save_cleaned_relations(
    relations: List[str],
    output_file: str
) -> None:
    """Save cleaned relations to output file."""
    output_path = Path(output_file)
    with output_path.open('w') as f:
        for line in relations:
            f.write(line + '\n')


def generate_relations(
    cipher_or_function: Any,
    *,
    # Mode selection
    function_mode: bool = False,
    function_type: Optional[str] = None,
    # Emitter parameters
    skip_layers: Optional[Iterable[str]] = None,
    skip_operations: Optional[Iterable[str]] = None,
    skip_rounds: Optional[Iterable[int]] = None,
    skip_functions: Optional[Iterable[str]] = None,
    flat_sbox_mode: bool = True,
    algebraic: bool = True,
    # Known/target variables
    known_vars: Optional[Iterable[str]] = None,
    target_vars: Optional[Iterable[str]] = None,
    # Output parameters
    output_file: Optional[str] = None,
    save_dirty: bool = True,
    # Cleaning parameters
    enable_cleaning: bool = True,
) -> List[str]:
    """
    Generate and clean cryptographic relations.

    This function generates raw relations using relation_emitter, optionally saves
    them for debugging, then cleans them using relation_cleaner with automatic
    key schedule cleaning detection.

    Parameters
    ----------
    cipher_or_function : Cipher or Function object
        Either a Cipher object (for full cipher analysis) or a Function object
        (for single function analysis).

    function_mode : bool, default=False
        If True, treat input as a single Function object.
        If False, treat input as a Cipher object with multiple functions.

    function_type : str, optional
        Type of function/cipher being analyzed. Used to determine if key schedule
        cleaning should be enabled:
        - 'BLOCK_CIPHER': Full block cipher (enables key schedule cleaning)
        - 'KEY_SCHEDULE': Key schedule only (no key schedule cleaning)
        - 'PERMUTATION': Permutation only (no key schedule cleaning)
        - 'SUBKEYS': Subkey generation (no key schedule cleaning)
        If not specified, defaults to BLOCK_CIPHER for cipher mode and
        no key schedule cleaning for function mode.

    skip_layers : iterable of str, optional
        Layer ID prefixes to skip during generation (e.g., ['MC_', 'SR_']).

    skip_operations : iterable of str, optional
        Operation class names to skip entirely (e.g., ['Equal', 'Rot']).

    skip_rounds : iterable of int, optional
        Round numbers to skip entirely. When skipping, round-to-round links
        are rebuilt to bypass skipped rounds.

    skip_functions : iterable of str, optional
        Function names to skip (only used when function_mode=False).

    flat_sbox_mode : bool, default=True
        Use flat S-box representation.

    algebraic : bool, default=True
        Generate algebraic relations (using '+' for XOR).

    known_vars : iterable of str, optional
        Variables to list in the "known" section.

    target_vars : iterable of str, optional
        Variables to list in the "target" section.

    output_file : str, optional
        Output filename for cleaned relations.
        If None, auto-generated based on cipher/function name.

    save_dirty : bool, default=True
        If True, save uncleaned relations to files/autoguess/temp/ for debugging.

    enable_cleaning : bool, default=True
        If True, apply the cleaner to simplify relations.
        If False, return raw relations from emitter.

    Returns
    -------
    list of str
        List of cleaned relation strings (or raw if enable_cleaning=False).

    Examples
    --------
    # Full block cipher with automatic key schedule cleaning
    >>> relations = generate_relations(
    ...     aes_cipher,
    ...     known_vars=['vs_1_0_0', 'vs_1_0_1', ...],
    ...     target_vars=['vs_2_4_0', 'vs_2_4_1', ...],
    ...     output_file='relations_aes_2r.txt'
    ... )

    # Key schedule only (no key schedule cleaning)
    >>> relations = generate_relations(
    ...     key_schedule_func,
    ...     function_mode=True,
    ...     function_type='KEY_SCHEDULE',
    ...     known_vars=[...],
    ...     target_vars=[...],
    ...     output_file='relations_ks.txt'
    ... )

    # Permutation only (no key schedule cleaning)
    >>> relations = generate_relations(
    ...     permutation_func,
    ...     function_mode=True,
    ...     function_type='PERMUTATION',
    ...     known_vars=[...],
    ...     target_vars=[...],
    ...     output_file='relations_perm.txt'
    ... )
    """

    # Step 1: Determine if key schedule cleaning should be enabled
    # By default, enable for block ciphers, disable for single functions
    use_key_schedule_cleaning = False

    if function_type:
        # Explicit function type specified
        if function_type.upper() == 'BLOCK_CIPHER':
            use_key_schedule_cleaning = True
        elif function_type.upper() in ('KEY_SCHEDULE', 'PERMUTATION', 'SUBKEYS'):
            use_key_schedule_cleaning = False
    elif not function_mode:
        # Cipher mode (multiple functions) - assume block cipher
        use_key_schedule_cleaning = True

    # Step 2: Generate raw relations using emitter
    if function_mode:
        # Single function mode
        raw_relations = relation_emitter.genRelationsForFunction(
            cipher_or_function,
            skip_layers=skip_layers,
            skip_operations=skip_operations,
            skip_rounds=skip_rounds,
            flat_sbox_mode=flat_sbox_mode,
            algebraic=algebraic,
        )
    else:
        # Full cipher mode
        raw_relations = relation_emitter.genRelations(
            cipher_or_function,
            skip_layers=skip_layers,
            skip_operations=skip_operations,
            skip_functions=skip_functions,
            skip_rounds=skip_rounds,
            flat_sbox_mode=flat_sbox_mode,
            algebraic=algebraic,
        )

    # Step 3: Format relations with section headers
    formatted_relations = _format_relations_for_cleaning(
        raw_relations,
        known_vars,
        target_vars
    )

    # Step 4: Determine output filename if not provided
    if output_file is None:
        if function_mode:
            fname = getattr(cipher_or_function, "name", "function")
            output_file = f"relations_{fname}.txt"
        else:
            cname = getattr(cipher_or_function, "name", "cipher")
            rounds = getattr(cipher_or_function, "nbr_rounds", None)
            output_file = f"relations_{cname}"
            if rounds is not None:
                output_file += f"_{rounds}r"
            output_file += ".txt"
    if output_file is not None and not Path(output_file).is_absolute():
        output_file = str(_project_root() / output_file)

    # Step 5: Save dirty relations for debugging
    if save_dirty:
        temp_dir = _ensure_temp_directory()
        _save_dirty_relations(formatted_relations, output_file, temp_dir)

    # Step 6: Clean the relations
    if not enable_cleaning:
        return formatted_relations

    print(f"Preparing final relations for Autoguess ...")

    # Use the cleaner with appropriate key schedule cleaning flag
    cleaned_relations = relation_cleaner.clean_relations(
        formatted_relations,
        clean_key_schedule_flag=use_key_schedule_cleaning
    )

    # Get relative path from project root for stable output paths
    output_path = Path(output_file)
    if output_path.is_absolute():
        try:
            rel_path = output_path.relative_to(_project_root())
        except ValueError:
            # If not relative to cwd, use absolute path
            rel_path = output_path
    else:
        rel_path = output_path

    print(f"{len(cleaned_relations)} relations prepared and written to {rel_path}")

    # Step 7: Save cleaned relations to file
    if output_file:
        _save_cleaned_relations(cleaned_relations, output_file)

    return cleaned_relations


# Convenience functions for common use cases

def generate_block_cipher_relations(
    cipher: Any,
    known_vars: Iterable[str],
    target_vars: Iterable[str],
    output_file: Optional[str] = None,
    **kwargs
) -> List[str]:
    """
    Generate and clean relations for a full block cipher.

    This automatically enables key schedule cleaning to replace vk_* variables
    with vsk_* variables.

    Parameters
    ----------
    cipher : Cipher object
        Cipher object with both permutation and key schedule functions.

    known_vars : iterable of str
        Variables in the "known" section (usually input state + key).

    target_vars : iterable of str
        Variables in the "target" section (usually output state).

    output_file : str, optional
        Output filename for cleaned relations.

    **kwargs
        Additional parameters passed to generate_relations.

    Returns
    -------
    list of str
        List of cleaned relation strings.

    Examples
    --------
    >>> relations = generate_block_cipher_relations(
    ...     aes_cipher,
    ...     known_vars=['vs_1_0_0', 'vs_1_0_1', ...],
    ...     target_vars=['vs_2_4_0', 'vs_2_4_1', ...],
    ...     output_file='relations_aes_2r.txt'
    ... )
    """
    return generate_relations(
        cipher,
        function_mode=False,
        function_type='BLOCK_CIPHER',
        known_vars=known_vars,
        target_vars=target_vars,
        output_file=output_file,
        **kwargs
    )


def generate_permutation_relations(
    permutation_func: Any,
    known_vars: Iterable[str],
    target_vars: Iterable[str],
    output_file: Optional[str] = None,
    **kwargs
) -> List[str]:
    """
    Generate and clean relations for a permutation function only.

    This does NOT enable key schedule cleaning (no vk_* variables expected).

    Parameters
    ----------
    permutation_func : Function object
        Function object representing the permutation.

    known_vars : iterable of str
        Variables in the "known" section (usually input state).

    target_vars : iterable of str
        Variables in the "target" section (usually output state).

    output_file : str, optional
        Output filename for cleaned relations.

    **kwargs
        Additional parameters passed to generate_relations.

    Returns
    -------
    list of str
        List of cleaned relation strings.

    Examples
    --------
    >>> relations = generate_permutation_relations(
    ...     permutation_func,
    ...     known_vars=['vs_1_0_0', 'vs_1_0_1', ...],
    ...     target_vars=['vs_2_4_0', 'vs_2_4_1', ...],
    ...     output_file='relations_perm.txt'
    ... )
    """
    return generate_relations(
        permutation_func,
        function_mode=True,
        function_type='PERMUTATION',
        known_vars=known_vars,
        target_vars=target_vars,
        output_file=output_file,
        **kwargs
    )


def generate_key_schedule_relations(
    key_schedule_func: Any,
    known_vars: Iterable[str],
    target_vars: Iterable[str],
    output_file: Optional[str] = None,
    **kwargs
) -> List[str]:
    """
    Generate and clean relations for a key schedule function only.

    This does NOT enable key schedule cleaning (vk_* variables are kept as-is).

    Parameters
    ----------
    key_schedule_func : Function object
        Function object representing the key schedule.

    known_vars : iterable of str
        Variables in the "known" section (usually master key).

    target_vars : iterable of str
        Variables in the "target" section (usually round keys).

    output_file : str, optional
        Output filename for cleaned relations.

    **kwargs
        Additional parameters passed to generate_relations.

    Returns
    -------
    list of str
        List of cleaned relation strings.

    Examples
    --------
    >>> relations = generate_key_schedule_relations(
    ...     key_schedule_func,
    ...     known_vars=['vk_0_0_0', 'vk_0_0_1', ...],
    ...     target_vars=['vk_2_0_0', 'vk_2_0_1', ...],
    ...     output_file='relations_ks.txt'
    ... )
    """
    return generate_relations(
        key_schedule_func,
        function_mode=True,
        function_type='KEY_SCHEDULE',
        known_vars=known_vars,
        target_vars=target_vars,
        output_file=output_file,
        **kwargs
    )


__all__ = [
    'generate_relations',
    'generate_block_cipher_relations',
    'generate_permutation_relations',
    'generate_key_schedule_relations',
]
