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

"""Render original AutoGuess graphs and optional deduction views.

Variable identities, visible labels and Graphviz identifiers are separate.  A
variable-only original graph retains every parser edge count. The optional
deduction view uses AND junctions for multiple required premises and direct
arrows for single-input deductions. PDF, SVG and optional TikZ share a DOT graph.
"""

from pathlib import Path
from html import escape as html_escape
import os
import tempfile

from graphviz import Digraph, escape


PALETTE = {
    "known_fill": "#83B6D9", "known_border": "#285A7D",
    "guessed_fill": "#78BF86", "guessed_border": "#155B2E",
    "derived_fill": "#CCD2D8", "derived_border": "#606970",
    "target_fill": "#E67B73", "target_border": "#9C2925",
    "junction_fill": "#F2F2F2", "junction_border": "#62686D",
}

_ROLE_STYLE = {
    "known": dict(shape="box", fillcolor=PALETTE["known_fill"], color=PALETTE["known_border"]),
    "guessed": dict(shape="hexagon", fillcolor=PALETTE["guessed_fill"], color=PALETTE["guessed_border"]),
    "derived": dict(shape="ellipse", fillcolor=PALETTE["derived_fill"], color=PALETTE["derived_border"]),
}


def variable_style(node):
    """Shared variable palette: targets are red, paid guesses stay identifiable."""
    role = node.get("kind", "derived")
    if role not in _ROLE_STYLE:
        raise ValueError("Unknown deduction graph node kind: %s" % role)
    attrs = dict(_ROLE_STYLE[role])
    if node.get("target"):
        # Target fill takes precedence over the role colour. A paid target keeps
        # its green single border and hexagon, plus the explicit guess label.
        attrs.update(fillcolor=PALETTE["target_fill"], penwidth="1.8")
        if role != "guessed":
            attrs["color"] = PALETTE["target_border"]
    return attrs


def _short(text, limit=72):
    text = str(text).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _tex_label(text):
    """Escape text, rather than treating user variable names as TeX code."""
    mapping = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%",
               "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{",
               "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    lines = ["".join(mapping.get(char, char) for char in line)
             for line in str(text).split("\n")]
    return lines[0] if len(lines) == 1 else r"\shortstack{" + r" \\ ".join(lines) + "}"


def _labels(text):
    # Graphviz's escape also prevents strings beginning with '<' from being
    # interpreted as HTML. texlbl is intentionally not backslash-escaped:
    # dot2tex consumes the safe TeX label directly.
    return dict(label=escape(str(text)), texlbl=_tex_label(text))


