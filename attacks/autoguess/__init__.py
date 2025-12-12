# attacks/autoguess/__init__.py

from .emitter import genAutoGuessRelations, genAutoGuessRelationsForFunction


def solve(
    inputfile,
    solver="cp",
    maxguess=50,
    maxsteps=5,
    timelimit=-1,
    outputfile="output",
    # MILP options
    milpdirection="min",
    # Solver-specific
    cpsolver="or-tools",
    satsolver="cadical153",
    smtsolver="z3",
    cpoptimization=1,
    # Output options
    tikz=0,
    dglayout="dot",
    log=0,
    # Preprocessing
    preprocess=0,
    D=2,
    term_ordering="degrevlex",
    overlapping_number=2,
    cnf_to_anf_conversion="simple",
):
    """
    Solve the guess-and-determine problem.
    
    Parameters
    ----------
    inputfile : str
        Path to the relations file.
    solver : str
        One of: 'cp', 'milp', 'sat', 'smt'
    maxguess : int
        Upper bound for number of guessed variables.
    maxsteps : int
        Depth of search.
    timelimit : int
        Time limit in seconds (-1 for no limit).
    milpdirection : str
        'min' or 'max'
    cpsolver : str
        CP solver: 'or-tools', 'gecode', 'chuffed', etc.
    satsolver : str
        SAT solver: 'cadical153', 'glucose3', etc.
    smtsolver : str
        SMT solver: 'z3', 'cvc4', 'yices', etc.
    cpoptimization : int
        1 = find minimal guess basis, 0 = check if basis exists
    tikz : int
        1 = generate tikz code for determination flow graph
    dglayout : str
        Graph layout: 'dot', 'circo', 'fdp', etc.
    log : int
        1 = save intermediate files to temp folder
    preprocess : int
        1 = enable preprocessing phase
    D : int
        Degree of Macaulay matrix in preprocessing
    term_ordering : str
        'degrevlex' or 'deglex'
    overlapping_number : int
        For block-wise CNF to ANF conversion
    cnf_to_anf_conversion : str
        'simple' or 'blockwise'
    """
    from .autoguess import startsearch, checkenvironment
    
    params = {
        "inputfile": inputfile,
        "outputfile": outputfile,
        "maxguess": maxguess,
        "maxsteps": maxsteps,
        "solver": solver,
        "timelimit": timelimit,
        "milpdirection": milpdirection,
        "cpsolver": cpsolver,
        "satsolver": satsolver,
        "smtsolver": smtsolver,
        "cpoptimization": cpoptimization,
        "tikz": tikz,
        "preprocess": preprocess,
        "D": D,
        "term_ordering": term_ordering,
        "overlapping_number": overlapping_number,
        "cnf_to_anf_conversion": cnf_to_anf_conversion,
        "dglayout": dglayout,
        "log": log,
    }
    
    checkenvironment()
    startsearch(params)