"""
Autoguess Integration for OCP

This module integrates the Autoguess solver with OCP:
1. Converts OCP cipher/function to relations
2. Runs Autoguess solver to find minimal guess basis
3. Returns structured results

Usage:
    from tools.ocp_autoguess import AutoguessModel

    model = AutoguessModel(cipher)
    model.set_known_variables(['vs_1_0_0', ...])
    model.set_target_variables(['vs_3_4_0', ...])
    model.solve(solver='sat', maxguess=10)
"""

from pathlib import Path
from typing import Any, List, Optional, Iterable

from tools.relation_generator import generate_relations
from tools.autoguess import solve_autoguess


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


class AutoguessModel:
    """
    Autoguess integration for OCP.

    Workflow:
    1. Generate relations from OCP cipher/function
    2. Solve using Autoguess to find minimal guess basis
    3. Return structured results

    Parameters:
        cipher_or_function: OCP cipher or function object
        output_dir: Directory for output files
    """

    def __init__(
        self,
        cipher_or_function: Any,
        output_dir: str = 'files'
    ):
        self.cipher_or_function = cipher_or_function
        output_path = Path(output_dir)
        if not output_path.is_absolute():
            output_path = _project_root() / output_path
        self.output_dir = output_path
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.known_vars: Optional[List[str]] = None
        self.target_vars: Optional[List[str]] = None
        self.relations_file: Optional[str] = None
        self.cipher_name = getattr(cipher_or_function, "name", "cipher")

    def set_known_variables(self, variables: Iterable[str]) -> None:
        """Set known variables (input plaintext, keys, etc.)."""
        self.known_vars = list(variables)

    def set_target_variables(self, variables: Iterable[str]) -> None:
        """Set target variables (output ciphertext, round keys, etc.)."""
        self.target_vars = list(variables)

    def generate_relations(
        self,
        relationfile: Optional[str] = None,
        skip_layers: Optional[Iterable[str]] = None,
        skip_rounds: Optional[Iterable[int]] = None,
        skip_operations: Optional[Iterable[str]] = None,
        skip_functions: Optional[Iterable[str]] = None,
        flat_sbox_mode: bool = True,
        algebraic: bool = True,
        save_dirty: bool = True,
    ) -> List[str]:
        """
        Generate relations from OCP cipher/function.

        Parameters:
            relationfile: Output filename (required)
            skip_layers: Layer IDs to skip
            skip_rounds: Round numbers to skip
            skip_operations: Operation classes to skip
            skip_functions: Function names to skip
            flat_sbox_mode: Use flat S-box representation
            algebraic: Generate algebraic relations
            save_dirty: Save uncleaned relations for debugging

        Returns:
            List of cleaned relation strings
        """
        if relationfile is None:
            raise ValueError("relationfile must be provided")

        if not Path(relationfile).is_absolute():
            autoguess_dir = self.output_dir / "autoguess"
            autoguess_dir.mkdir(parents=True, exist_ok=True)
            relationfile = str(autoguess_dir / relationfile)

        self.relations_file = relationfile

        is_function = not hasattr(self.cipher_or_function, "functions")
        if is_function:
            print(f"Building {self.cipher_name.upper()} function in OCP ...")
        else:
            print(f"Building {self.cipher_name.upper()} cipher in OCP ...")
        print("Generating relations from OCP model ...")

        relations = generate_relations(
            self.cipher_or_function,
            function_mode=is_function,
            known_vars=self.known_vars,
            target_vars=self.target_vars,
            output_file=relationfile,
            skip_layers=skip_layers,
            skip_rounds=skip_rounds,
            skip_operations=skip_operations,
            skip_functions=skip_functions,
            flat_sbox_mode=flat_sbox_mode,
            algebraic=algebraic,
            save_dirty=save_dirty,
            enable_cleaning=True,
        )

        return relations

    def solve(
        self,
        solver: str = 'sat',
        tool: Optional[str] = None,
        maxguess: int = 10,
        maxsteps: int = 20,
        timeout: Optional[int] = None,
        preprocess: int = 0,
        tikz: int = 0,
        dglayout: str = 'dot',
        outputfile: Optional[str] = None,
        **kwargs
    ):
        """
        Solve using Autoguess to find minimal guess basis.

        Parameters:
            solver: 'sat', 'cp', 'smt', 'milp', 'groebner', 'mark', 'elim'
            tool: Specific solver tool (e.g., 'cadical153', 'z3', 'gurobi')
            maxguess: Maximum number of guesses
            maxsteps: Maximum determination steps
            timeout: Solver timeout in seconds
            preprocess: Preprocessing level (0-2)
            tikz: Generate TikZ graph (0 or 1)
            dglayout: Graph layout algorithm
            outputfile: Output filename
            **kwargs: Additional solver parameters

        Returns:
            None
        """
        if self.relations_file is None:
            raise ValueError("Relations not generated. Call generate_relations() first.")

        if not Path(self.relations_file).exists():
            raise ValueError(f"Relations file not found: {self.relations_file}")

        print("Solving with Autoguess ...\n")

        autoguess_dir = self.output_dir / "autoguess"
        autoguess_dir.mkdir(parents=True, exist_ok=True)

        if outputfile is not None:
            output_path = str(autoguess_dir / outputfile) if not Path(outputfile).is_absolute() else outputfile
        else:
            output_path = str(autoguess_dir / f"autoguess_output_{self.cipher_name}")

        solver_kwargs = {
            'inputfile': self.relations_file,
            'solver': solver,
            'maxguess': maxguess,
            'maxsteps': maxsteps,
            'preprocess': preprocess,
            'tikz': tikz,
            'dglayout': dglayout,
            'outputfile': output_path,
            **kwargs
        }

        if timeout is not None:
            solver_kwargs['timelimit'] = timeout

        if tool is not None:
            solver_kwargs['tool'] = tool

        solve_autoguess(**solver_kwargs)

        return None


def run_autoguess(
    cipher_or_function: Any,
    known_vars: Iterable[str],
    target_vars: Optional[Iterable[str]] = None,
    *,
    solver: str = 'sat',
    maxguess: int = 10,
    maxsteps: int = 20,
    relationfile: Optional[str] = None,
    outputfile: Optional[str] = None,
    **kwargs
):
    """
    Run Autoguess solver in one call.

    Parameters:
        cipher_or_function: OCP cipher or function
        known_vars: Known variables
        target_vars: Target variables
        solver: Solver type
        maxguess: Maximum guesses
        maxsteps: Maximum steps
        relationfile: Relations output file
        outputfile: Solver output file
        **kwargs: Additional solver parameters

    Returns:
        None
    """
    model = AutoguessModel(cipher_or_function)

    if known_vars is not None:
        model.set_known_variables(known_vars)
    if target_vars is not None:
        model.set_target_variables(target_vars)

    # Split kwargs between relation generation and solver
    relation_params = ['skip_layers', 'skip_rounds', 'skip_operations', 'skip_functions',
                       'flat_sbox_mode', 'algebraic', 'save_dirty']
    relation_kwargs = {k: v for k, v in kwargs.items() if k in relation_params}
    solver_kwargs = {k: v for k, v in kwargs.items() if k not in relation_params}

    model.generate_relations(relationfile=relationfile, **relation_kwargs)

    model.solve(
        solver=solver,
        maxguess=maxguess,
        maxsteps=maxsteps,
        outputfile=outputfile,
        **solver_kwargs
    )
    return None


__all__ = ['AutoguessModel', 'run_autoguess']
