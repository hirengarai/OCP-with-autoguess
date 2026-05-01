'''
Created on Oct 4, 2020
Updated by Hiren on May 5, 2025 (removed sage dependency)

@author: Hosein Hadipour
@contact: hsn.hadipour@gmail.com
'''

import time
import sys
import re
from datetime import datetime
from argparse import ArgumentParser, RawTextHelpFormatter
from itertools import combinations


import numpy as np
# Handle both direct execution and module import
try:
    from .gf2poly import parse_gf2poly, GF2Poly, rref_gf2_u64, validate_packed_gf2_u64
except ImportError:
    from gf2poly import parse_gf2poly, GF2Poly, rref_gf2_u64, validate_packed_gf2_u64

def first_seen_var_names(lines):
    """
    Order the variables as per seen first
    """
    seen = set()
    ordered = []
    for line in lines:
        for name in re.findall(r"[A-Za-z_]\w*", line):
            if name not in seen:
                seen.add(name)
                ordered.append(name)
    return ordered


def poly_degree(poly: GF2Poly) -> int:
    """
    Return the total degree of a GF2Poly:
      max number of variables in any monomial.
    """
    # handle the zero polynomial
    if not poly.monomials:
        return 0
    return max(len(mono) for mono in poly.monomials)


def _pack_bits_to_uint64(mat: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Pack a binary matrix into uint64 words (little-endian bit order).

    Returns (packed_matrix, original_ncols).
    """
    rows, cols = mat.shape
    nwords = (cols + 63) // 64
    padded_cols = nwords * 64
    if padded_cols != cols:
        pad = np.zeros((rows, padded_cols - cols), dtype=np.uint8)
        mat = np.concatenate([mat, pad], axis=1)

    packed = np.packbits(mat, axis=1, bitorder="little")
    packed = np.ascontiguousarray(packed)
    return packed.view(np.uint64), cols


def _pivot_columns_from_packed(mat: np.ndarray, ncols: int) -> list[int]:
    """
    Extract pivot column indices from a packed RREF matrix.
    """
    pivots: list[int] = []
    for row in mat:
        for w, word in enumerate(row):
            word_int = int(word)
            if word_int:
                lsb = word_int & -word_int
                bit = lsb.bit_length() - 1
                col = w * 64 + bit
                if col < ncols:
                    pivots.append(col)
                break
    return pivots

class Macaulay:
    """
    Given a set of Boolean polynomials and a positive integer D, as well as a monomial ordering, 
    this class performs two main tasks:
    1- Constructing the Macaulay matrix of degree D
    2- Computing the reduced row echelon form of the derived Macaulay matrix
    """
    
    count = 0
    
    def __init__(self, inputfile, outputfile, D=2, term_ordering='deglex'):
        Macaulay.count += 1
        self.inputfile = inputfile
        self.outputfile = outputfile
        self.D = D
        self.term_ordering = term_ordering
        self.algebraize_input_polynomials()
        
    def algebraize_input_polynomials(self):
        try:
            with open(self.inputfile, 'r') as eqf:
                # Skip empty lines and comments
                lines = [L.strip() for L in eqf
                         if L.strip() and not L.strip().startswith('#')]
        except IOError:
            print(f'{self.inputfile} is not accessible!')
            sys.exit(1)
        
        # 1) Parse each algebraic relation into GF2Poly
        self.polynomials = [parse_gf2poly(line) for line in lines]  # list of GF2Poly

        # 2) Collect all variable names from monomials
        vars_set = set()
        for poly in self.polynomials:
            for mono in poly.monomials:    # mono is a frozenset of var-names
                vars_set.update(mono)
        self.variable_names = first_seen_var_names(lines)
    
    
    def build_macaulay_polynomials(self):
        """
        Constructs the Macaulay polynomials with degree at most D corresponding to the given boolean polynomial sequence
        """

        # 1) Prepare
        self.macaulay_polynomials = []
        nvars = len(self.variable_names)

        # 2) Compute degrees of each input GF2Poly via our poly_degree helper
        degrees = [poly_degree(f) for f in self.polynomials]
        degree_spectrum = sorted(set(degrees))

        unique_monos = set()
        for poly in self.polynomials:
            unique_monos |= poly.monomials   # union in all monomials
    
        print('Number of algebraic equations: %d' % len(self.polynomials))
        print('Number of algebraic variables: %d' % nvars)
        print('Number of algebraic monomials: %d' % len(unique_monos))
        print('Spectrum of degrees: %s' % degree_spectrum)


        # 3) Pre-compute the monomial multipliers for each degree d
        #    so that d + deg(multiplier) ≤ D
        multipliers = {}
        for d in degree_spectrum:
            r = self.D - d
            if r < 0:
                # if an equation already exceeds D, just multiply by 1
                multipliers[d] = [GF2Poly([frozenset()])]
                continue

            mons = []
            # generate all monomials of degree k = 0..r
            for k in range(r + 1):
                for idxs in combinations(range(nvars), k):
                    # build the frozenset of names for this monomial
                    mono_vars = frozenset(self.variable_names[i] for i in idxs)
                    mons.append(GF2Poly([mono_vars]))
            multipliers[d] = mons
       
        # 4) Multiply each input poly by its allowed multipliers,
        #    collecting only the non-zero products
        count = 0
        for f_poly, d in zip(self.polynomials, degrees):
            for m in multipliers[d]:
                prod = m * f_poly          # GF2Poly __mul__
                if prod:                   # skip the zero polynomial
                    self.macaulay_polynomials.append(prod)
                    count += 1
                    
        
    def build_macaulay_matrix(self):
        """
        Generate the Macaulay matrix over GF(2) from GF2Poly-based macaulay_polynomials.
        """
        # 1) Decide if we need Macaulay lifting (nonlinear case)
        degrees = [poly_degree(f) for f in self.polynomials]
        

        if max(degrees) > 1:
            min_deg = min(degrees)
            if self.D < min_deg:
                self.D = min_deg
            self.build_macaulay_polynomials()
        else:
            self.macaulay_polynomials = list(self.polynomials)

        # 2) Collect & sort all monomials (as exponent‐tuples) according to term ordering
        var_names = self.variable_names
        exps = set()
        for poly in self.macaulay_polynomials:
            for mono in poly.monomials:
                # mono is frozenset of var‐names → build an exp tuple
                exps.add(tuple(1 if v in mono else 0 for v in var_names))

        # Apply the chosen term ordering
        if self.term_ordering == 'degrevlex':
            # Degree reverse lexicographic: by total degree (descending), then reverse lex (descending)
            self.mons = sorted(exps, key=lambda e: (sum(e), tuple(reversed(e))), reverse=True)
        else:  # 'deglex' or default
            # Degree lexicographic: by total degree (descending), then lex (descending)
            self.mons = sorted(exps, key=lambda e: (sum(e), e), reverse=True)

        col_index = {exp: i for i, exp in enumerate(self.mons)}


        # 3) Build the 0/1 matrix
        n_rows = len(self.macaulay_polynomials)
        n_cols = len(self.mons)
        A = np.zeros((n_rows, n_cols), dtype=np.uint8)

        for i, poly in enumerate(self.macaulay_polynomials):
            for mono in poly.monomials:
                exp = tuple(1 if v in mono else 0 for v in var_names)
                A[i, col_index[exp]] = 1

        self.macaulay_matrix = A
        print(f"Macaulay matrix was generated in full matrixspace of {n_rows} by {n_cols} sparse matrices over finite field of size 2")

    def gaussian_elimination(self):
        """
        Perform RREF on a packed GF(2) matrix and compute pivot columns.
        """
        print('Gaussian elimination started - %s' % datetime.now())
        packed, ncols = _pack_bits_to_uint64(self.macaulay_matrix)
        validate_packed_gf2_u64(packed, ncols)
        # Warm up JIT so timing reflects steady-state performance
        rref_gf2_u64(packed.copy())

        t0 = time.time()
        packed, ncols = _pack_bits_to_uint64(self.macaulay_matrix)
        validate_packed_gf2_u64(packed, ncols)
        rref_gf2_u64(packed)

        pivots = _pivot_columns_from_packed(packed, ncols)

        # Unpack for downstream use (e.g., write_result)
        unpacked = np.unpackbits(packed.view(np.uint8), axis=1, bitorder="little")
        self.R = unpacked[:, :ncols].astype(np.uint8, copy=False)
        
        def is_constant(mono):
            return all(e == 0 for e in mono)

        # Exclude constant monomial from free/dependent count
        self.dependent = [m for j, m in enumerate(self.mons) if j in pivots and not is_constant(m)]
        self.free = [m for j, m in enumerate(self.mons) if j not in pivots and not is_constant(m)]

        print(f"#Dependent variables: {len(self.dependent)}")
        print(f"#Free variables: {len(self.free)}")
        elapsed = time.time() - t0
        print(f"Gaussian elimination was finished after {elapsed:.4f} seconds")
    
    def write_result(self):
        """
        Writes the reduced equations (rows of self.R) to self.outputfile
        using variable names in self.variable_names and monomials in self.mons.
        Also prints each equation to the console.
        """
        print('Writing the results into the %s - %s' % (self.outputfile, datetime.now()))
        t0 = time.time()
        try:
            with open(self.outputfile, 'w') as outf:
                # R should be your reduced-row-echelon form (NumPy array or list of lists)
                rows = np.array(self.R, dtype=np.uint8)

                for row in rows:
                    terms = []
                    for j, bit in enumerate(row):
                        if bit:
                            mono = self.mons[j]             
                            if sum(mono) == 0:
                                # constant term
                                terms.append('1')
                            else:
                                # select the variable names for exponent=1
                                var_list = [
                                    self.variable_names[i]
                                    for i, e in enumerate(mono) if e
                                ]
                                terms.append('*'.join(var_list))

                    if terms:
                        equation = ' + '.join(terms)
                        outf.write(equation + '\n')

        except IOError:
            print(f"Error: cannot write to {self.outputfile}")
            sys.exit(1)

        elapsed = time.time() - t0
        print(f"Result was written into {self.outputfile} after {elapsed:.2f} seconds")
    
def loadparameters(args):
    """
    Get parameters from the argument list and inputfile.
    """
    params = {'inputfile':'ex4.txt','outputfile':'macaulay_basis.txt','D':2,
              "term_ordering": 'deglex'}
    if args.inputfile: params['inputfile']=args.inputfile[0]
    if args.outputfile: params['outputfile']=args.outputfile[0]
    if args.D: params['D']=args.D[0]
    if args.term_ordering: params["term_ordering"] = args.term_ordering[0]
    return params


def main():
    """
    Parse the arguments and start the request functionality with the provided parameters.
    """
    parser = ArgumentParser(description="This tool computes the Macaulay matrix with degree D,"
                                        " given a system of boolean polynomials and"
                                        " a positive integer D",
                            formatter_class=RawTextHelpFormatter)
    parser.add_argument('-i','--inputfile', nargs=1, help="Use an input file in plaintext format to read the relations from.")
    parser.add_argument('-o','--outputfile', nargs=1, help="Use an output file to write the output into it.")
    parser.add_argument('-D','--D', nargs=1, type=int, help="A positive integer as the degree of Macaulay matrix.")
    parser.add_argument('-t', '--term_ordering', nargs=1, type=str, help="A term ordering such as deglex or degrevlex.")
    
    args = parser.parse_args()
    params = loadparameters(args)
    macaulay = Macaulay(inputfile=params['inputfile'], outputfile=params['outputfile'], D=params['D'], term_ordering=params['term_ordering'])
    macaulay.build_macaulay_matrix()
    macaulay.gaussian_elimination()
    macaulay.write_result()

if __name__ == '__main__':
    main()    
