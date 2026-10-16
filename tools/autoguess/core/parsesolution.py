"""
Created on Aug 24, 2020

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

from core.varnames import step_var
from core.console import progress
from core.solverresult import current_result, atomic_write


def parse_solver_solution(gd):
    """
    This method parses the obtained solution (if exists), into a human readable format
    """

    for name in ("_graph_files", "_graph_summary", "_graph_warnings"):
        setattr(gd, name, None)
    gd.guessed_vars = [
        v
        for v in gd.variables
        if (gd.solutions[0][step_var(v, 0)] == 1) and (v not in gd.known_variables)
    ]
    # Check the reported basis independently of the backend's state assignment.
    # A satisfiable encoding must imply actual finite-depth target coverage.
    validated = current_result(gd, True)
    if validated["status"] != "sat":
        raise RuntimeError("Solver model does not determine targets: " + ", ".join(validated["missing_targets"]))
    gd._report_written = None
    if getattr(gd, "defer_reporting", False):
        return

    from core.originalgraph import build_original_graph
    flow_graph = build_original_graph(gd.__dict__, gd.guessed_vars,
                                     max_steps=gd.max_steps, solutions=gd.solutions)
    gd.vertices = flow_graph["original_vertices"]
    gd.edges = [tuple(edge) for edge in flow_graph["original_edges"]]
    numbers_of_guesses = sum(gd.solutions[0].values()) - len(gd.known_variables)

    if numbers_of_guesses != len(gd.guessed_vars):
        print("There exist duplicated variables among the known variables!")

    gd.final_info = sum(gd.solutions[gd.max_steps].values())

    # Build pretty guessed-variables list
    guessed_vars_pretty = []
    for v in gd.guessed_vars:
        if hasattr(gd, "dummy_mapping") and v in gd.dummy_mapping:
            guessed_vars_pretty.append(
                f"{v} (represents: {' * '.join(gd.dummy_mapping[v])})"
            )
        else:
            guessed_vars_pretty.append(v)

    progress("\n" + "=" * 60)
    progress("RESULTS")
    progress("=" * 60)
    progress(f"Number of guesses:         {numbers_of_guesses}")
    if getattr(gd, "target_weights", None):
        progress(f"Total guess weight:        {validated['cost']}")
    progress(f"Known in final state:      {gd.final_info} / {len(gd.variables)}")
    progress(f"Maximum allowed steps:     {gd.max_steps}")
    progress("-" * 60)
    progress(f"Guessed variable(s) ({len(gd.guessed_vars)}):")
    progress(f'  {", ".join(guessed_vars_pretty)}')
    progress("=" * 60)

    separator_line = "#" * 60
    output_buffer = ""

    output_buffer += "Number of relations: %d\n" % gd.num_of_relations
    output_buffer += "Number of variables: %d\n" % gd.num_of_vars
    output_buffer += "Number of target variables: %d\n" % len(gd.target_variables)
    output_buffer += "Number of known variables: %d\n" % len(gd.known_variables)
    output_buffer += "Number of guessed variables: %d\n" % len(gd.guessed_vars)
    output_buffer += "Number of state copies (max_steps): %d\n" % gd.max_steps
    if getattr(gd, "target_weights", None):
        output_buffer += "Total guess weight: %d\n" % validated["cost"]
        output_buffer += "An upper bound for guess weight (max_guess): %d\n" % gd.max_guess
    else:
        output_buffer += "An upper bound for the number of guessed variables given by user (max_guess): %d\n" % gd.max_guess
    output_buffer += (
        "%d out of %d state variables are known after %d state copies\n"
        % (gd.final_info, gd.num_of_vars, gd.max_steps)
    )
    output_buffer += separator_line
    output_buffer += f"\nThe following {len(gd.guessed_vars)} variable(s) are guessed:\n{', '.join(guessed_vars_pretty)}\n"
    output_buffer += separator_line
    output_buffer += "\nThe following %d variable(s) are initially known:\n%s\n" % (
        len(gd.known_variables),
        ", ".join(gd.known_variables),
    )
    output_buffer += separator_line
    output_buffer += "\nTarget variables:\n%s\n" % ", ".join(gd.target_variables)
    output_buffer += separator_line
    output_buffer += "\nDetermination flow:\n"

    variables_deductor_relations = {
        v: {"deductor_relations": [], "number_of_deductions": 0} for v in gd.variables
    }
    detector_relations = []
    used_symmetric_relations = []
    used_implication_relations = []
    by_source_step = {}
    for deduction in flow_graph["deductions"]:
        by_source_step.setdefault(deduction["source_step"], []).append(deduction)
    for step in range(flow_graph["metadata"]["steps_scanned"]):
        output_buffer += "\nState %d:\n" % step
        for deduction in by_source_step.get(step, ()):
            relation = deduction["relation"]
            head = deduction["head"]
            lhs = ", ".join(deduction["premises"])
            per_variable = variables_deductor_relations[head]
            per_variable["number_of_deductions"] = deduction["count"]
            if deduction["relation_kind"] == "symmetric":
                description = ", ".join(relation)
                used_symmetric_relations.append(relation)
            else:
                description = ", ".join(relation[:-1]) + " => " + relation[-1]
                used_implication_relations.append(relation)
            per_variable["deductor_relations"].append(description)
            output_buffer += "%s in %s relation [%s] are known: %s ===> %s\n" % (
                lhs, deduction["relation_kind"], description, lhs, head)
        output_buffer += separator_line

    for rel in gd.symmetric_relations:
        if rel not in used_symmetric_relations:
            detector_relations.append(", ".join(rel))

    for rel in gd.implication_relations:
        if rel not in used_implication_relations:
            detector_relations.append(", ".join(rel[0:-1]) + " => " + rel[-1])

    gd.finally_known = [
        v
        for v in gd.variables
        if gd.solutions[gd.max_steps][step_var(v, gd.max_steps)] == 1
    ]
    output_buffer += (
        "\nThe following variables are known in final state:\n%s\n"
        % ", ".join(gd.finally_known)
    )
    output_buffer += separator_line
    output_buffer += "\nThe following relations have not been used in determination (they might be used to check the correctness of guesses):\n"
    output_buffer += "\n".join(detector_relations)
    output_buffer += "\n" + separator_line
    output_buffer += "\nThe following variables can be deduced from multiple paths:\n"

    for v in gd.variables:
        if variables_deductor_relations[v]["number_of_deductions"] > 1:
            output_buffer += "\n%s can be deduced from:\n%s\n" % (
                v,
                "\n".join(variables_deductor_relations[v]["deductor_relations"]),
            )

    if hasattr(gd, "dummy_mapping") and gd.dummy_mapping:
        output_buffer += "\n" + separator_line
        output_buffer += "\nDummy variable mapping (introduced during linearization of algebraic relations):\n"
        output_buffer += "Total dummy variables: %d\n\n" % len(gd.dummy_mapping)
        for dummy_var, original_vars in sorted(gd.dummy_mapping.items()):
            output_buffer += "  %s = %s\n" % (dummy_var, " * ".join(original_vars))
        output_buffer += "\n" + separator_line

    atomic_write(gd.output_dir, output_buffer)
    gd._report_written = gd.output_dir
    from core.graphreport import attach_graph
    attach_graph(gd.__dict__, validated, dict(
        inputfile=gd.inputfile_name, outputfile=gd.output_dir, maxsteps=gd.max_steps,
        drawgraph=getattr(gd, "draw_graph", False), tikz=getattr(gd, "tikz", 0),
        dglayout=getattr(gd, "dglayout", "dot"),
        graph_scope=getattr(gd, "graph_scope", "targets"),
        graph_view=getattr(gd, "graph_view", "original")),
        solutions=gd.solutions, original_graph=flow_graph)
    for key in ("graph_files", "graph_summary", "graph_warnings"):
        setattr(gd, "_" + key, validated.get(key))
