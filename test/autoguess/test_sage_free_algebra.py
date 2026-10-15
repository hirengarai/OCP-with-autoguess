"""Independent correctness checks for the Boolean algebra replacing SageMath.

The references here are truth tables and a plain Python GF(2) elimination,
so they do not reuse the implementation under test or require SageMath.
"""

from itertools import combinations, product
from pathlib import Path
import random
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.autoguess.core.gf2poly import (
    GF2Poly, parse_gf2poly, rref_gf2_u64, validate_packed_gf2_u64,
)
from tools.autoguess.core.macaulay import (
    Macaulay, _pack_bits_to_uint64, _pivot_columns_from_packed,
)


def _value(poly, assignment):
    return sum(all(assignment[name] for name in term) for term in poly.monomials) % 2


def _python_rref(matrix):
    """Unpacked elimination with Python integers, independently of NumPy/JIT."""
    rows = matrix.tolist()
    pivot = 0
    pivots = []
    for col in range(matrix.shape[1]):
        candidate = next((i for i in range(pivot, len(rows)) if rows[i][col]), None)
        if candidate is None:
            continue
        rows[pivot], rows[candidate] = rows[candidate], rows[pivot]
        for i in range(len(rows)):
            if i != pivot and rows[i][col]:
                rows[i] = [a ^ b for a, b in zip(rows[i], rows[pivot])]
        pivots.append(col)
        pivot += 1
        if pivot == len(rows):
            break
    return np.array(rows, dtype=np.uint8).reshape(matrix.shape), pivots


def _run_macaulay(tmp_path, equations, degree, order='degrevlex'):
    source = tmp_path / 'equations.txt'
    output = tmp_path / 'basis.txt'
    source.write_text('\n'.join(equations))
    macaulay = Macaulay(source, output, D=degree, term_ordering=order)
    macaulay.build_macaulay_matrix()
    macaulay.gaussian_elimination()
    macaulay.write_result()
    return macaulay, [parse_gf2poly(line) for line in output.read_text().splitlines()]


def test_boolean_arithmetic_exhaustive_truth_tables():
    monomials = [frozenset(), frozenset({'x'}), frozenset({'y'}), frozenset({'x', 'y'})]
    polys = [GF2Poly(m for j, m in enumerate(monomials) if mask & (1 << j)) for mask in range(16)]
    assignments = [dict(zip(('x', 'y'), bits)) for bits in product((0, 1), repeat=2)]
    for left, right, assignment in product(polys, polys, assignments):
        a, b = _value(left, assignment), _value(right, assignment)
        assert _value(left + right, assignment) == a ^ b
        assert _value(left * right, assignment) == a & b
    assert not GF2Poly([frozenset({'x'}), frozenset({'x'})])


@pytest.mark.parametrize(('expression', 'expected'), [
    ('x^0', '1'), ('(x+y)^0', '1'), ('0^0', '1'),
    ('(x+y)^2', 'x+y'), ('(x+y)**7', 'x+y'),
    ('x*x + x', '0'), ('x*(y+1)+x*y', 'x'),
    ('-x + 3*y - y', 'x'), ('2*x + 3', '1'),
])
def test_parser_boolean_semantics(expression, expected):
    assert parse_gf2poly(expression).monomials == parse_gf2poly(expected).monomials


@pytest.mark.parametrize('expression', [
    '', '()', 'x*', '*x', 'x+', 'x^', 'x^y', 'x^-1',
    'x/2', 'x@y', 'x=y', 'x y', 'x^2^3', '(x+y', 'x+y)',
])
def test_parser_rejects_unsupported_or_incomplete_input(expression):
    with pytest.raises(SyntaxError):
        parse_gf2poly(expression)


@pytest.mark.parametrize('ncols', [0, 1, 7, 63, 64, 65, 127, 128, 129])
def test_packed_rref_matches_independent_elimination(ncols):
    rng = np.random.default_rng(1400 + ncols)
    for nrows in (0, 1, 9):
        matrix = rng.integers(0, 2, (nrows, ncols), dtype=np.uint8)
        if nrows == 9:
            matrix[-1] = matrix[0] ^ matrix[1]
        expected, pivots = _python_rref(matrix)
        packed, width = _pack_bits_to_uint64(matrix)
        validate_packed_gf2_u64(packed, width)
        assert rref_gf2_u64(packed) == len(pivots)
        actual = np.unpackbits(packed.view(np.uint8), axis=1, bitorder='little')[:, :width]
        np.testing.assert_array_equal(actual, expected)
        assert _pivot_columns_from_packed(packed, width) == pivots