def _summary(metadata):
    parts = []
    if metadata.get("cost") is not None:
        parts.append("Paid guess cost: %s" % metadata["cost"])
    if metadata.get("guessed_count") is not None:
        parts.append("Guesses: %s" % metadata["guessed_count"])
    if metadata.get("target_count") is not None:
        parts.append("Targets: %s" % metadata["target_count"])
    if metadata.get("propagation_steps") is not None:
        parts.append("Propagation steps: %s" % metadata["propagation_steps"])
    if metadata.get("max_steps") is not None:
        parts.append("Allowed steps: %s" % metadata["max_steps"])
    scope = metadata.get("scope")
    if scope:
        parts.append("View: %s" % ("target explanations" if scope == "targets" else "full deduction trace"))
    lines, line = [], ""
    for part in parts:
        candidate = (line + " | " + part) if line else part
        if line and len(candidate) > 64:
            lines.append(line)
            line = part
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def _build_graph(graph, dglayout="dot"):
    """Build deterministic DOT; only opaque IDs reach Graphviz or TikZ."""
    nodes = sorted(graph.get("nodes", []), key=lambda node: (int(node.get("step", 0)), str(node["id"])))
    deductions = sorted(graph.get("deductions", []),
                        key=lambda rule: (int(rule.get("step", 0)), str(rule["head"]), str(rule["id"])))
    identities = {node["id"]: "v%s" % index for index, node in enumerate(nodes)}
    if len(identities) != len(nodes):
        raise ValueError("Deduction graph contains duplicate variable identities")
    rule_ids = {rule["id"]: "r%s" % index for index, rule in enumerate(deductions)}
    if len(rule_ids) != len(deductions):
        raise ValueError("Deduction graph contains duplicate deduction identities")
    title = "AutoGuess deduction graph"
    summary = _summary(graph.get("metadata", {}))
    if summary:
        title += "\n" + summary
    if dglayout != "dot":
        title += "\nLayout: %s (steps are shown in labels)" % dglayout
    dot = Digraph(name="AutoGuess", engine=dglayout,
                  graph_attr=dict(rankdir="TB", ranksep="0.55", nodesep="0.28", overlap="false",
                                  bgcolor="white", fontname="Helvetica", fontsize="12", labelloc="t",
                                  labeljust="l", label=escape(title)),
                  node_attr=dict(fontname="Helvetica", fontsize="10", margin="0.10,0.06",
                                 style="filled", penwidth="1.3"),
                  edge_attr=dict(color="#59636B", arrowsize="0.65", penwidth="1.1"))
    ranks = {}
    for node in nodes:
        step = int(node.get("step", 0))
        role = node.get("kind", "derived")
        attrs = variable_style(node)
        name = identities[node["id"]]
        label = "%s\nstep %s" % (_short(node.get("label") or node.get("expression") or node["id"]), step)
        if role == "guessed":
            label += " | guess cost %s" % node.get("weight", 1)
        if node.get("target"):
            label += " | target"
        tooltip = ["Variable: %s" % node["id"], "Role: %s" % role, "Deduction step: %s" % step]
        if node.get("expression"):
            tooltip.append("Expression: %s" % node["expression"])
        if role == "guessed":
            tooltip.append("Paid guess cost: %s" % node.get("weight", 1))
        if node.get("target"):
            tooltip.append("Target")
        attrs.update(**_labels(label), tooltip=escape("\n".join(tooltip)))
        dot.node(name, **attrs)
        ranks.setdefault(2 * step, []).append(name)
    for rule in deductions:
        head = rule["head"]
        premises = sorted(set(rule.get("premises", [])), key=str)
        if head not in identities or any(premise not in identities for premise in premises):
            raise ValueError("Deduction graph rule references a missing variable")
        name = rule_ids[rule["id"]]
        step = int(rule.get("step", 0))
        explanation = "%s => %s" % (", ".join(map(str, premises)) or "(no premises)", head)
        relation = rule.get("relation")
        tooltip = "Deduction step: %s\n%s" % (step, explanation)
        if relation:
            tooltip += "\nRelation (%s): %s" % (rule.get("relation_kind", "inference"),
                                                  ", ".join(map(str, relation)))
        if len(premises) == 1:
            dot.edge(identities[premises[0]], identities[head], tooltip=escape(tooltip))
            continue
        rule_label = "AND" if premises else "given"
        dot.node(name, shape="diamond", fillcolor=PALETTE["junction_fill"], color=PALETTE["junction_border"], fontsize="8",
                 width="0.40", height="0.24", margin="0.035", tooltip=escape(tooltip),
                 **_labels(rule_label))
        for premise in premises:
            dot.edge(identities[premise], name, arrowhead="none")
        dot.edge(name, identities[head])
        ranks.setdefault(max(0, 2 * step - 1), []).append(name)
    # Invisible anchors enforce alternate variable/rule layers without adding
    # artificial dependencies between variables. Other engines may ignore ranks.
    previous = None
    for rank, members in sorted(ranks.items()):
        anchor = "layer%s" % rank
        with dot.subgraph(name="rank%s" % rank) as layer:
            # Suppress inherited title/background while dot2tex flattens the
            # rank subgraphs; otherwise it redraws the title once per layer.
            layer.attr(rank="same", label="", bgcolor="transparent")
            layer.node(anchor, shape="point", width="0", height="0", style="invis", label="")
            for member in members:
                layer.node(member)
        if previous is not None:
            dot.edge(previous, anchor, style="invis", weight="100", arrowhead="none")
        previous = anchor
    legend = ("Legend: known = blue box | paid guess = green hexagon\n"
              "Derived = grey ellipse | Red fill = target\n"
              "Guessed targets keep their green border\n"
              "AND: every incoming premise is required\n"
              "Step = deduction propagation, not cipher rounds")
    dot.node("legend", shape="box", style="filled", fillcolor="#FAFAFA", color="#C6CBD0",
             fontsize="9", **_labels(legend))
    if ranks:
        # Centre the legend under the visible last layer, rather than under an
        # invisible rank anchor that dot may place to one side of the drawing.
        for member in ranks[max(ranks)]:
            dot.edge(member, "legend", style="invis", weight="1", arrowhead="none")
    return dot


