"""
Created on July 13, 2020

@author: Hosein Hadipour
@contact: hsn.hadipour@gmail.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

In case you use this tool please include the above copyright informations (name, contact, license)
"""

import os
import time
from pysat import solvers
from pysat import formula
from pysat import pb
import random
from core.inputparser import read_relation_file
from core.parsesolution import parse_solver_solution
from config import TEMP_DIR
from core.console import progress
from core.varnames import step_var, path_var
from core.solverresult import solve_sat


class ReduceGDtoSAT:
    """
    ReduceGDtoSAT
    Using the PySAT, this class reduces the guess-and-determine attack and
    key-bridging to a SAT problem, and then solves it via a SAT solver.

    Created by Hosein Hadipour
    Aug 27, 2020

    inputfile_name: The name of a text file containing the relations
    max_guess:  The maximum number of guessed variables
    max_steps:  Number of state copies
    """

    count = 0

    def __init__(
        self,
        inputfile_name=None,
        outputfile_name="output",
        max_guess=0,
        max_steps=0,
        sat_solver="cadical153",
        tikz=0,
        preprocess=1,
        D=2,
        dglayout="dot",
        drawgraph=True,
        log=0,
        extra_known=None,
        prepared_data=None,
        graph_scope="targets",
        graph_view="original",
        defer_reporting=False,
    ):
        ReduceGDtoSAT.count += 1
        self.inputfile_name = inputfile_name
        self.output_dir = outputfile_name
        self.rnd_string_tmp = "%030x" % random.randrange(16**30)
        self.max_guess = max_guess
        self.max_steps = max_steps
        self.sat_solver_name = sat_solver
        self.draw_graph = drawgraph
        self.graph_scope = graph_scope
        self.graph_view = graph_view
        self.defer_reporting = defer_reporting
        self.supported_sat_solvers = [
            solver
            for solver in solvers.SolverNames.__dict__.keys()
            if not solver.startswith("__")
        ]
        if self.sat_solver_name not in self.supported_sat_solvers:
            raise ValueError(f"Unsupported SAT solver: {self.sat_solver_name}")
        self.dglayout = dglayout
        self.log = log
        ###############################
        # Read and parse the input file
        parsed_data = prepared_data
        if parsed_data is None:
            parsed_data = read_relation_file(
                self.inputfile_name,
                preprocess=preprocess,
                D=D,
                log=self.log,
                extra_known=extra_known,
            )
        self.problem_name = parsed_data["problem_name"]
        self.variables = parsed_data["variables"]
        self.known_variables = parsed_data["known_variables"]
        self.target_variables = parsed_data["target_variables"]
        self.target_weights = parsed_data["target_weights"]
        self.notguessed_variables = parsed_data["notguessed_variables"]
        self.symmetric_relations = parsed_data["symmetric_relations"]
        self.implication_relations = parsed_data["implication_relations"]
        self.dummy_mapping = parsed_data.get("dummy_mapping", {})
        self.num_of_relations = len(self.symmetric_relations) + len(
            self.implication_relations
        )
        self.num_of_vars = len(self.variables)
        ###############################
        self.variables_dictionary = dict()
        self.top_variable_identifier_so_far = 0
        self.deductions = self.generate_possible_deductions()
        self.cnf_formula = formula.CNF()
        self.time_limit = -1
        self.tikz = tikz

    def ordered_set(self, seq):
        """
        This method eliminates duplicated elements in a given list,
        and returns a list in which each elements appears only once
        """
        seen = set()
        seen_add = seen.add
        return [x for x in seq if not (x in seen or seen_add(x))]

    def generate_possible_deductions(self):
        """
        This method generates all possible deductions

        Core idea of information propagation:
            If there is a relation in which all terms are known except one,
            then the value of the last term can be determined as well.
        """

        # Build inverted indices for O(1) lookup instead of O(|R|) scan per variable
        from collections import defaultdict

        sym_index = defaultdict(list)
        for rel in self.symmetric_relations:
            for v in rel:
                sym_index[v].append(rel)
        impl_index = defaultdict(list)
        for rel in self.implication_relations:
            impl_index[rel[-1]].append(rel)

        possible_deductions = {}
        for v in self.variables:
            possible_deductions[v] = [[v]]
            _seen = set()
            for rel in sym_index.get(v, []):
                temp = rel.copy()
                temp.remove(v)
                temp.sort()
                key = tuple(temp)
                if key not in _seen:
                    _seen.add(key)
                    possible_deductions[v].append(temp)
            for rel in impl_index.get(v, []):
                temp = rel.copy()
                temp.remove(v)
                temp.sort()
                key = tuple(temp)
                if key not in _seen:
                    _seen.add(key)
                    possible_deductions[v].append(temp)
        return possible_deductions

    def update_variables_dictionary(self, new_vars):
        """
        This method is used to update variables' dictionary
        """
        for nv in new_vars:
            if nv not in self.variables_dictionary.keys():
                self.top_variable_identifier_so_far += 1
                self.variables_dictionary[nv] = self.variables_dictionary.get(
                    nv, self.top_variable_identifier_so_far
                )

    def generate_boundary_conditions(self):
        """
        This method generates the initial constraints corresponding to the
        known variables in the initial state as well as the constraint
        corresponding to the maximum number of guessed variables
        """

        final_state_target_vars = [
            step_var(v, self.max_steps) for v in self.target_variables
        ]
        self.update_variables_dictionary(final_state_target_vars)
        self.cnf_formula.extend(
            [[self.variables_dictionary[fsv]] for fsv in final_state_target_vars]
        )
        for v in self.known_variables:
            if v != "":
                known_variable_at_state0 = step_var(v, 0)
                self.update_variables_dictionary([known_variable_at_state0])
                self.cnf_formula.append(
                    [self.variables_dictionary[known_variable_at_state0]]
                )
        for v in self.notguessed_variables:
            if v != "":
                temp = step_var(v, 0)
                self.update_variables_dictionary([temp])
                self.cnf_formula.append([-self.variables_dictionary[temp]])
        # Cardinality constraint
        _known_set = set(self.known_variables)
        unknown_init_state_vars = [v for v in self.variables if v not in _known_set]
        initial_state_vars = [step_var(v, 0) for v in unknown_init_state_vars]
        if self.target_weights != None:
            weights = [self.target_weights.get(v, 1) for v in unknown_init_state_vars]
        else:
            weights = None
        self.update_variables_dictionary(initial_state_vars)
        # The default value of encoding is card.Enctype.seqcounter
        # pairwise    = 0
        # seqcounter  = 1 *
        # sortnetwrk  = 2 *
        # cardnetwrk  = 3 *
        # bitwise     = 4
        # ladder      = 5
        # totalizer   = 6 *
        # mtotalizer  = 7
        # kmtotalizer = 8
        # native      = 9
        # card_constraint = card.CardEnc.atmost(lits=[self.variables_dictionary[v] for v in initial_state_vars],
        #                                       bound=self.max_guess,
        #                                       top_id=self.top_variable_identifier_so_far,
        #                                       encoding=card.EncType.sortnetwrk)
        # Using PyPBLib
        card_constraint = pb.PBEnc.leq(
            lits=[self.variables_dictionary[v] for v in initial_state_vars],
            weights=weights,
            bound=self.max_guess,
            top_id=self.top_variable_identifier_so_far,
            encoding=pb.EncType.binmerge,
        )
        card_clauses = card_constraint.clauses
        self.cnf_formula.extend(card_clauses)

    def generate_boundary_no_cardinality(self):
        """
        Generate boundary conditions (target/known/notguessed) WITHOUT
        the cardinality constraint.  Used by incremental findmin.
        """
        final_state_target_vars = [
            step_var(v, self.max_steps) for v in self.target_variables
        ]
        self.update_variables_dictionary(final_state_target_vars)
        self.cnf_formula.extend(
            [[self.variables_dictionary[fsv]] for fsv in final_state_target_vars]
        )
        for v in self.known_variables:
            if v != "":
                known_variable_at_state0 = step_var(v, 0)
                self.update_variables_dictionary([known_variable_at_state0])
                self.cnf_formula.append(
                    [self.variables_dictionary[known_variable_at_state0]]
                )
        for v in self.notguessed_variables:
            if v != "":
                temp = step_var(v, 0)
                self.update_variables_dictionary([temp])
                self.cnf_formula.append([-self.variables_dictionary[temp]])
        # Register initial-state unknown variables (needed for external cardinality)
        _known_set = set(self.known_variables)
        unknown_init_state_vars = [v for v in self.variables if v not in _known_set]
        initial_state_vars = [step_var(v, 0) for v in unknown_init_state_vars]
        self.update_variables_dictionary(initial_state_vars)

    def get_cardinality_lits(self):
        """
        Return (lits, weights) for the cardinality constraint on
        initial-state unknown variables.
        Must be called after generate_boundary_no_cardinality().
        """
        _known_set = set(self.known_variables)
        unknown_init_state_vars = [v for v in self.variables if v not in _known_set]
        initial_state_vars = [step_var(v, 0) for v in unknown_init_state_vars]
        lits = [self.variables_dictionary[v] for v in initial_state_vars]
        if self.target_weights is not None:
            weights = [self.target_weights.get(v, 1) for v in unknown_init_state_vars]
        else:
            weights = None
        return lits, weights

    def generate_sat_constraints(self):
        """
        This method generates the smt constraints corresponding to the
        obtained deductions
        """

        for step in range(self.max_steps):
            for v in self.variables:
                v_new = step_var(v, step + 1)
                self.update_variables_dictionary([v_new])
                tau = len(self.deductions[v])
                v_path_variables = [path_var(v, step + 1, i) for i in range(tau)]
                self.update_variables_dictionary(v_path_variables)
                #####################################-State variable constraints-#####################################
                ######################################################################################################
                ######################################################################################################
                # v_new = Or(v_path_variables)
                self.cnf_formula.append(
                    [-self.variables_dictionary[v_new]]
                    + [self.variables_dictionary[vp] for vp in v_path_variables]
                )
                for vp in v_path_variables:
                    self.cnf_formula.append(
                        [
                            -self.variables_dictionary[vp],
                            self.variables_dictionary[v_new],
                        ]
                    )
                #####################################-Path variable constraints-######################################
                ######################################################################################################
                ######################################################################################################
                for i in range(0, tau):
                    # v_path_variables[i] = And(v_connected_variables)
                    v_connected_variables = [
                        step_var(var, step) for var in self.deductions[v][i]
                    ]
                    self.update_variables_dictionary(v_connected_variables)
                    for vc in v_connected_variables:
                        self.cnf_formula.append(
                            [
                                -self.variables_dictionary[v_path_variables[i]],
                                self.variables_dictionary[vc],
                            ]
                        )
                    self.cnf_formula.append(
                        [self.variables_dictionary[v_path_variables[i]]]
                        + [
                            -self.variables_dictionary[vc]
                            for vc in v_connected_variables
                        ]
                    )
                ######################################################################################################
                ######################################################################################################
                ######################################################################################################

    def make_model(self):
        """
        This method makes the SAT model and then write it into a CNF file in DIMACS format
        """

        progress("=" * 60)
        progress("SAT SOLVER — %s" % self.problem_name)
        progress("=" * 60)
        progress(
            "Variables: %d | Relations: %d" % (self.num_of_vars, self.num_of_relations)
        )
        progress("Max guess: %d | Max steps: %d" % (self.max_guess, self.max_steps))
        progress("Solver: %s" % self.sat_solver_name)
        progress("-" * 60)
        progress("MODEL GENERATION")
        progress("-" * 60)
        start_time = time.time()
        self.generate_sat_constraints()
        self.generate_boundary_conditions()
        self.cnf_file_path = os.path.join(
            TEMP_DIR,
            "cnf_mg%d_ms%d_%s.cnf"
            % (self.max_guess, self.max_steps, self.rnd_string_tmp),
        )
        elapsed_time = time.time() - start_time
        if self.log == 1:
            self.cnf_formula.to_file(self.cnf_file_path)
            progress("SAT model generated in %0.2f seconds" % elapsed_time)
            progress("Written to: %s" % self.cnf_file_path)
        else:
            progress("SAT model generated in %0.2f seconds" % elapsed_time)

    def interrupt(self, s):
        s.interrupt()

    def solve_via_satsolver(self):
        """
        Using the pysat toolkit, this method invokes a the chosen sat solver to
        solve the derived CNF formula
        """

        self.optimal = False
        self.timed_out = False
        self.termination_reason = "unknown"
        if self.sat_solver_name in solvers.SolverNames.__dict__.keys():
            sat_solver = solvers.Solver(name=self.sat_solver_name)
        else:
            progress(
                "Choose a solver from the following list please: %s"
                % ", ".join(self.supported_sat_solvers)
            )
            return
        progress("-" * 60)
        progress("SOLVING")
        progress("-" * 60)
        start_time = time.time()
        try:
            sat_solver.append_formula(self.cnf_formula)
            result = solve_sat(sat_solver, self.sat_solver_name, self.time_limit)
            self.satsolver_solution = sat_solver.get_model() if result is True else None
        except KeyboardInterrupt:
            self.termination_reason = "interrupted"
            return None
        finally:
            sat_solver.delete()
        elapsed_time = time.time() - start_time
        progress("Solving finished in %0.2f seconds" % elapsed_time)
        if result == True:
            self.termination_reason = "solution_found"
            positive = set(literal for literal in self.satsolver_solution if literal > 0)
            self.solutions = [0] * (self.max_steps + 1)
            for step in range(self.max_steps + 1):
                state_vars = [step_var(v, step) for v in self.variables]
                state_values = list(
                    map(
                        lambda x: int(
                            self.variables_dictionary[x] in positive
                        ),
                        [st_var for st_var in state_vars],
                    )
                )
                self.solutions[step] = dict(zip(state_vars, state_values))
            parse_solver_solution(self)
            return True
        elif result == False:
            self.termination_reason = "infeasible"
            progress("\n" + "=" * 60)
            progress("RESULT: UNSATISFIABLE")
            progress("The problem is UNSAT!")
            progress("Increase max_guess or max_steps and try again.")
            progress("=" * 60)
            return False
        else:
            self.timed_out = self.time_limit != -1
            self.termination_reason = "time_limit" if self.timed_out else "unknown"
            progress("\n" + "=" * 60)
            progress("RESULT: %s" % self.termination_reason.upper())
            progress("The solver stopped before finding any solution.")
            progress("=" * 60)
            return None
