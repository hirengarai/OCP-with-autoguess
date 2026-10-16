"""Attach current graph artifacts to independently validated search results."""

import os


def validate_graph_options(parameters, additional_paths=()):
    """Keep rendering choices explicit and graph exports clear of input files."""
    if parameters.get("graph_scope", "targets") not in ("targets", "full"):
        raise ValueError("graph_scope must be 'targets' or 'full'")
    if parameters.get("graph_view", "original") not in ("original", "deduction"):
        raise ValueError("graph_view must be 'original' or 'deduction'")
    if not parameters.get("drawgraph", True):
        return
    if parameters.get("tikz", 0) not in (0, 1):
        raise ValueError("tikz must be 0 or 1")
    layouts = ("dot", "circo", "twopi", "fdp", "neato", "osage", "patchwork", "sfdp")
    if parameters.get("dglayout", "dot") not in layouts:
        raise ValueError("Unsupported graph layout; choose one of: " + ", ".join(layouts))
    output = os.fspath(parameters.get("outputfile", "output"))
    suffixes = [".gv", ".pdf", ".svg"]
    if parameters.get("tikz", 0):
        suffixes.append(".tex")
    exports = {os.path.realpath(output + "_graph" + suffix) for suffix in suffixes}
    protected = [parameters.get("inputfile"), parameters.get("seed_basis_file"),
                 parameters.get("outputfile"), *additional_paths]
    if any(path is not None and os.path.realpath(path) in exports for path in protected):
        raise ValueError("Graph output paths must differ from input, seed, report and JSON paths")


def attach_graph(data, result, parameters, *, solutions=None, original_graph=None):
    """Render a checked basis, preserving the original graph by default.

    Native parser calls supply their original state assignments. Workflows
    without such assignments reconstruct states from independently validated
    closure before applying the same original deduction-selection algorithm.
    The optional deduction view always uses earliest closure witnesses.
    """
    validate_graph_options(parameters)
    if result.get("status") != "sat" or not parameters.get("drawgraph", True):
        return result
    from core.deductiongraph import build_deduction_graph
    from core.graphdrawer import draw_deduction_graph

    view = parameters.get("graph_view", "original")
    if view == "original":
        graph = original_graph
        if graph is None:
            from core.originalgraph import build_original_graph
            graph = build_original_graph(data, result["guessed_variables"],
                max_steps=parameters.get("maxsteps"), solutions=solutions)
    else:
        graph = build_deduction_graph(data, result["guessed_variables"],
            max_steps=parameters.get("maxsteps"),
            focus_targets=parameters.get("graph_scope", "targets") == "targets")
    graph["metadata"]["view"] = view
    exports = draw_deduction_graph(graph, parameters.get("outputfile", "output"),
        tikz=parameters.get("tikz", 0), dglayout=parameters.get("dglayout", "dot"))
    result["graph_files"] = {key: exports[key] for key in ("gv", "pdf", "svg", "tex")
                             if exports.get(key)}
    result["graph_summary"] = graph["metadata"]
    if exports.get("warnings"):
        result["graph_warnings"] = list(exports["warnings"])
    return result