def test_packed_matrix_validation_checks_width_and_padding():
    with pytest.raises(ValueError, match='width'):
        validate_packed_gf2_u64(np.zeros((1, 2), dtype=np.uint64), 64)
    with pytest.raises(ValueError, match='two-dimensional'):
        validate_packed_gf2_u64(np.zeros(2, dtype=np.uint64), 64)
    with pytest.raises(ValueError, match='padding'):
        validate_packed_gf2_u64(np.array([[2]], dtype=np.uint64), 1)


def test_degrevlex_matches_sage_definition(tmp_path):
    macaulay, _ = _run_macaulay(tmp_path, ['x*y+x*z+y*z+x+y+z+1'], 2)
    assert macaulay.mons == [
        (1, 1, 0), (1, 0, 1), (0, 1, 1),
        (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0),
    ]


def test_empty_and_zero_polynomials_are_supported(tmp_path):
    for equations in ([], ['0'], ['x+x']):
        macaulay, basis = _run_macaulay(tmp_path, equations, 2)
        assert not basis
        assert macaulay.free == macaulay.dependent == []


def test_canceled_variables_do_not_enter_macaulay_lifting(tmp_path):
    macaulay, basis = _run_macaulay(tmp_path, ['unused^0+1', 'x*y+z'], 3)
    assert macaulay.variable_names == ['x', 'y', 'z']
    assert all('unused' not in monomial for poly in basis for monomial in poly.monomials)


def test_macaulay_products_and_elimination_preserve_all_solutions(tmp_path):
    rng = random.Random(1408)
    names = ('x', 'y', 'z')
    terms = ['1', 'x', 'y', 'z', 'x*y', 'x*z', 'y*z']
    assignments = [dict(zip(names, bits)) for bits in product((0, 1), repeat=3)]
    for _ in range(12):
        equations = ['+'.join(rng.sample(terms, rng.randint(1, 5))) for _ in range(3)]
        originals = [parse_gf2poly(line) for line in equations]
        macaulay, basis = _run_macaulay(tmp_path, equations, 3)
        expected, _ = _python_rref(macaulay.macaulay_matrix)
        np.testing.assert_array_equal(macaulay.R, expected)
        for assignment in assignments:
            original_solution = all(_value(poly, assignment) == 0 for poly in originals)
            reduced_solution = all(_value(poly, assignment) == 0 for poly in basis)
            assert reduced_solution == original_solution
            if original_solution:
                assert all(_value(poly, assignment) == 0 for poly in macaulay.macaulay_polynomials)


# AutoGuess paper, Section 5.1, Example 2, Equation (3).
PAPER_EXAMPLE = [
    'x0*x2+x1*x3+x0+x2+x3',
    'x1*x2+x0*x3+x2*x3+x0+x1+x3',
    'x1*x3+x2*x3+x0+x2+1',
    'x0*x1+x0*x2+x1*x2+x2+x3+1',
    'x0*x1+x1*x2+x0*x3+x2',
    'x0*x2+x0*x3+x2*x3+x0+x1+x2+x3',
    'x0*x1+x1*x3+x0+1',
]


def _smallest_original_guess_basis(polynomials):
    """Independent closure search, treating nonlinear monomials as forward only."""
    names = ('x0', 'x1', 'x2', 'x3')
    equations = [poly.monomials - {frozenset()} for poly in polynomials if poly]
    all_terms = set().union(*equations)
    for size in range(5):
        for guessed in combinations(names, size):
            known = {frozenset({name}) for name in guessed}
            while True:
                updated = set(known)
                for term in all_terms:
                    if all(frozenset({name}) in known for name in term):
                        updated.add(term)
                for equation in equations:
                    unknown = equation - known
                    if len(unknown) == 1:
                        updated.update(unknown)
                if updated == known:
                    break
                known = updated
            if all(frozenset({name}) in known for name in names):
                return size


def test_paper_example_reproduces_preprocessing_improvements(tmp_path):
    originals = [parse_gf2poly(line) for line in PAPER_EXAMPLE]
    assert _smallest_original_guess_basis(originals) == 3
    for degree, expected_guesses in ((2, 2), (3, 1)):
        macaulay, basis = _run_macaulay(tmp_path, PAPER_EXAMPLE, degree)
        # Same matrix dimensions and ranks as upstream's published Sage run.
        assert macaulay.macaulay_matrix.shape == {2: (7, 11), 3: (35, 15)}[degree]
        assert len(macaulay.dependent) == {2: 7, 3: 13}[degree]
        assert _smallest_original_guess_basis(originals + basis) == expected_guesses


