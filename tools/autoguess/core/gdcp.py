'''
Created on Oct 4, 2020

@author: Hosein Hadipour
@contact: hsn.hadipour@gmail.com
'''

import os
import time
import random
import minizinc
from core.inputparser import read_relation_file
from core.parsesolution import parse_solver_solution
# from core.graphdrawer import draw_graph
from config import TEMP_DIR
import datetime
import subprocess


try:
    output = subprocess.run(['minizinc', '--solvers'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    solvers_str = output.stdout.decode("utf-8").lower()
    if "com.google.ortools.sat" in solvers_str or "cp-sat" in solvers_str or "or tools" in solvers_str:
        ortools_available = True
        print("OR Tools is available")
    else:
        ortools_available = False
        print("OR Tools is not available")
except FileNotFoundError:
    ortools_available = False
    # print("MiniZinc not found")

class ReduceGDtoCP:
    count = 0

    def __init__(self, inputfile_name=None, outputfile_name='output', max_guess=0, max_steps=0, cp_solver_name='gecode',
        cp_optimization=0, tikz=0, preprocess=1, D=2, dglayout="dot", log="0"):
        self.inputfile_name = inputfile_name
        self.output_dir = outputfile_name     
        self.rnd_string_tmp = '%030x' % random.randrange(16**30)
        self.max_guess = max_guess
        self.max_steps = max_steps
        self.cp_solver_name = cp_solver_name
        self.dglayout = dglayout
        self.log = log  

        # self.supported_cp_solvers = [
        #     'gecode', 'chuffed', 'cbc', 'gurobi', 'picat', 'scip', 'choco', 'or-tools', 'cp-sat', 'com.google.ortools.sat']
        # self.supported_cp_solvers = [
        #     'cbc',         # COIN-BC
        #     'coinbc',      # COIN-BC alternative tag
        #     'cp',          # OR-Tools CP-SAT tag
        #     'cp-sat',      # OR-Tools CP-SAT full name
        #     'gurobi',      # Gurobi
        #     'highs',       # HiGHS
        #     'scip',        # SCIP
        #     'mip',         # SCIP alternative tag
        #     'xpress',      # Xpress
        #     'gecode'
        # ]
        self.supported_cp_solvers = ['gecode', 'chuffed', 'cbc', 'coinbc', 'cp', 'cp-sat', 'com.google.ortools.sat',
        'gurobi', 'highs', 'scip', 'mip', 'xpress', 'picat', 'choco', 'or-tools']
        assert(self.cp_solver_name in self.supported_cp_solvers)                

        if ortools_available:
            if self.cp_solver_name in ["or-tools", "cp-sat", "com.google.ortools.sat"]:
                try:
                    self.cp_solver = minizinc.Solver.lookup("com.google.ortools.sat")
                    self.cp_solver_name = "com.google.ortools.sat"
                except:
                    self.cp_solver = minizinc.Solver.lookup("cp-sat")
                    self.cp_solver_name = "cp-sat"
            else:
                self.cp_solver = minizinc.Solver.lookup(self.cp_solver_name)
        else:
            self.cp_solver = minizinc.Solver.lookup(self.cp_solver_name)

        self.cp_optimization = cp_optimization
        self.nthreads = 16
        self.cp_boolean_variables = []
        self.cp_constraints = ''

        parsed_data = read_relation_file(self.inputfile_name, preprocess, D, self.log)
        self.dummy_mapping = parsed_data.get('dummy_mapping', {})
        self.problem_name = parsed_data['problem_name']
        self.variables = parsed_data['variables']
        self.known_variables = parsed_data['known_variables']
        self.target_variables = parsed_data['target_variables']
        self.notguessed_variables = parsed_data['notguessed_variables']
        self.symmetric_relations = parsed_data['symmetric_relations']
        self.implication_relations = parsed_data['implication_relations']
        self.num_of_relations = len(self.symmetric_relations) + len(self.implication_relations)
        self.num_of_vars = len(self.variables)

        if (self.max_guess is None) or (self.max_guess > len(self.target_variables)):
            if self.notguessed_variables is None:
                self.max_guess = len(self.target_variables)
            else:
                self.max_guess = len(self.variables)
            print('Number of guessed variables is set to be at most %d' % self.max_guess)   
        self.deductions = self.generate_possible_deductions()        
        self.time_limit = -1
        self.tikz = tikz

    def ordered_set(self, seq):
        seen = set()
        seen_add = seen.add
        return [x for x in seq if not (x in seen or seen_add(x))]

    def generate_possible_deductions(self):
        possible_deductions = {}
        for v in self.variables:
            possible_deductions[v] = [[v]]
            for rel in self.symmetric_relations:
                if v in rel:
                    temp = rel.copy()
                    temp.remove(v)
                    possible_deductions[v].append(temp)
            for rel in self.implication_relations:
                if v == rel[-1]:
                    temp = rel.copy()
                    temp.remove(v)
                    possible_deductions[v].append(temp)
        return possible_deductions
    
    def update_variables_list(self, new_vars):
        for v in new_vars:
            if v not in self.cp_boolean_variables:
                self.cp_boolean_variables.append(v)
        
    def generate_initial_conditions(self):
        initial_state_vars = ['%s_%d' % (v, 0) for v in self.variables if v not in self.known_variables]
        if initial_state_vars:
            self.update_variables_list(initial_state_vars)
            self.cp_constraints += 'constraint %s <= %d;\n' % (' + '.join(initial_state_vars), self.max_guess)

        final_state_target_vars = ['%s_%d' % (v, self.max_steps) for v in self.target_variables]
        self.update_variables_list(final_state_target_vars)
        for fv in final_state_target_vars:
            self.cp_constraints += 'constraint %s = 1;\n' % fv

        for v in self.known_variables:
            if v != '':
                self.cp_constraints += 'constraint %s_0 = 1;\n' % v

        for v in self.notguessed_variables:
            if v != '':
                self.cp_constraints += 'constraint %s_0 = 0;\n' % v

    def generate_objective_function(self):
        initial_state_vars = ['%s_%d' % (v, 0) for v in self.variables if v not in self.known_variables]
        if self.cp_optimization == 1 and initial_state_vars:
            self.cp_constraints += 'solve minimize %s;\n' % ' + '.join(initial_state_vars)
        else:
            self.cp_constraints += 'solve satisfy;\n'

    def generate_cp_constraints(self):
        for step in range(self.max_steps):
            for v in self.variables:
                v_new = f"{v}_{step + 1}"
                tau = len(self.deductions[v])
                v_path_variables = [f"{v}_{step + 1}_{i}" for i in range(tau)]
                self.update_variables_list([v_new] + v_path_variables)
                self.cp_constraints += f"constraint {v_new} <-> {' \\/ '.join(v_path_variables)};\n"
                for i in range(tau):
                    v_connected_variables = [f"{var}_{step}" for var in self.deductions[v][i]]
                    self.update_variables_list(v_connected_variables)
                    self.cp_constraints += f"constraint {v_path_variables[i]} <-> {' /\\ '.join(v_connected_variables)};\n"

    def make_model(self):
        print('Generating the CP model ...')
        start_time = time.time()
        self.generate_cp_constraints()
        self.generate_initial_conditions()
        boolean_variables = '\n'.join(f"var bool: {bv};" for bv in self.cp_boolean_variables)
        self.cp_constraints = boolean_variables + '\n' + self.cp_constraints
        self.generate_objective_function()
        self.cp_file_path = os.path.join(TEMP_DIR, f'cpmodel_mg{self.max_guess}_ms{self.max_steps}_{self.rnd_string_tmp}.mzn')
        elapsed_time = time.time() - start_time
        print(f'CP model was generated after {elapsed_time:.2f} seconds')
        with open(self.cp_file_path, 'w') as f:
            f.write(self.cp_constraints)
        self.cp_model = minizinc.Model()
        self.cp_model.output_type = dict
        self.cp_model.add_file(self.cp_file_path)
        self.cp_inst = minizinc.Instance(solver=self.cp_solver, model=self.cp_model)

    def solve_via_cpsolver(self):
        rand_int = random.randint(0, 1000) if '-r' in self.cp_solver.stdFlags else None
        time_limit = datetime.timedelta(seconds=self.time_limit) if self.time_limit != -1 else None
        nthreads = self.nthreads if '-p' in self.cp_solver.stdFlags else None
        print(f'Solving the CP model with {self.cp_solver_name} ...')
        start_time = time.time()
        result = self.cp_inst.solve(timeout=time_limit, processes=nthreads, random_seed=rand_int)
        if self.log == 0:
            os.remove(self.cp_file_path)
        elapsed_time = time.time() - start_time
        print(f'Solving process was finished after {elapsed_time:.2f} seconds')
        if result.status in [minizinc.Status.OPTIMAL_SOLUTION, minizinc.Status.SATISFIED, minizinc.Status.ALL_SOLUTIONS]:
            self.solutions = [0] * (self.max_steps + 1)
            for step in range(self.max_steps + 1):
                state_vars = ['%s_%d' % (v, step) for v in self.variables]
                state_values = list(map(lambda vx: int(result.solution[vx]), state_vars))
                self.solutions[step] = dict(zip(state_vars, state_values))
            parse_solver_solution(self)
            # draw_graph(self.vertices, self.edges, self.known_variables, self.guessed_vars,
            #            self.output_dir, self.tikz, self.dglayout)
            return True
        elif result.status == minizinc.Status.UNSATISFIABLE:
            print('The model is UNSAT!\nIncrease the max_guess or max_steps parameters and try again.')
            return False
        elif result.status == minizinc.Status.ERROR:
            print(result.status)
        else:
            print('Solver could not find the solution. Perhaps more time is needed!')
            return None