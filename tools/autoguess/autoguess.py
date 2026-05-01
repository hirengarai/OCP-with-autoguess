#!/usr/bin/python3
# -*- coding: UTF-8 -*-
"""
Created on Aug 23, 2020

@author: Hosein Hadipour
@contact: hsn.hadipour@gmail.com

For more information, feedback or any questions, please contact hsn.hadipour@gmail.com

MIT License

Copyright (c) 2021 Hosein Hadipour

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from core import search
from argparse import ArgumentParser, RawTextHelpFormatter
import os
import sys
from config import TEMP_DIR


def _resolve_dynamic_defaults(params):
    """
    If maxguess or maxsteps were not supplied by the user, derive sensible
    defaults from the input file:
      maxguess  -> number of target variables
      maxsteps  -> number of all variables (before preprocessing)
    A lightweight parse (preprocess=0) is used so this is fast.
    """
    if params["maxguess"] is not None and params["maxsteps"] is not None:
        return
    from core.inputparser import read_relation_file

    parsed = read_relation_file(params["inputfile"], preprocess=0, D=2, log=0)
    if params["maxguess"] is None:
        params["maxguess"] = len(parsed["target_variables"])
    if params["maxsteps"] is None:
        params["maxsteps"] = len(parsed["variables"])


def startsearch(tool_parameters):
    """
    Starts the search tool for the given parameters
    """

    _resolve_dynamic_defaults(tool_parameters)

    # Handle program flow
    if tool_parameters["solver"] == "milp":
        search.search_using_milp(tool_parameters)
    elif tool_parameters["solver"] == "sat":
        search.search_using_sat(tool_parameters)
    elif tool_parameters["solver"] == "smt":
        search.search_using_smt(tool_parameters)
    elif tool_parameters["solver"] == "cp":
        search.search_using_cp(tool_parameters)
    elif tool_parameters["solver"] == "groebner":
        print(
            "[ERROR] Groebner solver is not supported in this version (requires SageMath)."
        )
        print(
            "        Please use the original autoguess: https://github.com/hadipourh/autoguess"
        )
        print(
            "        Or choose another solver: sat, cp, milp, smt, mark, elim, propagate."
        )
        sys.exit(1)
    elif tool_parameters["solver"] == "mark":
        search.search_using_mark(tool_parameters)
    elif tool_parameters["solver"] == "elim":
        search.search_using_elim(tool_parameters)
    elif tool_parameters["solver"] == "propagate":
        search.search_using_propagate(tool_parameters)
    else:
        print(
            "Choose the solver from the following options please: cp, milp, sat, smt, mark, elim, propagate"
        )
    return


def checkenvironment():
    """
    Basic checks if the environment is set up correctly
    """

    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    return


def loadparameters(args):
    """
    Get parameters from the argument list and inputfile.
    """

    # Load default values
    params = {
        "inputfile": "./ciphers/AES/relationfile_aes1kp_1r_mg6_ms14.txt",
        "outputfile": "output",
        "maxguess": None,
        "maxsteps": None,
        "solver": "sat",
        "milpdirection": "min",
        "timelimit": -1,
        "cpsolver": "cp-sat",
        "satsolver": "cadical153",
        "smtsolver": "z3",
        "cpoptimization": 1,
        "tikz": 0,
        "preprocess": 0,
        "D": 2,
        "term_ordering": "degrevlex",
        "overlapping_number": 2,
        "cnf_to_anf_conversion": "simple",
        "dglayout": "dot",
        "log": 0,
        "known": None,
        "threads": 0,
        "drawgraph": True,
        "findmin": False,
        "reducebasis": False,
    }

    # Override parameters if they are set on commandline
    if args.inputfile:
        params["inputfile"] = args.inputfile[0]

    if args.outputfile:
        params["outputfile"] = args.outputfile[0]

    if args.maxguess:
        params["maxguess"] = args.maxguess[0]

    if args.maxsteps:
        params["maxsteps"] = args.maxsteps[0]

    if args.solver:
        params["solver"] = args.solver[0]

    if args.milpdirection:
        params["milpdirection"] = args.milpdirection[0]

    if args.cpsolver:
        params["cpsolver"] = args.cpsolver[0]

    if args.smtsolver:
        params["smtsolver"] = args.smtsolver[0]

    if args.satsolver:
        params["satsolver"] = args.satsolver[0]

    if args.timelimit:
        params["timelimit"] = args.timelimit[0]

    if args.cpoptimization:
        params["cpoptimization"] = args.cpoptimization[0]

    if args.tikz:
        params["tikz"] = args.tikz[0]

    if args.preprocess:
        params["preprocess"] = args.preprocess[0]

    if args.D:
        params["D"] = args.D[0]

    if args.term_ordering:
        params["term_ordering"] = args.term_ordering[0]

    if args.overlapping_number:
        params["overlapping_number"] = args.overlapping_number[0]

    if args.cnf_to_anf_conversion:
        params["cnf_to_anf_conversion"] = args.cnf_to_anf_conversion[0]

    if args.dglayout:
        params["dglayout"] = args.dglayout[0]

    if args.log:
        params["log"] = args.log[0]

    if args.known:
        params["known"] = args.known

    if args.threads:
        params["threads"] = args.threads[0]

    if args.nograph:
        params["drawgraph"] = False

    if args.findmin:
        params["findmin"] = True

    if args.reducebasis:
        params["reducebasis"] = True

    # If reducebasis is requested, route to that handler
    if params["reducebasis"]:
        params["_action"] = "reducebasis"

    return params


def main():
    """
    Parse the arguments and start the request functionality with the provided
    parameters.
    """
    parser = ArgumentParser(
        description="This tool automates the Guess-and-Determine"
        " and Key-Bridging techniques"
        " using the variety of CP, MILP, SMT and SAT solvers",
        formatter_class=RawTextHelpFormatter,
    )
    parser.add_argument(
        "-i", "--inputfile", nargs=1, help="Use an input file in plain text format"
    )
    parser.add_argument(
        "-o",
        "--outputfile",
        nargs=1,
        help="Use an output file to" " write the output into it",
    )
    parser.add_argument(
        "-mg",
        "--maxguess",
        nargs=1,
        type=int,
        help="An upper bound for the number of guessed variables",
    )
    parser.add_argument(
        "-ms",
        "--maxsteps",
        nargs=1,
        type=int,
        help="An integer number specifying the depth of search",
    )
    parser.add_argument(
        "-s",
        "--solver",
        nargs=1,
        choices=["cp", "milp", "sat", "smt", "groebner", "mark", "elim", "propagate"],
        help="cp = solve the problem using CP solvers\n"
        "milp = solve the problem using the MILP solvers\n"
        "sat = solve the problem using the SAT solvers\n"
        "smt = solve the problem using the SMT solvers\n"
        "mark = use the marking algorithm\n"
        "elim = use the elimination algorithm\n"
        "propagate = use pure knowledge propagation (no solver)\n"
        "groebner = not supported in this version\n",
    )
    parser.add_argument(
        "-milpd",
        "--milpdirection",
        nargs=1,
        choices=["min", "max"],
        help="min = convert the problem to a minimization problem looking for the minimal set of guessed variables.\n"
        "max = convert the problem to a maximization problem in which the known variables in final state are maximized,\n"
        'when the size of the initially known variables is equal or less than "maxguess"\n',
    )
    parser.add_argument(
        "-cps",
        "--cpsolver",
        nargs=1,
        type=str,
        choices=[
            "gecode",
            "chuffed",
            "coin-bc",
            "gurobi",
            "highs",
            "picat",
            "scip",
            "choco",
            "or-tools",
            "cp-sat",
            "cbc",
            "mip",
        ],
        help="\n",
    )
    parser.add_argument(
        "-sats",
        "--satsolver",
        nargs=1,
        type=str,
        choices=[
            "cadical103",
            "cadical153",
            "cadical195",
            "glucose3",
            "glucose4",
            "lingeling",
            "maplechrono",
            "maplecm",
            "maplesat",
            "minicard",
            "minisat22",
            "minisat-gh",
        ],
        help="\n",
    )
    parser.add_argument(
        "-smts",
        "--smtsolver",
        nargs=1,
        type=str,
        choices=["msat", "cvc4", "cvc5", "z3", "yices", "btor", "bdd"],
        help="\n",
    )
    parser.add_argument(
        "-cpopt",
        "--cpoptimization",
        nargs=1,
        type=int,
        choices=[0, 1],
        help='1: Looking for a minimal guess basis \n0: Decides whether a guess basis of size up to "maxguess" exists\n',
    )
    parser.add_argument(
        "-tl",
        "--timelimit",
        nargs=1,
        type=int,
        help="Set a timelimit for the search in seconds\n",
    )
    parser.add_argument(
        "-tk",
        "--tikz",
        nargs=1,
        type=int,
        help="Set to 1 to generate the tikz code of the determination flow graph\n",
    )
    parser.add_argument(
        "-prep",
        "--preprocess",
        nargs=1,
        type=int,
        help="Set to 1 to enable the preprocessing phase\n",
    )
    parser.add_argument(
        "-D",
        "--D",
        nargs=1,
        type=int,
        help="It specifies the degree of Macaulay matrix generated in preprocessing phase\n",
    )
    parser.add_argument(
        "-tord",
        "--term_ordering",
        nargs=1,
        type=str,
        help='A degree compatible term ordering such as "degrevlex" or "deglex"\n',
    )
    parser.add_argument(
        "-oln",
        "--overlapping_number",
        nargs=1,
        type=int,
        help="A positive integer specifying the overlapping number in block-wise CNF to ANF conversion\n",
    )
    parser.add_argument(
        "-cnf2anf",
        "--cnf_to_anf_conversion",
        nargs=1,
        type=str,
        choices=["simple", "blockwise"],
        help="It specifies the CNF to ANF conversion method\n",
    )
    parser.add_argument(
        "-dgl",
        "--dglayout",
        nargs=1,
        type=str,
        choices=[
            "dot",
            "circo",
            "twopi",
            "fdp",
            "neato",
            "nop",
            "nop1",
            "nop2",
            "osage",
            "patchwork",
            "sfdp",
        ],
        help="It specifies the layout of determination flow graph\n",
    )
    parser.add_argument(
        "-log",
        "--log",
        nargs=1,
        type=int,
        choices=[0, 1],
        help="By setting this parameter to 1, the intermediate generated files such as CP/MILP/SAT models as well as\n"
        "some intermediate results are stored inside the temp folder\n",
    )
    parser.add_argument(
        "-kn",
        "--known",
        nargs="+",
        type=str,
        help="Comma-separated list of extra known variables (in addition to those in the relation file)\n",
    )
    parser.add_argument(
        "-t",
        "--threads",
        nargs=1,
        type=int,
        help="Number of threads to use for MILP/CP solvers (0 = auto)\n",
    )
    parser.add_argument(
        "--nograph",
        action="store_true",
        help="Skip generation of the determination flow graph\n",
    )
    parser.add_argument(
        "--findmin",
        action="store_true",
        help="Find the minimum number of guessed variables (incremental for SAT, descent for others)\n",
    )
    parser.add_argument(
        "--reducebasis",
        action="store_true",
        help="Try to reduce the provided guess basis (via --known) using propagation\n",
    )

    # Parse command line arguments and construct parameter list.
    args = parser.parse_args()
    params = loadparameters(args)

    # Check if environment is setup correctly.
    checkenvironment()

    # Handle reducebasis action
    if params.get("_action") == "reducebasis":
        search.search_using_reducebasis(params)
        return

    # Start the solver
    startsearch(params)


if __name__ == "__main__":
    main()