def test_macaulay_rejects_unsupported_configuration(tmp_path):
    source = tmp_path / 'equations.txt'
    source.write_text('x+y')
    with pytest.raises(ValueError, match='term_ordering'):
        Macaulay(source, tmp_path / 'basis', term_ordering='unsupported')
    with pytest.raises(ValueError, match='non-negative'):
        Macaulay(source, tmp_path / 'basis', D=-1)


@pytest.fixture
def relation_parser(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / 'tools' / 'autoguess'))
    from core import inputparser
    monkeypatch.setattr(inputparser, 'TEMP_DIR', str(tmp_path))
    return inputparser


@pytest.mark.parametrize(('expressions', 'expected'), [
    (['x+x+y'], 'y'), (['x*x+y'], 'x,y'),
    (['0', 'x+x'], ''), (['x^0+y'], 'y'),
])
def test_connection_conversion_normalizes_boolean_polynomials(relation_parser, expressions, expected):
    relations, mapping = relation_parser.algebraic_relations_to_connection_relations(expressions)
    assert relations == expected
    assert mapping == {}


def test_connection_conversion_rejects_constant_contradiction(relation_parser):
    with pytest.raises(ValueError, match='1 = 0'):
        relation_parser.algebraic_relations_to_connection_relations(['x+x+1'])


def test_dummy_variables_cannot_alias_existing_connections(relation_parser, monkeypatch, tmp_path):
    prefixes = iter(('ABCD', 'EFGH'))
    monkeypatch.setattr(relation_parser, 'random_prefix_generator', lambda _length: next(prefixes))
    source = tmp_path / 'collision.txt'
    source.write_text('connection relations\nABCD1x2,z\nalgebraic relations\nx*y+t\nknown\nt\ntarget\nz\nend\n')
    data = relation_parser.read_relation_file(source, preprocess=0)
    assert 'ABCD1x2' not in data['dummy_mapping']
    from core.solverresult import basis_result
    result = basis_result(data, [])
    assert result['status'] == 'unknown'
    assert result['missing_targets'] == ['z']


def test_preprocessor_failure_is_propagated(relation_parser, monkeypatch, tmp_path):
    source = tmp_path / 'relations.txt'
    source.write_text('algebraic relations\nx+y\nend\n')
    def fail(command, **kwargs):
        assert kwargs['check'] is True
        raise subprocess.CalledProcessError(7, command)
    monkeypatch.setattr(relation_parser.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError) as error:
        relation_parser.read_relation_file(source, preprocess=1)
    assert error.value.returncode == 7


def test_connection_deductions_are_sound_for_every_tiny_boolean_value(relation_parser):
    """Every abstract deduction must determine a unique actual Boolean value."""
    from core.solverresult import knowledge_trace
    names = ('x', 'y')
    terms = ('1', 'x', 'y', 'x*y')
    for mask in range(2, 16):  # Zero and the inconsistent constant one are separate tests.
        expression = '+'.join(term for i, term in enumerate(terms) if mask & (1 << i))
        polynomial = parse_gf2poly(expression)
        connection, mapping = relation_parser.algebraic_relations_to_connection_relations([expression])
        symmetric, implication, variables = relation_parser.parse_connection_relations(connection)
        data = {'variables': variables,
                'symmetric_relations': [rel for rel in symmetric if len(rel) > 1],
                'implication_relations': implication}
        fixed_known = {rel[0] for rel in symmetric if len(rel) == 1}
        solutions = []
        for bits in product((0, 1), repeat=2):
            assignment = dict(zip(names, bits))
            if _value(polynomial, assignment):
                continue
            assignment.update({dummy: int(all(assignment[name] for name in factors))
                               for dummy, factors in mapping.items()})
            solutions.append(assignment)
        for size in range(len(variables) + 1):
            for subset in combinations(variables, size):
                initially_known = set(subset) | fixed_known
                determined, _ = knowledge_trace(data, initially_known)
                for first, second in product(solutions, solutions):
                    if all(first[name] == second[name] for name in initially_known):
                        assert all(first[name] == second[name] for name in determined)
