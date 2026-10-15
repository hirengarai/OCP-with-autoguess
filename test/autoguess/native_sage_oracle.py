"""JSON oracle using installed Sage library components, with no OCP imports.

Run with a full Sage Python or an isolated environment containing
passagemath-brial and passagemath-modules[GF2].  PassageMath is a compatible
SageMath fork; the response records its exact distribution versions and native
implementation types, rather than presenting it as the upstream application.
"""

import ast
from contextlib import redirect_stdout
import hashlib
import io
from importlib import metadata
from itertools import combinations
import json
import re
import sys
import tempfile
from pathlib import Path

from sage.matrix.constructor import matrix
from sage.rings.finite_rings.finite_field_constructor import GF
from sage.rings.polynomial.pbori.pbori import BooleanPolynomialRing
from sage.rings.polynomial.multi_polynomial_sequence import PolynomialSequence


def _parse(expression, ring):
    """Evaluate only arithmetic AST nodes, using native Boolean ring objects."""
    variables = dict(zip(ring.variable_names(), ring.gens()))

    def visit(node):
        if isinstance(node, ast.Name):
            return variables[node.id]
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return ring(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = visit(node.left)
            if isinstance(node.op, ast.Pow):
                if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int:
                    raise ValueError("Only literal non-negative exponents are supported")
                if node.right.value < 0:
                    raise ValueError("Negative exponents are unsupported")
                return left ** node.right.value
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
        raise ValueError("Unsupported polynomial syntax")

    return ring(visit(ast.parse(expression.replace('^', '**'), mode='eval').body))


def _terms(poly):
    names = poly.parent().variable_names()
    # PolyBoRi's public indices correspond to the ring generators.  In the
    # installed native library, variables() mislabels degrevlex monomials;
    # iterindex() avoids that unrelated display/introspection defect.
    return sorted(sorted(names[int(index)] for index in monomial.iterindex())
                  for monomial in poly.monomials())


def _matrix_result(value):
    reduced = value.echelon_form()
    return {
        'shape': [int(value.nrows()), int(value.ncols())],
        'matrix': [[int(entry) for entry in row] for row in value.rows()],
        'rref': [[int(entry) for entry in row] for row in reduced.rows()],
        'rank': int(value.rank()),
        'pivots': [int(col) for col in reduced.pivots()],
        'matrix_type': type(value).__module__ + '.' + type(value).__name__,
    }


def _macaulay(case):
    equations = case['equations']
    # Establish variable order independently, and remove canceled variables by
    # querying the installed native ring's normalized polynomials.
    names = list(dict.fromkeys(re.findall(r'[A-Za-z_]\w*', '\n'.join(equations))))
    # Native PolyBoRi requires at least one generator.  An unused generator
    # lets it represent the constant/empty systems without adding any columns.
    ring_names = names or ['oracleUnused']
    ring = BooleanPolynomialRing(len(ring_names), names=ring_names, order=case['order'])
    polynomials = [_parse(expression, ring) for expression in equations]
    used = {name for poly in polynomials for term in _terms(poly) for name in term}
    names = [name for name in names if name in used]
    ring_names = names or ['oracleUnused']
    ring = BooleanPolynomialRing(len(ring_names), names=ring_names, order=case['order'])
    polynomials = [_parse(str(poly), ring) for poly in polynomials]
    degree = int(case['degree'])
    degrees = [max(0, int(poly.degree())) for poly in polynomials]
    if degrees and max(degrees) > 1:
        degree = max(degree, min(degrees))
        lifted = []
        for poly, poly_degree in zip(polynomials, degrees):
            # As in upstream AutoGuess, get the multipliers from native leading
            # monomial divisors.  Cap at nvars: every Boolean monomial is then
            # included even when the requested degree exceeds nvars.
            if degree <= poly_degree:
                multipliers = [ring.one()]
            else:
                size = min(degree - poly_degree, len(names))
                multipliers = set()
                for subset in combinations(ring.gens(), size):
                    leading = ring.one()
                    for variable in subset:
                        leading *= variable
                    multipliers.update(leading.lead_divisors())
                multipliers = sorted(multipliers, key=str)
            lifted.extend(product for multiplier in multipliers
                          if (product := multiplier * poly))
    else:
        lifted = polynomials

    if any(lifted):
        # This is the same Sage API used by upstream AutoGuess.  The native
        # polynomial sequence supplies term ordering and matrix coefficients.
        value, monomials = PolynomialSequence(ring, lifted).coefficients_monomials()
        value = matrix(GF(2), value, sparse=False)
        ordered = [ring(monomial) for monomial in monomials]
    else:
        value = matrix(GF(2), len(lifted), 0)
        ordered = []
    result = _matrix_result(value)
    result.update({
        'names': names,
        'degree': degree,
        'monomials': [[int(name in set(_terms(monomial)[0]))
                       for name in names] for monomial in ordered],
        'lifted': sorted(_terms(poly) for poly in lifted),
    })
    return result


def _upstream(case, source_path):
    """Run upstream mathematical methods unchanged with explicit ring input.

    Only its broad sage.all import is replaced with the native names it uses.
    Its symbolic input parser is bypassed so both implementations have the same
    explicit variable order (upstream obtains a nondeterministic set order).
    """
    from sage.combinat.integer_vector import IntegerVectors
    from sage.misc.flatten import flatten
    from sage.rings.integer import Integer

    source = Path(source_path).read_bytes()
    code = source.decode()
    if code.count('from sage.all import *') != 1:
        raise ValueError('Unrecognized upstream import layout')
    namespace = {'__name__': 'upstream_macaulay_comparison',
                 'IntegerVectors': IntegerVectors, 'Integer': Integer, 'flatten': flatten,
                 'BooleanPolynomialRing': BooleanPolynomialRing}
    exec(compile(code.replace('from sage.all import *', ''), str(source_path), 'exec'), namespace)
    names = list(dict.fromkeys(re.findall(r'[A-Za-z_]\w*', '\n'.join(case['equations']))))
    ring = BooleanPolynomialRing(len(names), names=names, order=case['order'])
    sequence = PolynomialSequence(ring, [_parse(expression, ring) for expression in case['equations']])
    value = namespace['Macaulay'].__new__(namespace['Macaulay'])
    value.PolyRing = ring
    value.polynomial_sequence = sequence
    value.D = case['degree']
    value.term_ordering = case['order']
    with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(io.StringIO()):
        value.outputfile = str(Path(temp_dir) / 'basis.txt')
        value.build_macaulay_matrix()
        initial = matrix(GF(2), value.macaulay_matrix, sparse=False)
        value.gaussian_elimination()
        value.write_result()
        basis = Path(value.outputfile).read_text().splitlines()
    result = _matrix_result(matrix(GF(2), initial, sparse=False))
    result.update({'names': names, 'degree': int(value.D), 'basis': basis,
                   'source_sha256': hashlib.sha256(source).hexdigest(),
                   'monomials': [[int(name in set(_terms(ring(monomial))[0])) for name in names]
                                  for monomial in value.macaulay_vars]})
    # Also check that the original in-place echelonize agrees with its native
    # dense RREF, rather than replacing the original elimination silently.
    result['upstream_rref'] = [[int(entry) for entry in row] for row in value.macaulay_matrix.rows()]
    return result


def main():
    request = json.load(sys.stdin)
    versions = {}
    for name in ('sagemath-standard', 'passagemath-brial', 'passagemath-modules',
                 'passagemath-m4ri', 'passagemath-categories'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    response = {'versions': versions, 'python': sys.version, 'arithmetic': [],
                'ordering': [], 'matrices': [], 'macaulay': [], 'upstream': []}
    for case in request.get('arithmetic', []):
        ring = BooleanPolynomialRing(len(case['names']), names=case['names'])
        left, right = (_parse(case[key], ring) for key in ('left', 'right'))
        response['arithmetic'].append({
            'left': _terms(left), 'right': _terms(right),
            'sum': _terms(left + right), 'product': _terms(left * right),
            'polynomial_type': type(left).__module__ + '.' + type(left).__name__,
        })
    for case in request.get('ordering', []):
        ring = BooleanPolynomialRing(len(case['names']), names=case['names'], order=case['order'])
        polynomial = _parse(case['expression'], ring)
        response['ordering'].append([
            [int(name in {ring.variable_names()[int(index)] for index in monomial.iterindex()})
             for name in case['names']]
            for monomial in polynomial.monomials()
        ])
    for case in request.get('matrices', []):
        value = matrix(GF(2), case['nrows'], case['ncols'], case['entries'])
        response['matrices'].append(_matrix_result(value))
    for case in request.get('macaulay', []):
        try:
            response['macaulay'].append(_macaulay(case))
        except Exception as error:
            raise RuntimeError(f'Native oracle case failed: {case}') from error
    for case in request.get('upstream', []):
        response['upstream'].append(_upstream(case, request['upstream_source']))
    json.dump(response, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
