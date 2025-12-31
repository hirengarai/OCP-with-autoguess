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
    if mat.dtype != np.uint64:
        raise TypeError("mat must be a uint64 array")
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
        # Initialize the polynomial with given monomials (each a frozenset).
        self.monomials: Set[FrozenSet[str]] = set(monomials)

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
# Supports +, *, ^, parentheses, and 0/1 literals.
# ---------------------------------------------------------------------
_token = re.compile(r'\s*([A-Za-z_]\w*|\d+|\^|\*|\+|\(|\))')

def parse_gf2poly(text: str) -> GF2Poly:
    """
    Parse an expression like "x*(x^4 + 1)" into a GF2Poly.
    Exponents are ignored (x^k -> x), and idempotence (x^2 = x) holds.
    """
    # Tokenize input string
    toks = [t for t in _token.findall(text) if t.strip()]
    pos = 0

    def nexttok() -> str:
        return toks[pos] if pos < len(toks) else None

    def parse_sum() -> GF2Poly:
        nonlocal pos
        poly = parse_prod()
        while nexttok() == '+':
            pos += 1  # consume '+'
            poly = poly + parse_prod()
        return poly

    def parse_prod() -> GF2Poly:
        nonlocal pos
        term = GF2Poly([frozenset()])  # start with 1
        while True:
            t = nexttok()
            if t is None or t in '+)':
                break
            if t == '(':  # parenthesized subexpression
                pos += 1
                factor = parse_sum()
                if nexttok() != ')':
                    raise SyntaxError("missing ')'")
                pos += 1  # consume ')'
            else:
                name = t
                pos += 1
                # Skip any exponent '^k'
                if nexttok() == '^':
                    pos += 2
                factor = const(int(name)) if name.isdigit() else var(name)

            term = term * factor
            if nexttok() == '*':
                pos += 1  # consume '*'
        return term

    result = parse_sum()
    if pos != len(toks):
        raise SyntaxError("junk at end of expression")
    return result