def _original_caption(metadata):
    """An obvious coloured key without adding graph vertices or edges."""
    metadata = dict(metadata)
    metadata.pop("scope", None)
    summary = _summary(metadata).splitlines()
    entries = [("Known", "known_fill", "known_border"),
               ("Guesses", "guessed_fill", "guessed_border"),
               ("Derived", "derived_fill", "derived_border"),
               ("Targets", "target_fill", "target_border"),
               ("Guessed targets", "target_fill", "guessed_border")]

    def html_cell(entry, columns=1):
        text, fill, border = entry
        return ('<TD COLSPAN="%s" BORDER="2" COLOR="%s" BGCOLOR="%s" CELLPADDING="5">'
                '<FONT COLOR="#111111" POINT-SIZE="12">%s</FONT></TD>'
                % (columns, PALETTE[border], PALETTE[fill], html_escape(text)))

    panel = ('<TABLE BORDER="1" COLOR="#606970" CELLBORDER="0" CELLSPACING="4" CELLPADDING="3">'
             '<TR><TD COLSPAN="3"><FONT POINT-SIZE="13"><B>LEGEND</B></FONT></TD></TR>'
             '<TR>' + ''.join(html_cell(entry) for entry in entries[:3]) + '</TR>'
             '<TR>' + html_cell(entries[3]) + html_cell(entries[4], 2) + '</TR></TABLE>')
    notes = ["Guessed targets: red fill with a green single border",
             "Dashed = second or later deduction occurrence",
             "Inputs from the same relation remain jointly required"]
    rows = ['<TR><TD><FONT POINT-SIZE="14"><B>Original AutoGuess graph</B></FONT></TD></TR>']
    rows.extend('<TR><TD>%s</TD></TR>' % html_escape(line) for line in summary)
    rows.append('<TR><TD CELLPADDING="7">%s</TD></TR>' % panel)
    rows.extend('<TR><TD>%s</TD></TR>' % html_escape(line) for line in notes)
    label = '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2">' + ''.join(rows) + '</TABLE>>'

    def tex_cell(entry):
        text, fill, border = entry
        return (r"\fcolorbox[HTML]{%s}[HTML]{%s}{\strut\color{black} %s}"
                % (PALETTE[border].lstrip("#"), PALETTE[fill].lstrip("#"), _tex_label(text)))

    tex_panel = (r"\fbox{\shortstack{\textbf{LEGEND} \\ "
                 + r"\quad ".join(tex_cell(entry) for entry in entries[:3]) + r" \\ "
                 + r"\quad ".join(tex_cell(entry) for entry in entries[3:]) + "}}")
    tex_lines = [r"\textbf{Original AutoGuess graph}"] + [_tex_label(line) for line in summary]
    tex_lines += [tex_panel] + [_tex_label(line) for line in notes]
    return dict(label=label, texlbl=r"\shortstack{" + r" \\ ".join(tex_lines) + "}")


