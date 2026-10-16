"""
Created on Feb 6, 2021

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
import re
import sys
import string
import random
from collections import namedtuple
import subprocess
from core.console import progress
from config import TEMP_DIR
import pathlib
import time


def ordered_set(seq):
    """
    This function eliminates duplicated elements in a given list,
    and keeping the order of appearance unchanged,
    returns a list in which each elements appears only once
    """

    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]


def read_relation_file(path, preprocess=1, D=2, log=0, extra_known=None):
    """
    Reads a relation file in GD format and parses it into a systems of connection relations
    """

    if preprocess not in (0, 1):
        raise ValueError("preprocess must be 0 or 1")
    rnd_string_tmp = "%030x" % random.randrange(16**30)
    contents = None
    try:
        if os.path.isfile(path):
            with open(path, "r") as fileobj:
                contents = fileobj.read()
    except (TypeError, ValueError):
        progress(f"File at {path} could not be read or is empty.")

    if contents is None:
        raise ValueError(f"File at {path} could not be read or is empty.")
    contents = contents.strip()
    problem_name = find_problem_name(contents)
    sections = split_contents_by_sections(remove_comments(contents))

    dummy_mapping = {}
    connection_relations = sections.get("connection relations", "")
    reserved_variables = set(parse_connection_relations(connection_relations)[2])
    for role in ("known", "target", "not guessed", "weights"):
        reserved_variables.update(line.split()[0] for line in sections.get(role, "").splitlines() if line.strip())
    algebraic_relations = sections.get("algebraic relations", "")
    algebraic_equations_file = os.path.join(
        TEMP_DIR, "algebraic_equations_%s.txt" % rnd_string_tmp
    )
    if algebraic_relations != "" and preprocess == 1:
        with open(algebraic_equations_file, "w") as equations_file:
            equations_file.write(algebraic_relations)
        starting_time = time.time()
        progress("-" * 60)
        progress("PREPROCESSING (Macaulay matrix)")
        progress("-" * 60)
        macaulay_basis_file = os.path.join(
            TEMP_DIR, "macaulay_basis_%s.txt" % rnd_string_tmp
        )
        _macaulay_path = str(pathlib.Path(__file__).parent / "macaulay.py")
        completed = subprocess.run(
            [
                sys.executable,
                _macaulay_path,
                "-i",
                algebraic_equations_file,
                "-o",
                macaulay_basis_file,
                "-t",
                "degrevlex",
                "-D",
                str(D),
            ],
            check=True, stdout=subprocess.PIPE, text=True,
        )
        if completed.stdout:
            progress(completed.stdout, end="")
        elapsed_time = time.time() - starting_time
        progress("Preprocessing finished in %0.4f seconds" % elapsed_time)
        try:
            with open(macaulay_basis_file, "r") as groebner_basis_file:
                groebner_basis = groebner_basis_file.read()
        except IOError:
            raise RuntimeError(macaulay_basis_file + " is not accessible!")
        algebraic_relations += "\n" + groebner_basis
        # algebraic_relations = groebner_basis
        if connection_relations == "":
            connection_relations, dummy_mapping = (
                algebraic_relations_to_connection_relations(
                    algebraic_relations.split("\n"), reserved_variables=reserved_variables
                )
            )
        else:
            cr, dummy_mapping = algebraic_relations_to_connection_relations(
                algebraic_relations.split("\n"), reserved_variables=reserved_variables
            )
            connection_relations += "\n" + cr
    elif algebraic_relations != "" and preprocess == 0:
        if connection_relations == "":
            connection_relations, dummy_mapping = (
                algebraic_relations_to_connection_relations(
                    algebraic_relations.split("\n"), reserved_variables=reserved_variables
                )
            )
        else:
            cr, dummy_mapping = algebraic_relations_to_connection_relations(
                algebraic_relations.split("\n"), reserved_variables=reserved_variables
            )
            connection_relations += "\n" + cr
    symmetric_relations, implication_relations, variables = parse_connection_relations(
        connection_relations
    )
    known_variables = [v.strip() for v in sections.get("known", "").splitlines() if v.strip()]
    known_variables.extend([rel[0] for rel in symmetric_relations if len(rel) == 1])
    known_variables = ordered_set(known_variables)
    if extra_known:
        for v in extra_known:
            if v not in known_variables:
                known_variables.append(v)
    symmetric_relations = [rel for rel in symmetric_relations if len(rel) != 1]
    target_variables = [v.strip() for v in sections.get("target", "").splitlines() if v.strip()]
    target_variables = ordered_set(target_variables or variables)
    weights_section = sections.get("weights", [])
    target_weights = None
    if weights_section != []:
        target_weights = dict()
        weights_section = weights_section.split("\n")
        for element in weights_section:
            if not element.strip():
                continue
            var, weight = element.split()
            target_weights[var] = int(weight)
            if target_weights[var] < 0:
                raise ValueError("Guess weights must be nonnegative")
    notguessed_variables = [v.strip() for v in sections.get("not guessed", "").splitlines() if v.strip()]
    universe = set(variables)
    for role, names in (("known", known_variables), ("target", target_variables),
                        ("not guessed", notguessed_variables), ("weights", target_weights or {})):
        missing = sorted(set(names) - universe)
        if missing:
            raise ValueError("Variables in %s are absent from relations: %s" % (role, ", ".join(missing)))
    # Being known is compatible with being forbidden as a guess. State zero
    # represents both kinds of knowledge, so only unknown variables get a zero.
    notguessed_variables = [v for v in ordered_set(notguessed_variables) if v not in known_variables]
    parsed_data = {
        "problem_name": problem_name,
        "variables": variables,
        "known_variables": known_variables,
        "target_variables": target_variables,
        "target_weights": target_weights,
        "notguessed_variables": notguessed_variables,
        "symmetric_relations": symmetric_relations,
        "implication_relations": implication_relations,
        "dummy_mapping": dummy_mapping,
    }
    if log == 0 and algebraic_relations != "" and preprocess == 1:
        os.remove(algebraic_equations_file)
        os.remove(macaulay_basis_file)
    elif log != 0 and algebraic_relations != "" and preprocess == 1:
        implication_relations_file = os.path.join(
            TEMP_DIR, f"extended_relations{rnd_string_tmp}.txt"
        )
        with open(implication_relations_file, "w") as file:
            file.write("--" * 20 + "\n")
            file.write("implication relations: \n")
            for relation in implication_relations:
                file.write(", ".join(relation[:-1]) + "=>" + relation[-1] + "\n")
            file.write("--" * 20 + "\n")
            file.write("symmetric relations: \n")
            for relation in symmetric_relations:
                file.write(",".join(relation) + "\n")
            file.write("--" * 20 + "\n")
            file.write("variables:\n")
            file.write("\n".join(variables) + "\n")
            file.write("--" * 20 + "\n")
            file.write("known variables:\n")
            file.write("\n".join(known_variables) + "\n")
            file.write("--" * 20 + "\n")
            file.write("target variables:\n")
            file.write("\n".join(target_variables) + "\n")
            if target_weights is not None:
                file.write("target weights:\n")
                for var, weight in target_weights.items():
                    file.write(f"{var} {weight}\n")
    return parsed_data


def find_problem_name(contents):
    """
    Find the name of the problem by reading the first comments if it exists.
    If no comments are found 'gdproblem' is used by default.
    """

    pattern = re.compile(r"(?<=#).*?\n", re.DOTALL)
    match = pattern.search(contents)
    if match:
        return match.group().strip()
    return "gdproblem"


def split_contents_by_sections(contents):
    """
    Split a relation file into multiple sections

    It searches for the following keywords and split the contents by section
    'connection relations', 'algebraic relations', 'known', 'target', 'not guessed'

    Raises ValueError when the given contents is not in a valid GD format
    """

    keywords = {
        "connection relations": ("connection relation", "connection relations"),
        "algebraic relations": ("algebraic relation", "algebraic relations"),
        "known": ("known variables", "known"),
        "target": ("target variables", "target"),
        "not guessed": ("not guessed",),
        "weights": (
            "weights",
            "weight",
        ),
        "end": ("end",),
    }
    sections = []
    Section = namedtuple("Section", ("name", "keyword_start", "keyword_end"))

    for section_name, keywords in keywords.items():
        try:
            match, keyword_start, keyword_end = search_keywords(contents, keywords)
            sections.append(Section(section_name.lower(), keyword_start, keyword_end))
        except AttributeError:
            pass
    # sort by the start index of the section
    sections.sort(key=lambda x: x.keyword_start)

    if not sections or sections[-1].name != "end":
        raise ValueError('File must end with an "end" keyword')

    parsed_sections = {}

    for i in range(len(sections) - 1):
        section = sections[i]
        next_section = sections[i + 1]
        parsed_sections[section.name] = contents[
            section.keyword_end : next_section.keyword_start
        ].strip()

    return parsed_sections


def search_keywords(contents, keywords):
    """
    Search multiple keywords in a given contents case insensitively, and return the first match

    Raises ValueError when none of the keywords is found in the contents
    """

    sense_pattern = re.compile(
        "|".join(rf"\b{re.escape(keyword)}\b" for keyword in keywords), re.IGNORECASE
    )
    match = sense_pattern.search(contents)
    return match.group(), match.start(), match.end()


def remove_comments(contents):
    """
    Remove the comments from the contents
    """

    contents = re.sub(
        re.compile(r"#.*?\n", re.DOTALL), "", contents
    )  # remove all occurrences of #COMMENT from line
    return contents


def parse_connection_relations(connection_relations):
    variables = []
    symmetric_relations = []
    implication_relations = []
    connection_relations = connection_relations.replace(" ", "")
    connection_relations = connection_relations.split("\n")
    for rel in connection_relations:
        rel = "".join(rel.split())
        if not rel:
            continue
        # Extract implication relations
        if "=>" in rel:
            if rel.count("=>") != 1:
                raise ValueError("Malformed implication relation: " + rel)
            rel = re.split(",|=>", rel)
            if any(not variable for variable in rel):
                raise ValueError("Empty variable in implication relation")
            implication_relations.append(rel)
        # Extract symmetric relations
        else:
            rel = rel.split(",")
            if any(not variable for variable in rel):
                raise ValueError("Empty variable in symmetric relation")
            symmetric_relations.append(rel)
        variables.extend(rel)
    variables = ordered_set(variables)
    return symmetric_relations, implication_relations, variables


def random_prefix_generator(N):
    """
    Generate a random string of length N
    """

    return "".join(random.choice(string.ascii_uppercase) for _ in range(N))


def get_variables_from_monomial(monomial):
    """
    It is fed by a non-constant monomial like x*y*z and
    returns a list consisting of given monomial's
    variables. which in this case are: ['x', 'y', 'z']
    """
    assert not monomial.isdigit()
    temp = monomial.split("*")
    temp.sort()
    return temp


def get_variables_from_list_of_monomials(list_of_monomials):
    """
    It is fed by a list of monomials and returns the variables
    which are used in the given monomials
    """
    vars = set()
    for monomial in list_of_monomials:
        vars = vars.union(get_variables_from_monomial(monomial))
    temp = list(vars)
    temp.sort()
    return temp


def get_monomials_from_polynomial(polynomial):
    """
    It is fed by a polynomial, and returns its monomials
    """

    monomials = polynomial.split("+")
    if "1" in monomials:
        monomials.remove("1")
    if "0" in monomials:
        monomials.remove("0")
    return list(set(monomials))


def get_monomials_from_list_of_polys(polys):
    """
    It is fed by a list of polynomials and returns
    all of the monomials which are used in the given
    polynomials
    """

    monomials = set()
    for poly in polys:
        monos = set(get_monomials_from_polynomial(poly))
        monomials = monomials.union(monos)
    return list(monomials)


def degree_of_monomial(monomial):
    """
    Returns the degree of the given monomial
    """

    vars = get_variables_from_monomial(monomial)
    return len(vars)


def algebraic_relations_to_connection_relations(algebraic_relations, reserved_variables=()):
    """
    Generate the connection relations derived from the given algebraic relations by introducing new variables
    It currently work for boolean polynomial relations merely
    Also creates a mapping from dummy variables to original monomials.
    Returns:
        connection_relations_str: string of relations
        dummy_mapping: dictionary {dummy_var: [original variables]}
    """

    connection_relations = []
    dummy_mapping = dict()
    from core.gf2poly import parse_gf2poly
    normalized = []
    for expression in algebraic_relations:
        if not expression.strip():
            continue
        polynomial = parse_gf2poly(expression)
        if polynomial.monomials == {frozenset()}:
            raise ValueError("Inconsistent algebraic equation: 1 = 0")
        if polynomial:
            normalized.append(str(polynomial).replace(" ", ""))
    algebraic_relations = normalized
    all_monomials = get_monomials_from_list_of_polys(algebraic_relations)
    algebraic_variables = get_variables_from_list_of_monomials(all_monomials)
    # Generate a random prefix and ensure it doesn't collide with existing variable names
    algebraic_variables_set = set(algebraic_variables) | set(reserved_variables)
    dummy_vars_prefix = random_prefix_generator(4)
    while any(v.startswith(dummy_vars_prefix) for v in algebraic_variables_set):
        dummy_vars_prefix = random_prefix_generator(4)
    substitution_dictionary = dict()
    for monomial in all_monomials:
        if degree_of_monomial(monomial) >= 2:
            monomial_variables = get_variables_from_monomial(monomial)
            var_indices = [algebraic_variables.index(x) for x in monomial_variables]
            var_indices = list(map(str, var_indices))
            dummy_var = "{0}{1}".format(dummy_vars_prefix, "x".join(var_indices))
            if dummy_var not in substitution_dictionary.values():
                connection_relations.append(
                    "{0}=>{1}".format(",".join(monomial_variables), dummy_var)
                )
                dummy_mapping[dummy_var] = (
                    monomial_variables  # Record dummy → original vars
                )
            substitution_dictionary[monomial] = dummy_var

    for poly in algebraic_relations:
        linearized_relation = [
            substitution_dictionary.get(term, term) for term in poly.split("+")
        ]
        if "1" in linearized_relation:
            linearized_relation.remove("1")
        if "0" in linearized_relation:
            linearized_relation.remove("0")
        connection_relations.append(",".join(linearized_relation))
    return "\n".join(connection_relations), dummy_mapping
