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
from core.solverresult import timed_search
from argparse import ArgumentParser, RawTextHelpFormatter
import json
import os
import sys
from config import TEMP_DIR


def _resolve_dynamic_defaults(params):
    """
    If maxguess or maxsteps were not supplied by the user, derive sensible
    defaults from the input file:
      maxguess  -> total possible guess cost of unknown variables
      maxsteps  -> number of all variables (before preprocessing)
    A lightweight parse (preprocess=0) is used so this is fast.
    """
    if params["maxguess"] is not None and params["maxsteps"] is not None:
        return
    from core.inputparser import read_relation_file

    parsed = read_relation_file(params["inputfile"], preprocess=0, D=2, log=0)
    if params["maxguess"] is None:
        weights = parsed["target_weights"] or {}
        params["maxguess"] = sum(weights.get(v, 1) for v in parsed["variables"]
                                  if v not in parsed["known_variables"])
    if params["maxsteps"] is None:
        params["maxsteps"] = len(parsed["variables"])


@timed_search
def startsearch(tool_parameters):
    """
    Starts the search tool for the given parameters
    """

    if tool_parameters.get("term_ordering", "degrevlex") != "degrevlex":
        raise ValueError(
            "Relation preprocessing only supports term_ordering='degrevlex'; "
            "requested %r" % tool_parameters["term_ordering"]
        )
    checkenvironment()
    from core.graphreport import validate_graph_options
    validate_graph_options(tool_parameters)
    _resolve_dynamic_defaults(tool_parameters)
    for name in ("maxguess", "maxsteps"):
        if not isinstance(tool_parameters[name], int) or tool_parameters[name] < 0:
            raise ValueError("%s must be a nonnegative integer" % name)

    if tool_parameters.get("findmin"):
        if tool_parameters.get("reducebasis"):
            raise ValueError("--findmin and --reducebasis cannot be combined")
        if tool_parameters["solver"] not in ("sat", "smt", "maxsat"):
            raise ValueError(
                "--findmin supports SAT, SMT and MaxSAT; use --cpoptimization 1 for CP "
                "or --milpdirection min for MILP"
            )
    if tool_parameters.get("reducebasis") or tool_parameters.get("_action") == "reducebasis":
        if any(tool_parameters.get(key) for key in ("refine_basis", "lower_bound", "seed_basis_file")) or tool_parameters.get("seed_basis") is not None:
            raise ValueError("--reducebasis cannot be combined with the paid-seed optimization options")
    if tool_parameters.get("reducebasis") or tool_parameters.get("_action") == "reducebasis":
        return search.search_using_reducebasis(tool_parameters)

    from core.optimization import has_optimization_options, search_with_options
    if has_optimization_options(tool_parameters):
        return search_with_options(tool_parameters)

    # Handle program flow
    if tool_parameters["solver"] == "milp":
        return search.search_using_milp(tool_parameters)
    elif tool_parameters["solver"] == "sat":
        return search.search_using_sat(tool_parameters)
    elif tool_parameters["solver"] == "smt":
        return search.search_using_smt(tool_parameters)
    elif tool_parameters["solver"] == "cp":
        return search.search_using_cp(tool_parameters)
    elif tool_parameters["solver"] == "groebner":
        raise ValueError(
            "Groebner search requires SageMath and is unsupported here. "
            "Use the original AutoGuess or choose sat, cp, milp, smt, mark, elim, propagate."
        )
    elif tool_parameters["solver"] == "mark":
        return search.search_using_mark(tool_parameters)
    elif tool_parameters["solver"] == "elim":
        return search.search_using_elim(tool_parameters)
    elif tool_parameters["solver"] == "propagate":
        return search.search_using_propagate(tool_parameters)
    else:
        raise ValueError("Unknown solver: %s" % tool_parameters["solver"])


def checkenvironment():
    """
    Basic checks if the environment is set up correctly
    """

    os.makedirs(TEMP_DIR, exist_ok=True)