def _build_original_graph(graph, dglayout="dot"):
    """Render the original variable-to-variable graph and edge count styling.

    Exact repeated edge triples are deduplicated as in the upstream renderer.
    Different occurrence counts remain separate edges, including solid/dashed
    variants between the same two variables. There is no witness pruning or
    imposed deduction-step ranking in this view.
    """
    nodes = sorted(graph.get("nodes", []), key=lambda node: str(node["id"]))
    identities = {node["id"]: "v%s" % index for index, node in enumerate(nodes)}
    if len(identities) != len(nodes):
        raise ValueError("Original graph contains duplicate variable identities")
    edges = set()
    for edge in graph.get("original_edges", []):
        if len(edge) != 3:
            raise ValueError("Original graph edges require source, head and deduction count")
        tail, head, count = edge
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Original graph deduction count must be a nonnegative integer")
        if tail not in identities or head not in identities:
            raise ValueError("Original graph edge references a missing variable")
        edges.add((tail, head, count))
    dot = Digraph(name="DataFlow", engine=dglayout,
                  graph_attr=dict(rankdir="TB", ranksep="0.75 equally", overlap="scale", ratio="compress",
                                  bgcolor="white", fontname="Helvetica", fontsize="11", labelloc="t",
                                  **_original_caption(graph.get("metadata", {}))),
                  node_attr=dict(shape="circle", fontname="Helvetica", fontsize="10", style="filled",
                                 margin="0.06", penwidth="1.3"),
                  edge_attr=dict(color="#59636B", arrowsize="0.65", penwidth="1.1"))
    for node in nodes:
        role = node.get("kind", "derived")
        attrs = variable_style(node)
        attrs["shape"] = "circle"
        tooltip = ["Variable: %s" % node["id"], "Role: %s" % role]
        if node.get("step") is not None:
            tooltip.append("Earliest propagation step: %s" % node["step"])
        if node.get("expression"):
            tooltip.append("Expression: %s" % node["expression"])
        if role == "guessed":
            tooltip.append("Paid guess cost: %s" % node.get("weight", 1))
        if node.get("target"):
            tooltip.append("Target")
        attrs.update(**_labels(_short(node["id"])), tooltip=escape("\n".join(tooltip)))
        dot.node(identities[node["id"]], **attrs)
    for tail, head, count in sorted(edges, key=lambda edge: (str(edge[0]), str(edge[1]), edge[2])):
        dot.edge(identities[tail], identities[head], style="dashed" if count >= 2 else "solid",
                 tooltip=escape("%s -> %s\nOriginal deduction occurrence for %s: %s" %
                                (tail, head, head, count)))
    return dot


