import re
from typing import FrozenSet, Iterable, Set
import numpy as np
import numba as nb

@nb.njit(parallel=True)
def rref_gf2_u64(mat: np.ndarray) -> int:
    """
    In-place Gauss-Jordan elimination (RREF) over GF(2) for a matrix stored as uint64 words.

    Each row of `mat` is an array of uint64 words, packing 64 bits per word.
    Returns the rank (number of pivot rows).
    """
    m, nwords = mat.shape
    pivot = 0

    # Iterate over bit-columns (total bits = nwords * 64)
    for col in range(nwords * 64):
        w, b = divmod(col, 64)
        # Find a row >= pivot with a 1 in bit (w,b)
        for i in range(pivot, m):
            if (mat[i, w] >> b) & 1:
                # Swap row i with pivot row
                mat[pivot], mat[i] = mat[i].copy(), mat[pivot].copy()
                break
        else:
            continue  # no pivot in this column, move to next

        # Eliminate this bit from all other rows in parallel
        for i in nb.prange(m):
            if i != pivot and ((mat[i, w] >> b) & 1):
                mat[i, :] ^= mat[pivot, :]

        pivot += 1
        if pivot == m:
            break

    return pivot


def validate_packed_gf2_u64(mat: np.ndarray, ncols: int) -> None:
    """
    Validate a bit-packed GF(2) matrix before elimination.
    """
    if ncols < 0:
        raise ValueError("ncols must be non-negative")
    if mat.ndim != 2:
        raise ValueError("mat must be two-dimensional")
    if mat.dtype != np.uint64:
        raise TypeError("mat must be a uint64 array")
    if mat.shape[1] != (ncols + 63) // 64:
        raise ValueError("packed width does not match ncols")
    if not mat.flags["C_CONTIGUOUS"]:
        raise ValueError("mat must be C-contiguous")

    rem = ncols % 64
    if rem == 0:
        return

    last_word = (ncols // 64)
    mask = np.uint64(0xFFFFFFFFFFFFFFFF) << np.uint64(rem)
    if np.any(mat[:, last_word] & mask):
        raise ValueError("padding bits must be zero")


class GF2Poly:
    """
    Polynomial over GF(2) with idempotent variables (x^2 = x).

    Internally, each polynomial is a set of monomials.
    Each monomial is represented as a frozenset of variable names.
    """

    def __init__(self, monomials: Iterable[FrozenSet[str]] = ()):
        # Repeated terms cancel, just as they do in addition over GF(2).
        self.monomials: Set[FrozenSet[str]] = set()
        for monomial in monomials:
            mono = frozenset(monomial)
            if mono in self.monomials:
                self.monomials.remove(mono)
            else:
                self.monomials.add(mono)

    def __xor__(self, other: "GF2Poly") -> "GF2Poly":
        """
        Add two polynomials over GF(2) (XOR): symmetric difference of monomial sets.
        """
        return GF2Poly(self.monomials ^ other.monomials)

    # Alias '+' operator to XOR behavior
    __add__ = __xor__ 

    def __mul__(self, other: "GF2Poly") -> "GF2Poly":
        """
        Multiply two polynomials over GF(2):
        For each pair of monomials, merge variable sets (idempotent union),
        toggling presence to handle mod-2 cancellation.
        """
        out: Set[FrozenSet[str]] = set()
        for m1 in self.monomials:
            for m2 in other.monomials:
                merged = frozenset(m1 | m2)
                # Toggle merged monomial in output set
                if merged in out:
                    out.remove(merged)
                else:
                    out.add(merged)
        return GF2Poly(out)

    def __bool__(self) -> bool:
        """
        Truth value of the polynomial: False if zero (no monomials), True otherwise.
        """
        return bool(self.monomials)

    def __str__(self) -> str:
        """
        Human-readable string: monomials sorted by degree then lexically,
        joined by ' + '.  Empty polynomial prints '0'.
        """
        if not self:
            return "0"

        # Sort monomials: by length (degree), then by variable names
        def key(mon: FrozenSet[str]) -> tuple:
            return (len(mon), tuple(sorted(mon)))

        parts = []
        for mon in sorted(self.monomials, key=key):
            # Join variable names with '*', empty monomial -> '1'
            part = "*".join(sorted(mon)) or "1"
            parts.append(part)
        return " + ".join(parts)

    # Use the same string for repr in REPL/debug
    __repr__ = __str__ 


def var(name: str) -> GF2Poly:
    """
    Create a single-variable polynomial representing 'name'.
    """
    return GF2Poly([frozenset([name])])


def const(bit: int) -> GF2Poly:
    """
    Create a constant polynomial 1 (if bit is odd) or 0 (if bit is even).
    """
    return GF2Poly([frozenset()]) if (bit & 1) else GF2Poly()


# ---------------------------------------------------------------------
# Very small recursive-descent parser for Boolean-polynomial expressions
# Supports +, -, *, ^/**, parentheses, and integer literals modulo 2.
# ---------------------------------------------------------------------
_token = re.compile(r'[A-Za-z_]\w*|[0-9]+|\*\*|[\^*+()\-]')

def parse_gf2poly(text: str) -> GF2Poly:
    """
    Parse a polynomial in GF(2)[x,...]/(x^2+x,...).

    Powers must have non-negative integer exponents. Every positive power
    of a Boolean polynomial equals itself; the zeroth power equals 1.
    Unsupported characters and incomplete expressions raise SyntaxError.
    """
    toks = []
    offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        match = _token.match(text, offset)
        if match is None:
            raise SyntaxError(f"unexpected character at position {offset}: {text[offset]!r}")
        toks.append(match.group())
        offset = match.end()
    pos = 0

    def nexttok() -> str:
        return toks[pos] if pos < len(toks) else None

    def parse_sum() -> GF2Poly:
        nonlocal pos
        poly = parse_prod()
        while nexttok() in ('+', '-'):
            pos += 1
            poly = poly + parse_prod()
        return poly

    def parse_prod() -> GF2Poly:
        nonlocal pos
        term = parse_factor()
        while nexttok() == '*':
            pos += 1
            term = term * parse_factor()
        return term

    def parse_factor() -> GF2Poly:
        nonlocal pos
        # Unary signs coincide over GF(2).
        while nexttok() in ('+', '-'):
            pos += 1
        token = nexttok()
        if token == '(':
            pos += 1
            factor = parse_sum()
            if nexttok() != ')':
                raise SyntaxError("missing ')'")
            pos += 1
        elif token is not None and (token.isdigit() or re.fullmatch(r'[A-Za-z_]\w*', token)):
            pos += 1
            factor = const(int(token)) if token.isdigit() else var(token)
        else:
            raise SyntaxError(f"expected a polynomial term, got {token!r}")
        if nexttok() in ('^', '**'):
            pos += 1
            exponent = nexttok()
            if exponent is None or not exponent.isdigit():
                raise SyntaxError("exponent must be a non-negative integer")
            pos += 1
            if int(exponent) == 0:
                factor = const(1)
        return factor

    result = parse_sum()
    if pos != len(toks):
        raise SyntaxError("junk at end of expression")
    return result
