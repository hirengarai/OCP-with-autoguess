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
from math import ceil
from pysat import solvers
from pysat import formula
import random
from .inputparser import read_relation_file
import z3
from core.parsesolution import parse_solver_solution
from config import TEMP_DIR
from core.console import progress
from core.varnames import step_var, path_var
from core.solverresult import solve_sat


class ReduceGDtoZ3SMT:
    """
    ReduceGDtoZ3SMT-version 2
    Using the Z3 SMT solver, this class reduces the guess-and-determine attack and
    key-bridging to an SMT (or SAT) problem, and then solves it via Z3 (or a SAT solver).

    Created by Hosein Hadipour
    July 13, 2020

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
        graph_scope="targets",
        graph_view="original",
        defer_reporting=False,
    ):
        self.inputfile_name = inputfile_name
        self.output_dir = outputfile_name
        self.rnd_string_tmp = "%030x" % random.randrange(16**30)
        self.max_guess = max_guess
        self.max_steps = max_steps
        self.sat_solver_name = sat_solver
        self.supported_sat_solvers = [name for name in vars(solvers.SolverNames) if not name.startswith("_")]
        if self.sat_solver_name not in self.supported_sat_solvers:
            raise ValueError("Unsupported SAT solver: %s" % self.sat_solver_name)
        self.dglayout = dglayout
        self.draw_graph = drawgraph
        self.graph_scope = graph_scope
        self.graph_view = graph_view
        self.defer_reporting = defer_reporting
        self.log = log
        ###############################
        # Read and parse the input file
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
        self.deductions = self.generate_possible_deductions()
        self.solver = z3.Solver()
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
            for rel in sym_index.get(v, []):
                temp = rel.copy()
                temp.remove(v)
                possible_deductions[v].append(temp)
            for rel in impl_index.get(v, []):
                temp = rel.copy()
                temp.remove(v)
                possible_deductions[v].append(temp)
        return possible_deductions

    def generate_initial_conditions(self):
        """
        This method generates the initial constraints consisting of
        constrains corresponding to the maximum number of guessed, and
        known variables in the initial state
        """
        # initial_state_vars = list(map(z3.Bool, ['%s_%d' % (
        #     v, 0) for v in self.variables if v not in self.known_variables]))
        # self.solver.add(z3.Sum([z3.If(initial_state_vars[i], 1, 0)
        #                     for i in range(len(initial_state_vars))]) <= self.max_guess)
        _known_set = set(self.known_variables)
        weights = self.target_weights or {}
        initial_state_vars = [(z3.Bool(step_var(v, 0)), weights.get(v, 1))
                              for v in self.variables if v not in _known_set]
        if initial_state_vars != []:
            self.solver.add(
                z3.PbLe(
                    [initial_state_vars[i] for i in range(len(initial_state_vars))],
                    self.max_guess,
                )
            )

        final_state_target_vars = list(
            map(z3.Bool, [step_var(v, self.max_steps) for v in self.target_variables])
        )
        self.solver.add(z3.And(final_state_target_vars) == True)
        for v in self.known_variables:
            if v != "":
                self.solver.add(z3.Bool(step_var(v, 0)) == True)
        for v in self.notguessed_variables:
            if v != "":
                self.solver.add(z3.Bool(step_var(v, 0)) == False)

    def generate_smt_constraints(self):
        """
        This method generates the smt constraints corresponding to the
        obtained deductions
        """
        for step in range(self.max_steps):
            for v in self.variables:
                v_new = step_var(v, step + 1)
                tau = len(self.deductions[v])
                v_path_variables = [path_var(v, step + 1, i) for i in range(tau)]
                #####################################-State variable constraints-#####################################
                ######################################################################################################
                ######################################################################################################
                LHS = z3.Or(list(map(z3.Bool, v_path_variables)))
                RHS = z3.Bool(v_new)
                self.solver.add(LHS == RHS)
                #####################################-Path variable constraints-######################################
                ######################################################################################################
                ######################################################################################################
                for i in range(0, tau):
                    v_connected_variables = list(
                        map(
                            z3.Bool,
                            [step_var(var, step) for var in self.deductions[v][i]],
                        )
                    )
                    LHS = z3.And(v_connected_variables)
                    RHS = z3.Bool(v_path_variables[i])
                    self.solver.add(LHS == RHS)
                ######################################################################################################
                ######################################################################################################
                ######################################################################################################

    def make_model(self):
        """
        This method makes the SMT model, and then write it into an smt file
        """
        progress("Generating the SMT model ...")
        start_time = time.time()
        self.generate_initial_conditions()
        self.generate_smt_constraints()
        z3.set_param(smtlib2_compliant=True)
        smt2_model = self.solver.to_smt2()
        file_path = os.path.join(
            TEMP_DIR, "smtmodel_mg%d_ms%d.smt2" % (self.max_guess, self.max_steps)
        )
        elapsed_time = time.time() - start_time
        if self.log == 1:
            with open(file_path, "w") as outputfile:
                outputfile.write(smt2_model)
            progress(
                "SMT model was generated after %0.2f seconds and was written into %s"
                % (elapsed_time, file_path)
            )
        else:
            progress("SMT model was generated after %0.2f seconds" % elapsed_time)

    def convert_smt_to_cnf(self):
        """
        This method encodes the obtained SMT problem to CNF

        Goal is a collection of constraints we want to find a solution or show to be unsatisfiable (infeasible).

        Goals are processed using Tactics. A Tactic transforms a goal into a set of subgoals.
        A goal has a solution if one of its subgoals has a solution.
        A goal is unsatisfiable if all subgoals are unsatisfiable.
        """
        G = z3.Goal()
        G.add(self.solver.assertions())
        # z3.set_option("sat.cardinality.encoding", "circuit")
        # z3.set_option("sat.cardinality.encoding", "sorting")
        cnf_format = z3.Then("simplify", "card2bv", "tseitin-cnf")
        # cnf_format = z3.Then("card2bv", "tseitin-cnf")
        # cnf_format = z3.Tactic("card2bv")
        progress("Converting the SMT problem to CNF in dimacs format ...")
        start_time = time.time()
        temp = cnf_format(G)
        """
        Regarding dimcas mehod:
        'dimacs' convert a goal into a DIMACS formatted string. The goal must be in CNF.
        You can convert a goal to CNF by applying the tseitin-cnf tactic. Bit-vectors are not
        automatically converted to Booleans either, so if the caller intends to preserve satisfiability,
        it should apply bit-blasting tactics. Quantifiers and theory atoms will not be encoded.
        """
        dimacs_format = temp[0].dimacs()
        conversion_table = list(
            filter(lambda x: x[0:2] == "c ", dimacs_format.split("\n"))
        )
        self.dimacs_vars_dict = dict()
        for row in conversion_table:
            row = row.split(" ")[1:]
            self.dimacs_vars_dict[row[1]] = int(row[0])
        dimacs_file_name = "cnf_mg%d_ms%d_%s.cnf" % (
            self.max_guess,
            self.max_steps,
            self.rnd_string_tmp,
        )
        self.cnf_file_path = os.path.join(TEMP_DIR, dimacs_file_name)
        with open(self.cnf_file_path, "w") as outputfile:
            outputfile.write(dimacs_format)
        elapsed_time = time.time() - start_time
        if self.log == 1:
            progress(
                "SMT was converted to the CNF after %0.2f seconds and was written into %s"
                % (elapsed_time, self.cnf_file_path)
            )
        else:
            progress("SMT was converted to the CNF after %0.2f seconds" % elapsed_time)

    def interrupt(self, s):
        s.interrupt()

    def solve_via_satsolver(self):
        """
        Using the pysat toolkit, this method invokes the chosen sat solver to
        solve the derived CNF formula
        """

        self.optimal = False
        self.timed_out = False
        self.termination_reason = "unknown"
        self.convert_smt_to_cnf()
        cnf_formula = formula.CNF(self.cnf_file_path)
        sat_solver = solvers.Solver(name=self.sat_solver_name)
        sat_solver.append_formula(cnf_formula)
        progress("\nSolving via a SAT solver ...")
        start_time = time.time()
        try:
            result = solve_sat(sat_solver, self.sat_solver_name, self.time_limit)
            self.satsolver_solution = sat_solver.get_model() if result is True else None
        except KeyboardInterrupt:
            self.termination_reason = "interrupted"
            result = None
        finally:
            sat_solver.delete()
        elapsed_time = time.time() - start_time
        progress("Time used by SAT solver: %0.2f seconds" % elapsed_time)
        if result == True:
            self.termination_reason = "solution_found"
            positive = set(v for v in self.satsolver_solution if v > 0)
            self.solutions = [0] * (self.max_steps + 1)
            for step in range(self.max_steps + 1):
                state_vars = [step_var(v, step) for v in self.variables]
                state_values = list(
                    map(
                        lambda x: int(
                            self.dimacs_vars_dict[x] in positive
                        ),
                        [st_var for st_var in state_vars],
                    )
                )
                self.solutions[step] = dict(zip(state_vars, state_values))
            parse_solver_solution(self)
        elif result == False:
            self.termination_reason = "infeasible"
            progress("The problem is UNSAT!\n")
        else:
            if self.termination_reason != "interrupted":
                self.timed_out = self.time_limit != -1
                self.termination_reason = "time_limit" if self.timed_out else "unknown"
            progress("The solver stopped before finding any solution (%s)." % self.termination_reason)
        if self.log == 0:
            os.remove(self.cnf_file_path)
        return result

    def solve_via_smtsolver(self):
        """
        This method uses Z3 to solve the obtained SMT problem
        """
        self.optimal = False
        self.timed_out = False
        self.termination_reason = "unknown"
        if self.time_limit < 0 and self.time_limit != -1:
            raise ValueError("Time limit must be nonnegative or -1")
        if self.time_limit == 0:
            self.timed_out = True
            self.termination_reason = "time_limit"
            return None
        # If you want to produce a new solution at each new run uncomment this line
        z3.set_param("smt.random_seed", int(time.time()))
        # If you want get the same solution as before, uncomment this line
        # z3.set_param('smt.random_seed', 1370)
        # z3.set_param(verbose=2)
        # z3.set_param(memory_max_size=8192)
        # self.solver.set("sat.cardinality.solver", True)
        z3.set_param("parallel.enable", True)
        progress(
            "Checking the satisfiablity of the obtained SMT model using z3-solver ..."
        )
        timeout = 0 if self.time_limit == -1 else max(1, ceil(self.time_limit * 1000))
        self.solver.set(timeout=timeout)
        start_time = time.time()
        ##########################
        ##########################
        try:
            result = self.solver.check()
        except KeyboardInterrupt:
            self.termination_reason = "interrupted"
            return None
        ##########################
        ##########################
        elapsed_time = time.time() - start_time
        progress("Checking was finished after %0.2f seconds" % elapsed_time)

        solver_statistics = self.solver.statistics()
        # progress(solver_statistics)
        if result == z3.sat:
            self.termination_reason = "solution_found"
            # self.solution = self.solver.model()
            # Extract the solution
            self.solver_model = self.solver.model()
            self.solutions = [0] * (self.max_steps + 1)
            for step in range(self.max_steps + 1):
                state_vars = [step_var(v, step) for v in self.variables]
                z3_state_vars = list(
                    map(z3.Bool, [step_var(v, step) for v in self.variables])
                )
                state_values = list(
                    map(
                        int,
                        [
                            z3.is_true(self.solver_model[st_var])
                            for st_var in z3_state_vars
                        ],
                    )
                )
                self.solutions[step] = dict(zip(state_vars, state_values))
            parse_solver_solution(self)
        elif result == z3.unsat:
            self.termination_reason = "infeasible"
            progress(
                "The model is UNSAT!\nIncrease the max_guess, and max_steps paramters, and try again."
            )
        elif result == z3.unknown:
            reason = self.solver.reason_unknown().lower()
            if "timeout" in reason:
                self.timed_out = True
                self.termination_reason = "time_limit"
            elif "interrupt" in reason or "cancel" in reason:
                self.termination_reason = "interrupted"
            progress("The solver stopped before finding any solution (%s)." % self.termination_reason)
        return True if result == z3.sat else False if result == z3.unsat else None