def _atomic_bytes(path, data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(path.parent), prefix=".%s." % path.name,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def draw_deduction_graph(graph, output_dir, tikz=0, dglayout="dot"):
    """Save DOT, PDF and SVG, plus optional TeX, returning current artifacts.

    Missing rendering tools cannot invalidate a solved result: DOT remains
    available and warnings explain any omitted format.  An older artifact is
    never returned as if it had been generated by this call.
    """
    if graph.get("metadata", {}).get("view") == "original":
        dot = _build_original_graph(graph, dglayout=dglayout)
    else:
        dot = _build_graph(graph, dglayout=dglayout)
    return _render_graph(dot, output_dir, tikz=tikz)


def _tikz_document(dot):
    """Keep native positions while drawing multiline captions exactly once.

    dot2tex 2.11.3 applies a graph's whole texlbl to *each* text line in its
    Graphviz drawing operations. Its parser also inherits those operations into
    layout subgraphs, repeating the caption yet again. Our subgraphs only arrange
    ranks; draw the graph caption once at Graphviz's label position and leave
    node labels and every edge to the ordinary TikZ converter.
    """
    from dot2tex.dot2tex import Dot2TikZConv

    caption = dot.graph_attr.get("texlbl")
    if caption is None:
        # Our labels use graphviz.escape, which doubles literal backslashes.
        caption = _tex_label(str(dot.graph_attr.get("label", "")).replace("\\\\", "\\"))
    font_size = float(dot.graph_attr.get("fontsize", 12))

    class CaptionTikZConverter(Dot2TikZConv):
        def do_graph(self):
            if self.graph is not self.main_graph or not caption:
                return
            position = self.main_graph.attr.get("lp")
            if not position:
                return
            x, y = map(float, position.split(","))
            self.body += (r"\node[font=\fontsize{%g}{%g}\selectfont] at (%gbp,%gbp) {%s};" "\n"
                          % (font_size, font_size * 1.2, x, y, caption))

    # Native XDOT also makes a missing executable an ordinary, catchable error;
    # dot2tex's own executable lookup can otherwise exit the whole application.
    xdot = dot.pipe(format="xdot").decode("utf-8")
    converter = CaptionTikZConverter(dict(format="tikz", prog=dot.engine,
                                          texmode="verbatim", crop=False))
    return converter.convert(xdot)


def _render_graph(dot, output_dir, tikz=0):
    """Export one DOT graph consistently for all supported views."""
    base = str(output_dir) + "_graph"
    result = {"warnings": []}
    failures = {}
    gv_path = base + ".gv"
    _atomic_bytes(gv_path, dot.source.encode("utf-8"))
    result["gv"] = gv_path
    for file_format in ("pdf", "svg"):
        try:
            data = dot.pipe(format=file_format)
            if not data:
                raise RuntimeError("Graphviz returned an empty %s document" % file_format)
            path = base + "." + file_format
            _atomic_bytes(path, data)
            result[file_format] = path
        except Exception as exc:
            message = "Could not render graph %s (%s). DOT source: %s" % (file_format.upper(), exc, gv_path)
            result["warnings"].append(message)
            failures.setdefault(str(exc), []).append(file_format.upper())
    if tikz:
        try:
            # PDF/SVG users do not need dot2tex installed or importable. Avoid
            # autosize/crop: basic TikZ export does not require a TeX executable.
            tex = _tikz_document(dot)
            if not isinstance(tex, str) or not tex.strip():
                raise RuntimeError("dot2tex returned an empty TeX document")
            path = base + ".tex"
            _atomic_bytes(path, tex.encode("utf-8"))
            result["tex"] = path
        except Exception as exc:
            message = "Could not export graph TikZ (%s). DOT source: %s" % (exc, gv_path)
            result["warnings"].append(message)
            failures.setdefault(str(exc), []).append("TikZ")
    for cause, formats in failures.items():
        print("WARNING: Could not export graph %s (%s). DOT source: %s" %
              (", ".join(formats), cause, gv_path))
    return result


def draw_graph(vertices, edges, known_variables, guessed_vars, output_dir, tikz=0, dglayout="dot"):
    """Compatibility adapter for callers with legacy pairwise dependencies.

    Keep the upstream edge triples, including the count that selects dashed
    styling. The optional deduction view represents complete premise sets.
    """
    known, guessed = set(known_variables), set(guessed_vars)
    triples = {tuple(edge) if len(edge) == 3 else (edge[0], edge[1], 1) for edge in edges}
    variables = set(vertices)
    for tail, head, _count in triples:
        variables.update((tail, head))
    if not variables:
        # The original parser emits no vertices when recovery needs zero steps.
        # Keep that useful initial-state fix without adding unrelated initial
        # variables to ordinary legacy graphs.
        variables.update(known | guessed)
    nodes = [dict(id=variable, label=str(variable), kind="known" if variable in known else
                  "guessed" if variable in guessed else "derived",
                  step=0 if variable in known | guessed else None, target=False, weight=1)
             for variable in sorted(variables, key=str)]
    graph = dict(nodes=nodes, deductions=[],
                 original_edges=[list(edge) for edge in sorted(triples, key=lambda edge: (str(edge[0]), str(edge[1]), edge[2]))],
                 metadata=dict(view="original", guessed_count=len(guessed)))
    return draw_deduction_graph(graph, output_dir, tikz=tikz, dglayout=dglayout)
