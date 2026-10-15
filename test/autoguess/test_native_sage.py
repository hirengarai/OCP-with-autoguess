"""Optional comparisons with installed, compiled Sage mathematical libraries.

Set OCP_SAGE_PYTHON to a Sage-capable Python executable, or OCP_SAGE_COMMAND to
e.g. ``sage -python``.  The separate files/native-sage-env is also detected.
No Sage package is required by, or imported into, the OCP runtime.
"""

from itertools import combinations
import json
import hashlib
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.autoguess.core.gf2poly import parse_gf2poly, rref_gf2_u64
from tools.autoguess.core.macaulay import (
    Macaulay, _pack_bits_to_uint64, _pivot_columns_from_packed,
)
from test_sage_free_algebra import PAPER_EXAMPLE, _smallest_original_guess_basis


def _request():
    rng = random.Random(151026)
    names = ['alpha_0', 'zeta', 'b2', 'x9', 'tmp']
    terms = ['1'] + ['*'.join(subset) for size in range(1, 4)
                     for subset in combinations(names, size)]
    arithmetic = [{'names': names, 'left': expression, 'right': 'alpha_0+zeta+1'}
                  for expression in ('0', '1', 'alpha_0^0', '0^0', '(alpha_0+zeta)^7',
                                     'alpha_0*alpha_0+alpha_0', '-alpha_0+3*zeta-zeta',
                                     '2*alpha_0+3', 'alpha_0*(zeta+1)+alpha_0*zeta')]
    for _ in range(160):
        arithmetic.append({'names': names,
                           'left': '+'.join(rng.choices(terms, k=rng.randint(1, 9))),
                           'right': '+'.join(rng.choices(terms, k=rng.randint(1, 9)))})
    all_terms = ['1'] + ['*'.join(subset) for size in range(1, len(names) + 1)
                         for subset in combinations(names, size)]
    ordering = [{'names': names, 'order': order, 'expression': '+'.join(all_terms)}
                for order in ('deglex', 'degrevlex')]

    matrices = []
    numpy_rng = np.random.default_rng(151026)
    for ncols in (0, 1, 7, 63, 64, 65, 127, 128, 129):
        for nrows in (0, 1, 12):
            value = numpy_rng.integers(0, 2, (nrows, ncols), dtype=np.uint8)
            if nrows == 12:
                value[-1] = value[0] ^ value[1]
            matrices.append({'nrows': nrows, 'ncols': ncols,
                             'entries': value.ravel().tolist()})

    macaulay = []
    edge_cases = [([], 2), (['0'], 2), (['unused^0+1', 'alpha_0*zeta+b2'], 3),
                  (['1'], 3), (['alpha_0+zeta+1', 'alpha_0+zeta+1'], 0),
                  (['alpha_0*zeta+b2', 'alpha_0+1'], 0),
                  (['alpha_0*zeta+alpha_0', 'zeta+1'], 7)]
    for order in ('deglex', 'degrevlex'):
        macaulay.extend({'equations': equations, 'degree': degree, 'order': order}
                        for equations, degree in edge_cases)
        macaulay.extend({'equations': PAPER_EXAMPLE, 'degree': degree, 'order': order,
                         'paper': True} for degree in (2, 3))
        for nvars in (2, 3, 4, 5):
            pool = ['1'] + ['*'.join(subset) for size in range(1, min(3, nvars) + 1)
                            for subset in combinations(names[:nvars], size)]
            for _ in range(10):
                equations = ['+'.join(rng.choices(pool, k=rng.randint(1, 6)))
                             for _ in range(rng.randint(1, 6))]
                macaulay.append({'equations': equations, 'degree': rng.randint(0, 5), 'order': order})
    upstream = []
    for order in ('deglex', 'degrevlex'):
        upstream.extend({'equations': PAPER_EXAMPLE, 'degree': degree, 'order': order, 'paper': True}
                        for degree in (2, 3))
        pool = ['1'] + ['*'.join(subset) for size in range(1, 4)
                        for subset in combinations(names, size)]
        for _ in range(10):
            equations = ['+'.join(rng.sample(pool, 6)) for _ in range(6)]
            upstream.append({'equations': equations, 'degree': rng.randint(2, 4), 'order': order})
    return {'arithmetic': arithmetic, 'ordering': ordering, 'matrices': matrices, 'macaulay': macaulay,
            'upstream': upstream}