def loadparameters(args):
    """
    Get parameters from the argument list and inputfile.
    """

    # Load default values
    params = {
        "inputfile": None,
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
        "graph_scope": "targets",
        "graph_view": "original",
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

    for key in ("graph_scope", "graph_view", "seed_basis", "seed_basis_file", "lower_bound", "refine_basis",
                "refine_time", "random_seed", "refine_trials"):
        value = getattr(args, key, None)
        if value is not None:
            params[key] = value

    # If reducebasis is requested, route to that handler
    if params["reducebasis"]:
        params["_action"] = "reducebasis"

    if not args.satsolver and (params["solver"] == "maxsat" or
                              params["solver"] == "sat" and params["timelimit"] != -1):
        params["satsolver"] = "glucose3"

    return params


def _print_result(result, requested_report):
    """Print only the result of this invocation, including solver-free modes."""
    status = result["status"]
    print("STATUS: %s" % status.upper())
    if status == "error":
        print("ERROR: %s" % result["error"], file=sys.stderr)
        return
    print("Termination: %s" % result.get("termination_reason", "unknown"))
    if result.get("timed_out"):
        if status == "sat":
            print("Time limit reached; returning the best validated basis found (optimal: false).")
        else:
            print("Time limit reached; no complete basis was found (status: unknown).")
    if "elapsed_seconds" in result:
        print("Elapsed: %.3f seconds" % result["elapsed_seconds"])
    print("Targets covered: %d / %d" % (
        len(result.get("covered_target_variables", [])),
        len(result.get("target_variables", [])),
    ))
    if result.get("cost") is not None:
        print("Guess cost: %s" % result["cost"])
        print("Guessed variables: %s" % (", ".join(result["guessed_variables"]) or "(none)"))
    if "lower_bound" in result:
        upper = result.get("upper_bound")
        if upper is None and status == "sat":
            upper = result.get("cost")
        print("Cost bounds: %s .. %s" % (result["lower_bound"],
              upper if upper is not None else "unknown"))
    if result.get("propagation_steps") is not None:
        print("Target propagation steps: %s" % result["propagation_steps"])
    print("Optimal: %s" % ("yes" if result.get("optimal") else "not established"))
    if result.get("outputfile"):
        print("Current report: %s" % result["outputfile"])
    elif os.path.exists(requested_report):
        print("No report from this run; existing %s belongs to an earlier run." % requested_report)
    for kind, path in result.get("graph_files", {}).items():
        print("Current graph (%s): %s" % (kind.upper(), path))


def main(argv=None):
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
        "-i", "--inputfile", nargs=1, required=True,
        help="Use an input file in plain text format"
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
        choices=["cp", "milp", "sat", "maxsat", "smt", "groebner", "mark", "elim", "propagate"],
        help="cp = solve the problem using CP solvers\n"
        "milp = solve the problem using the MILP solvers\n"
        "sat = solve the problem using the SAT solvers\n"
        "maxsat = minimize weighted guesses using RC2/Glucose3\n"
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
        type=float,
        help="Search budget in seconds, shared across optimization attempts (-1 = unlimited; 0 = no search time)\n",
    )
    parser.add_argument(
        "-tk",
        "--tikz",
        nargs=1,
        type=int,
        choices=[0, 1],
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
        help='Relation preprocessing supports only "degrevlex"\n',
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
    parser.add_argument("--verbose", action="store_true",
                        help="Show model-generation and solver progress in addition to the final result")
    parser.add_argument("--graph-view", choices=["original", "deduction"], default="original",
                        help="Original AutoGuess graph or deduction layers (default: original)")
    parser.add_argument("--graph-scope", choices=["targets", "full"], default="targets",
                        help="Scope for the deduction view: target dependencies or full closure (default: targets)")
    parser.add_argument(
        "--findmin",
        action="store_true",
        help="Minimize guess cost (SAT/SMT; MaxSAT always minimizes)\n",
    )
    parser.add_argument(
        "--reducebasis",
        action="store_true",
        help="Try to reduce the provided guess basis (via --known) using propagation\n",
    )
    parser.add_argument(
        "--json-output",
        metavar="FILE",
        help="Write the current-run status and validated result as JSON\n",
    )
    seeds = parser.add_mutually_exclusive_group()
    seeds.add_argument("--seed-basis", nargs="+", metavar="VAR",
                       help="Fully paid starting guesses; spaces or commas accepted")
    seeds.add_argument("--seed-basis-file", metavar="FILE",
                       help="JSON guess list or previous result containing guessed_variables")
    parser.add_argument("--lower-bound", action="store_true",
                        help="Generate and verify a formal lower-bound certificate before search")
    parser.add_argument("--refine-basis", action="store_true",
                        help="Refine the paid seed for lower cost, then fewer propagation steps")
    parser.add_argument("--refine-time", type=float,
                        help="Maximum seconds for refinement within the shared budget (default: at most 1s/20%%)")
    parser.add_argument("--random-seed", type=int, default=0,
                        help="Random seed for optional basis refinement (default: 0)")
    parser.add_argument("--refine-trials", type=int, default=1000,
                        help="Maximum refinement trials (default: 1000)")

    # Parse command line arguments and construct parameter list.
    args = parser.parse_args(argv)
    params = loadparameters(args)
    # A sidecar must never overwrite the relation system or the text report.
    if args.json_output and os.path.realpath(args.json_output) in {
        os.path.realpath(params["inputfile"]), os.path.realpath(params["outputfile"])
    }:
        parser.error("--json-output must differ from both the input file and text report")
    if os.path.realpath(params["inputfile"]) == os.path.realpath(params["outputfile"]):
        parser.error("the text report must differ from the input file")
    if args.seed_basis_file and os.path.realpath(args.seed_basis_file) in {
        os.path.realpath(params["outputfile"]),
        os.path.realpath(args.json_output) if args.json_output else None,
    }:
        parser.error("seed-basis input must differ from output paths")
    from core.graphreport import validate_graph_options
    try:
        validate_graph_options(params, additional_paths=[args.json_output])
    except ValueError as exc:
        parser.error(str(exc))

    try:
        from core.console import progress_output
        with progress_output(args.verbose):
            result = startsearch(params)
    except Exception as exc:
        # Keep failures available to automation without rereading old reports.
        result = {"status": "error", "error": str(exc), "outputfile": None,
                  "targets_covered": False, "optimal": False}
    if args.json_output:
        from core.solverresult import atomic_write
        atomic_write(args.json_output, json.dumps(result, indent=2) + "\n")
    _print_result(result, params["outputfile"])
    return result


def cli():
    """Translate current-run status to a shell exit code."""
    try:
        result = main()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    return {"sat": 0, "unsat": 1, "error": 2, "unknown": 3}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(cli())
