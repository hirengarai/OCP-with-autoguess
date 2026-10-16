"""
Crated on july 13, 2020

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

from core.parsesolution import parse_solver_solution
from gurobipy import Env, GRB, read
from core.inputparser import read_relation_file
import os
import math
import time
import random
from config import TEMP_DIR
from core.console import progress, progress_enabled
from core.varnames import step_var, path_var


class ReduceGDtoMILP:
    """
    ReduceGDtoMILP-version4-kb
    This class reduces the guess-and-determine attack and
    key-bridging to an MILP problem, and then solves it via Gurobi

    Created by Hosein Hadipour
    version4-kb
    July 13, 2020

    mod 0: Maximization
    mod 1: Minimization
    max_guess:  The number of guessed variables in mod 0,
                and an upper bound for the number of guessed variables in mod 1
    max_steps:  Number of state copies
    """

    count = 0

    def __init__(
        self,
        inputfile_name=None,
        outputfile_name="output",
        max_guess=0,
        max_steps=0,
        direction="min",
        tikz=0,
        preprocess=1,
        D=2,
        dglayout="dot",
        drawgraph=True,
        log=0,
        threads=0,
        extra_known=None,
        prepared_data=None,
        graph_scope="targets",
        graph_view="original",
        defer_reporting=False,
    ):
        self.inputfile_name = inputfile_name
        self.rnd_string_tmp = "%030x" % random.randrange(16**30)
        self.output_dir = outputfile_name
        self.max_guess = max_guess
        self.max_steps = max_steps
        self.direction = direction
        self.dglayout = dglayout
        self.draw_graph = drawgraph
        self.graph_scope = graph_scope
        self.graph_view = graph_view
        self.defer_reporting = defer_reporting
        self.log = log
        self.threads = threads
        ###############################
        # Read and parse the input file
        parsed_data = prepared_data if prepared_data is not None else read_relation_file(
            self.inputfile_name, preprocess, D, extra_known=extra_known
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
        if self.max_guess is None:
            self.max_guess = len(self.target_variables)
            progress(
                "The number of guessed variables is set to be at most %d"
                % self.max_guess
            )
        self.lpfile_name = "milp_mg%d_ms%d_%s_%s.lp" % (
            self.max_guess,
            max_steps,
            direction,
            self.rnd_string_tmp,
        )
        self.deductions = self.generate_possible_deductions()
        # milp_variables is initialized to the variables corresponding to the initial state variables
        self.milp_variables = [step_var(v, 0) for v in self.variables]
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

    def generate_objective_function(self):
        """
        This method generates the objective function of the MILP problem
        """
        _known_set = set(self.known_variables)
        if self.direction == "max":
            objective_function = "Maximize\n"
            final_state = [step_var(v, self.max_steps) for v in self.target_variables]
            objective_function += " + ".join(final_state)
        elif self.direction == "min":
            objective_function = "Minimize\n"
            unknown_init_state_vars = [v for v in self.variables if v not in _known_set]
            if self.target_weights != None:
                wights = [
                    self.target_weights.get(v, 1) for v in unknown_init_state_vars
                ]
                weighted_init_state = zip(wights, unknown_init_state_vars)
                objective_list = [
                    "%d %s" % (w, step_var(v, 0)) for (w, v) in weighted_init_state
                ]
            else:
                objective_list = [step_var(v, 0) for v in unknown_init_state_vars]
            objective_function += " + ".join(objective_list)
        objective_function += "\n"
        return objective_function

    def generate_initial_conditions(self):
        """
        This method generates the initial constraints consisting of
        constrains corresponding to the maximum number of guessed variables, and
        number of known variables in the initial state
        """

        initial_constraints = "Subject To\n"
        _known_set = set(self.known_variables)
        unknown_vars = ["%s" % v for v in self.variables if v not in _known_set]
        unknown_init_state_vars = [step_var(v, 0) for v in unknown_vars]
        if self.target_weights != None:
            LHS1 = [
                "%d %s" % (self.target_weights.get(v, 1), step_var(v, 0)) for v in unknown_vars
            ]
            LHS1 = " + ".join(LHS1)
        else:
            LHS1 = " + ".join(unknown_init_state_vars)
        RHS1 = self.max_guess
        final_state_target_vars = [
            step_var(v, self.max_steps) for v in self.target_variables
        ]
        LHS2 = " + ".join(final_state_target_vars)
        RHS2 = len(final_state_target_vars)

        if self.direction == "max":
            # initial_constraints += '%s = %d\n' % (LHS1, RHS1)
            initial_constraints += "%s <= %d\n" % (LHS1, RHS1)
        elif self.direction == "min":
            initial_constraints += "%s <= %d\n" % (LHS1, RHS1)
            initial_constraints += "%s = %d\n" % (LHS2, RHS2)

        for v in self.known_variables:
            if v != "":
                initial_constraints += "%s = 1\n" % step_var(v, 0)

        # Limit the notguessed variables to be equal to 0 in the first step of knowledge propagation
        for v in self.notguessed_variables:
            if v != "":
                initial_constraints += "%s = 0;\n" % step_var(v, 0)
        return initial_constraints

    def generate_milp_constraints(self):
        """
        This method generates the milp constraints corresponding to the
        obtained deductions.
        """

        _lines = []
        for step in range(self.max_steps):
            for v in self.variables:
                v_old = step_var(v, step)
                v_new = step_var(v, step + 1)
                tau = len(self.deductions[v])
                v_path_variables = [path_var(v, step + 1, i) for i in range(tau)]
                self.milp_variables.extend([v_new] + v_path_variables)
                #####################################-State variable constraints-#####################################
                ######################################################################################################
                ######################################################################################################
                LHS = " + ".join(v_path_variables)
                _lines.append(
                    "\\ Constraints corresponding to the state variable %s:\n" % v_new
                )
                if tau == 1:
                    _lines.append("%s - %s = 0\n" % (v_new, LHS))
                else:
                    _lines.append("-2 %s + %s >= -1\n" % (v_new, LHS))
                    _lines.append(
                        "%d %s - %s >= 0\n" % (tau, v_new, LHS.replace("+", "-"))
                    )
                #####################################-Path variable constraints-######################################
                ######################################################################################################
                ######################################################################################################
                for i in range(tau // 2):
                    v_connected_variables = [
                        step_var(var, step) for var in self.deductions[v][i]
                    ]
                    LHS = " - ".join(v_connected_variables)
                    kapa = len(v_connected_variables)
                    _lines.append(
                        "\\ Constraints corresponding to the path variable %s:\n"
                        % v_path_variables[i]
                    )
                    if kapa == 1:
                        _lines.append("%s - %s = 0\n" % (v_path_variables[i], LHS))
                    else:
                        _lines.append(
                            "%s - %s >= %d\n" % (v_path_variables[i], LHS, 1 - kapa)
                        )
                        _lines.append(
                            "-%d %s + %s >= 0\n"
                            % (kapa, v_path_variables[i], LHS.replace("-", "+"))
                        )
                #####################################-Path variable constraints-######################################
                ######################################################################################################
                ######################################################################################################
                for i in range(tau // 2, tau):
                    v_connected_variables = [
                        step_var(var, step) for var in self.deductions[v][i]
                    ]
                    LHS = " - ".join(v_connected_variables)
                    kapa = len(v_connected_variables)
                    _lines.append(
                        "\\ Constraints corresponding to the path variable %s:\n"
                        % v_path_variables[i]
                    )
                    if kapa == 1:
                        _lines.append("%s - %s = 0\n" % (v_path_variables[i], LHS))
                    else:
                        _lines.append(
                            "%s - %s >= %d\n" % (v_path_variables[i], LHS, 1 - kapa)
                        )
                        _lines.append(
                            "-%d %s + %s >= 0\n"
                            % (kapa, v_path_variables[i], LHS.replace("-", "+"))
                        )
                ######################################################################################################
                ######################################################################################################
                ######################################################################################################
                # Given that the order of putting constraints into an LP file have a great impact on the performance of
                # Gurobi (and other CP solvers), user may want to change the order of constraints inside the generated
                # LP file in order to find a more suitable ordering. It is not known which odering might be the best from
                # the theoretical point of view in general. However, according to my experiences it may be better to put the connected
                # relations closer to each other. For example, change the order of the above blocks to see what impact it has
                # on the performance.
        return "".join(_lines)

    def declare_binary_variables(self):
        """
        This function declares the binary variables into the generated LP file
        """

        return "Binary\n" + "".join("%s\n" % v for v in self.milp_variables)

    def make_model(self):
        """
        This method makes the MILP model, and then write it into an LP file
        """

        progress("Generating the MILP model ...")
        start_time = time.time()
        lp_str = self.generate_objective_function()
        lp_str += self.generate_initial_conditions()
        lp_str += self.generate_milp_constraints()
        lp_str += self.declare_binary_variables()
        lp_str += "End\n"
        lp_file_path = os.path.join(TEMP_DIR, self.lpfile_name)
        elapsed_time = time.time() - start_time
        with open(lp_file_path, "w") as lpfile:
            lpfile.write(lp_str)
        if self.log == 1:
            progress(
                "MILP model was generated, and written into %s after %0.2f seconds"
                % (lp_file_path, elapsed_time)
            )
        else:
            progress("MILP model was generated after %0.2f seconds" % elapsed_time)

    def parse_and_write_solution(self):
        """Compatibility entry point for the shared validated report writer."""
        return parse_solver_solution(self)

    def solve_model(self):
        """
        This method uses Gurobi to solve the obtained MILP problem
        """
        self.optimal = False
        self.timed_out = False
        self.termination_reason = "unknown"
        self.lower_bound = None
        if self.time_limit < 0 and self.time_limit != -1:
            raise ValueError("Time limit must be nonnegative or -1")
        lpfile_path = os.path.join(TEMP_DIR, self.lpfile_name)
        self._gurobi_env = Env(params={"OutputFlag": int(progress_enabled())})
        self.milp_model = read(lpfile_path, env=self._gurobi_env)
        if self.log == 0:
            os.remove(lpfile_path)
        if self.time_limit != -1:
            self.milp_model.params.TimeLimit = self.time_limit
        # 0 (default: Gurobi strikes a balance between finding feasible solution and proving the optimality)
        self.milp_model.params.MIPFocus = 0
        if self.direction == "min":
            # Guess costs are integers. Require an exact bound before claiming
            # optimality, including inputs with large non-unit weights.
            self.milp_model.params.MIPGap = 0
            self.milp_model.params.MIPGapAbs = 0
        # 1 (quickly find a feasible solution)
        # 2 (proving optimality is in priority)
        # 3 (focus on the best bound)
        self.milp_model.params.Threads = self.threads  # 0 = use all available cores
        self.milp_model.params.OutputFlag = int(progress_enabled())

        start_time = time.time()
        ##########################
        ##########################
        interrupted = False
        try:
            self.milp_model.optimize()
        except KeyboardInterrupt:
            # Native Gurobi normally returns INTERRUPTED, but retain any
            # incumbent if Python receives the interrupt itself.
            interrupted = True
        self.optimal = self.direction == "min" and self.milp_model.Status == GRB.OPTIMAL
        self.timed_out = self.milp_model.Status == GRB.TIME_LIMIT
        if interrupted or self.milp_model.Status == GRB.INTERRUPTED:
            self.optimal = False
            self.termination_reason = "interrupted"
        elif self.timed_out:
            self.termination_reason = "time_limit"
        elif self.optimal:
            self.termination_reason = "optimal"
        elif self.milp_model.Status == GRB.INFEASIBLE:
            self.termination_reason = "infeasible"
        elif self.milp_model.SolCount:
            self.termination_reason = "solution_found"
        if self.direction == "min":
            try:
                bound = float(self.milp_model.ObjBound)
                if math.isfinite(bound):
                    self.lower_bound = bound
            except (AttributeError, GurobiError):
                # Some early stops do not expose a native objective bound.
                pass
        ##########################
        ##########################
        elapsed_time = time.time() - start_time
        progress("Solving process was finished after %0.2f seconds" % elapsed_time)

        if self.milp_model.SolCount > 0:
            # SolCount, rather than a small allowlist of stopping statuses,
            # determines whether a usable current-run incumbent exists.
            self.objval = self.milp_model.objval
            self.solutions = [0] * (self.max_steps + 1)
            for step in range(self.max_steps + 1):
                state_vars = [step_var(v, step) for v in self.variables]
                state_values = list(
                    map(lambda x: int(round(self.milp_model.getVarByName(x).X)), state_vars)
                )
                self.solutions[step] = dict(zip(state_vars, state_values))
            if self.log == 1:
                gurobi_solution_file_name = "grbsol_mg%d_ms%d_%s.sol" % (
                    self.max_guess,
                    self.max_steps,
                    self.direction,
                )
                grb_solution_file_path = os.path.join(
                    TEMP_DIR, gurobi_solution_file_name
                )
                self.milp_model.write(grb_solution_file_path)
            parse_solver_solution(self)
            return True
        elif self.milp_model.Status == GRB.INFEASIBLE:
            progress("The obtained milp model is infeasible")
            return False
        else:
            progress("No solution found (stopping reason: %s)." % self.termination_reason)
            return None