@pytest.fixture(scope='module')
def native_sage():
    explicit = os.environ.get('OCP_SAGE_COMMAND')
    executable = os.environ.get('OCP_SAGE_PYTHON')
    isolated = ROOT / 'files' / 'native-sage-env' / 'bin' / 'python'
    if explicit:
        command = shlex.split(explicit)
    elif executable:
        command = [executable]
    elif isolated.exists():
        command = [str(isolated)]
    elif shutil.which('sage'):
        command = [shutil.which('sage'), '-python']
    else:
        pytest.skip('Set OCP_SAGE_PYTHON to an installed Sage-capable Python')
    request = _request()
    upstream_source = Path(os.environ.get('OCP_UPSTREAM_MACAULAY_SOURCE',
                           ROOT / 'files' / 'autoguess-native-validation-2026-10-15' / 'upstream_macaulay.py'))
    if upstream_source.exists():
        request['upstream_source'] = str(upstream_source)
    else:
        request['upstream'] = []
    completed = subprocess.run(command + [str(Path(__file__).with_name('native_sage_oracle.py'))],
                               input=json.dumps(request), text=True, capture_output=True,
                               timeout=180, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    artifact = os.environ.get('OCP_NATIVE_SAGE_REPORT')
    if artifact:
        Path(artifact).write_text(json.dumps({'request': request, 'native': result}, indent=2) + '\n')
    return request, result


def _terms(poly):
    return sorted(sorted(monomial) for monomial in poly.monomials)


def test_boolean_arithmetic_matches_installed_sage(native_sage):
    request, result = native_sage
    for case, expected in zip(request['arithmetic'], result['arithmetic'], strict=True):
        left, right = (parse_gf2poly(case[key]) for key in ('left', 'right'))
        assert _terms(left) == expected['left'], case
        assert _terms(right) == expected['right'], case
        assert _terms(left + right) == expected['sum'], case
        assert _terms(left * right) == expected['product'], case
        assert expected['polynomial_type'].startswith('sage.rings.polynomial.pbori.'), expected


@pytest.mark.parametrize('order_index', (0, 1), ids=('deglex', 'degrevlex'))
def test_monomial_order_matches_installed_sage(native_sage, tmp_path, order_index):
    request, result = native_sage
    case = request['ordering'][order_index]
    source = tmp_path / 'ordering.txt'
    source.write_text(case['expression'])
    value = Macaulay(source, tmp_path / 'basis.txt', D=0, term_ordering=case['order'])
    value.build_macaulay_matrix()
    assert [list(monomial) for monomial in value.mons] == result['ordering'][order_index]


@pytest.mark.parametrize('ncols', (0, 1, 7, 63, 64, 65, 127, 128, 129))
def test_packed_rref_matches_installed_sage(native_sage, ncols):
    request, result = native_sage
    for case, expected in zip(request['matrices'], result['matrices'], strict=True):
        if case['ncols'] != ncols:
            continue
        value = np.array(case['entries'], dtype=np.uint8).reshape(case['nrows'], ncols)
        packed, width = _pack_bits_to_uint64(value)
        assert rref_gf2_u64(packed) == expected['rank']
        reduced = np.unpackbits(packed.view(np.uint8), axis=1, bitorder='little')[:, :width]
        assert reduced.tolist() == expected['rref']
        assert _pivot_columns_from_packed(packed, width) == expected['pivots']
        if ncols and case['nrows']:
            assert 'matrix_mod2_dense' in expected['matrix_type'], expected


@pytest.mark.parametrize('order', ('deglex', 'degrevlex'))
def test_macaulay_matches_installed_sage(native_sage, tmp_path, order):
    request, result = native_sage
    for index, (case, expected) in enumerate(zip(request['macaulay'], result['macaulay'], strict=True)):
        if case['order'] != order:
            continue
        source = tmp_path / f'equations-{index}.txt'
        output = tmp_path / f'basis-{index}.txt'
        source.write_text('\n'.join(case['equations']))
        value = Macaulay(source, output, D=case['degree'], term_ordering=order)
        value.build_macaulay_matrix()
        value.gaussian_elimination()
        value.write_result()
        assert value.variable_names == expected['names'], case
        assert value.D == expected['degree'], case
        assert [list(monomial) for monomial in value.mons] == expected['monomials'], case
        assert list(value.macaulay_matrix.shape) == expected['shape'], case
        assert sorted(_terms(poly) for poly in value.macaulay_polynomials) == expected['lifted'], case
        # Native multiplier iteration may use a different row order.  RREF is
        # unique for a fixed ordered list of monomial columns.
        assert value.R.tolist() == expected['rref'], case
        assert len(value.dependent) + int(any(not any(value.mons[col])
                                             for col in expected['pivots'])) == expected['rank'], case
        if case.get('paper'):
            basis = [parse_gf2poly(line) for line in output.read_text().splitlines()]
            originals = [parse_gf2poly(line) for line in PAPER_EXAMPLE]
            assert _smallest_original_guess_basis(originals + basis) == {2: 2, 3: 1}[case['degree']]


def test_original_upstream_macaulay_methods_match(native_sage, tmp_path):
    request, result = native_sage
    if not request['upstream']:
        pytest.skip('Set OCP_UPSTREAM_MACAULAY_SOURCE to the downloaded upstream source')
    source_hash = hashlib.sha256(Path(request['upstream_source']).read_bytes()).hexdigest()
    for index, (case, expected) in enumerate(zip(request['upstream'], result['upstream'], strict=True)):
        source, output = tmp_path / f'upstream-{index}.txt', tmp_path / f'basis-{index}.txt'
        source.write_text('\n'.join(case['equations']))
        value = Macaulay(source, output, D=case['degree'], term_ordering=case['order'])
        value.build_macaulay_matrix()
        value.gaussian_elimination()
        value.write_result()
        assert expected['source_sha256'] == source_hash
        assert value.variable_names == expected['names'], case
        assert [list(monomial) for monomial in value.mons] == expected['monomials'], case
        assert value.D == expected['degree'], case
        # Upstream retains zero products as empty rows; the replacement omits
        # them.  Their nonzero reduced bases must still agree exactly.
        assert [row for row in value.R.tolist() if any(row)] == [row for row in expected['rref'] if any(row)], case
        assert expected['rref'] == expected['upstream_rref'], case
        ours = sorted(_terms(parse_gf2poly(line)) for line in output.read_text().splitlines())
        original = sorted(_terms(parse_gf2poly(line)) for line in expected['basis'])
        assert ours == original, case
