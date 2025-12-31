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
    result = model.solve(solver='sat', maxguess=10)

    print(f"Guess basis size: {result.num_guesses}")
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterable
from dataclasses import dataclass, field

from tools.relation_generator import generate_relations
from tools.autoguess import solve_autoguess


@dataclass
class AutoguessResult:
    """Container for Autoguess solver results."""
    success: bool = False
    num_guesses: int = 0
    guess_basis: List[str] = field(default_factory=list)
    determination_flow: List[tuple] = field(default_factory=list)
    solver_time: float = 0.0
    solver_type: str = ""
    relation_count: int = 0
    output_file: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Pretty print the result."""
        lines = [
            "=" * 60,
            "Autoguess Result",
            "=" * 60,
            f"Success:          {self.success}",
            f"Solver:           {self.solver_type}",
            f"Solver Time:      {self.solver_time:.2f}s",
            f"Relations:        {self.relation_count}",
            f"Guess Basis Size: {self.num_guesses}",
            "",
            "Guess Basis Variables:",
        ]

        for i, var in enumerate(self.guess_basis, 1):
            lines.append(f"  {i}. {var}")

        if self.determination_flow:
            lines.extend([
                "",
                "Determination Flow (first 10 steps):",
            ])
            for i, step in enumerate(self.determination_flow[:10], 1):
                lines.append(f"  Step {i}: {step}")

        lines.extend([
            "",
            f"Full output: {self.output_file}",
            "=" * 60,
        ])

        return "\n".join(lines)


class AutoguessModel:
    """
    Autoguess integration for OCP.

    Workflow:
    1. Generate relations from OCP cipher/function
    2. Solve using Autoguess to find minimal guess basis
    3. Return structured results

    Parameters:
        cipher_or_function: OCP cipher or function object
        function_mode: If True, treat as single Function (not Cipher)
        function_type: 'BLOCK_CIPHER', 'KEY_SCHEDULE', or 'PERMUTATION'
        output_dir: Directory for output files
    """

    def __init__(
        self,
        cipher_or_function: Any,
        function_mode: bool = False,
        function_type: Optional[str] = None,
        output_dir: str = 'files'
    ):
        self.cipher_or_function = cipher_or_function
        self.function_mode = function_mode
        self.function_type = function_type
        self.output_dir = Path(output_dir)
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

        if self.function_mode:
            print(f"Building {self.cipher_name.upper()} function in OCP ...")
        else:
            print(f"Building {self.cipher_name.upper()} cipher in OCP ...")
        print("Generating relations from OCP model ...")

        relations = generate_relations(
            self.cipher_or_function,
            function_mode=self.function_mode,
            function_type=self.function_type,
            known_vars=self.known_vars,
            target_vars=self.target_vars,
            output_file=relationfile,
            skip_layers=skip_layers,
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
    ) -> AutoguessResult:
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
            AutoguessResult object
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

        result = self._parse_solver_output(output_path, solver)
        return result

    def _parse_solver_output(self, output_filename: str, solver_type: str) -> AutoguessResult:
        """Parse Autoguess solver output file."""
        result = AutoguessResult(solver_type=solver_type)

        output_path = Path(output_filename)
        if not output_path.exists():
            output_path = Path.cwd() / output_filename

        if not output_path.exists():
            return result

        result.output_file = str(output_path)

        try:
            with output_path.open('r') as f:
                content = f.read()

            # Extract guess basis
            guess_basis_match = re.search(
                r'Guess basis:(.*?)(?:\n\n|\nDetermination flow:)',
                content,
                re.DOTALL
            )
            if guess_basis_match:
                guess_vars = guess_basis_match.group(1).strip().split('\n')
                result.guess_basis = [v.strip() for v in guess_vars if v.strip()]
                result.num_guesses = len(result.guess_basis)
                result.success = True

            # Extract solver time
            time_match = re.search(r'Time:\s*([\d.]+)', content)
            if time_match:
                result.solver_time = float(time_match.group(1))

            # Extract relation count
            rel_match = re.search(r'Number of relations:\s*(\d+)', content)
            if rel_match:
                result.relation_count = int(rel_match.group(1))

            # Extract determination flow
            flow_match = re.search(
                r'Determination flow:(.*?)(?:\n\n|$)',
                content,
                re.DOTALL
            )
            if flow_match:
                flow_lines = flow_match.group(1).strip().split('\n')
                result.determination_flow = [
                    line.strip() for line in flow_lines if line.strip()
                ]

        except Exception as e:
            print(f"Warning: Error parsing output: {e}")

        return result


def run_autoguess(
    cipher_or_function: Any,
    known_vars: Iterable[str],
    target_vars: Optional[Iterable[str]] = None,
    *,
    function_mode: bool = False,
    function_type: Optional[str] = None,
    solver: str = 'sat',
    maxguess: int = 10,
    maxsteps: int = 20,
    relationfile: Optional[str] = None,
    outputfile: Optional[str] = None,
    **kwargs
) -> AutoguessResult:
    """
    Run Autoguess solver in one call.

    Parameters:
        cipher_or_function: OCP cipher or function
        known_vars: Known variables
        target_vars: Target variables
        function_mode: Treat as single function
        function_type: 'BLOCK_CIPHER', 'KEY_SCHEDULE', or 'PERMUTATION'
        solver: Solver type
        maxguess: Maximum guesses
        maxsteps: Maximum steps
        relationfile: Relations output file
        outputfile: Solver output file
        **kwargs: Additional solver parameters

    Returns:
        AutoguessResult object
    """
    # Auto-detect if we have a Function or Cipher
    if not function_mode and not hasattr(cipher_or_function, 'functions'):
        function_mode = True

    model = AutoguessModel(
        cipher_or_function,
        function_mode=function_mode,
        function_type=function_type
    )

    if known_vars is not None:
        model.set_known_variables(known_vars)
    if target_vars is not None:
        model.set_target_variables(target_vars)

    # Split kwargs between relation generation and solver
    relation_params = ['skip_layers', 'skip_operations', 'skip_functions',
                       'flat_sbox_mode', 'algebraic', 'save_dirty']
    relation_kwargs = {k: v for k, v in kwargs.items() if k in relation_params}
    solver_kwargs = {k: v for k, v in kwargs.items() if k not in relation_params}

    model.generate_relations(relationfile=relationfile, **relation_kwargs)

    result = model.solve(
        solver=solver,
        maxguess=maxguess,
        maxsteps=maxsteps,
        outputfile=outputfile,
        **solver_kwargs
    )

    return result


__all__ = ['AutoguessModel', 'AutoguessResult', 'run_autoguess']
