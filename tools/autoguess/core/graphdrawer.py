'''
Created on Aug 24, 2020

@author: Hosein Hadipour
@contact: hsn.hadipour@gmail.com
'''

from random import random
from graphviz import Digraph
import dot2tex
import os

def draw_graph(vertices, edges, known_variables, guessed_vars, output_dir, tikz, dglayout):
    """
    Using the Graphviz package this function constructs a
    directed graph representing the determination flow

    Parameters:
    ----------
    vertices : list
        List of vertices (variables) in the graph
    edges : list of tuples
        List of edges (dependencies) as (source, target, weight)
    known_variables : list
        Variables that are known (blue nodes)
    guessed_vars : list
        Variables that are guessed (red nodes)
    output_dir : str
        Base path for output files (without extension)
    tikz : int
        If 1, generate TikZ LaTeX code in addition to PDF
    dglayout : str
        Graphviz layout engine: 'dot', 'neato', 'fdp', 'sfdp', 'circo', 'twopi'
    """

    vertices = list(set(vertices))
    edges = list(set(edges))

    # Create the main directed graph for PDF output
    directed_graph = Digraph(name='DataFlow', node_attr={'shape': 'circle'})
    directed_graph.graph_attr.update({
        "layout": dglayout,
        "ranksep": '0.75 equally',
        "rankdir": 'TB',
        "overlap": 'scale',
        "orientation": '[lL]*',
        "pagedir": 'BL',
        "ratio": 'compress'
    })

    # Create a separate graph for TikZ/LaTeX output
    digraph_tikz = Digraph(name='DataFlowTikz', node_attr={'shape': 'circle'}, graph_attr={
        'layout': 'dot',
        'overlap': 'scale',
        'orientation': '[lL]*]',
        'rankdir': 'TB'
    })

    # Add edges
    for edge in edges:
        # Dashed style for edges that appear multiple times (weight >= 2)
        style = 'dashed' if edge[2] >= 2 else None
        directed_graph.edge(edge[0], edge[1], style=style)

        # Format node names for TikZ (LaTeX math mode)
        node1_name = "{%s_{%s}}" % (edge[0].split("_")[0], ",".join(edge[0].split("_")[1:])) if "_" in edge[0] else edge[0]
        node2_name = "{%s_{%s}}" % (edge[1].split("_")[0], ",".join(edge[1].split("_")[1:])) if "_" in edge[1] else edge[1]

        # Only add non-duplicate edges to TikZ graph
        if edge[2] < 2:
            digraph_tikz.edge(node1_name, node2_name)

    # Add vertices with appropriate styling
    for vertex in vertices:
        # Format vertex name for TikZ
        vertex_name = "{%s_{%s}}" % (vertex.split("_")[0], ",".join(vertex.split("_")[1:])) if "_" in vertex else vertex

        # Color coding:
        # Blue = known variables
        # Red = guessed variables
        # Green = determined variables
        if vertex in known_variables:
            color, shape = "blue", "doublecircle"
        elif vertex in guessed_vars:
            color, shape = "red", "doublecircle"
        else:
            color, shape = "green", "circle"

        directed_graph.node(vertex, color=color, style="filled", shape=shape)
        digraph_tikz.node(vertex_name, color=color, style="filled", shape=shape, texmode="math")

    # Render the graph to PDF
    graph_file_name = output_dir + "_graph"
    directed_graph.render(graph_file_name, cleanup=True)

    # Generate TikZ/LaTeX code if requested
    if tikz == 1:
        print("Generating TikZ LaTeX code ...")
        try:
            texcode = dot2tex.dot2tex(digraph_tikz.source, format='tikz', crop=True)
            with open(os.path.join(graph_file_name + ".tex"), "w") as tikzfile:
                tikzfile.write(texcode)
            print(f"TikZ code written to: {graph_file_name}.tex")
        except Exception as e:
            print(f"Warning: Failed to generate TikZ code: {e}")
