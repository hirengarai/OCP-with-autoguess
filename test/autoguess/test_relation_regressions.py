"""Small independent correctness checks for OCP's AutoGuess relation export.

Run with: env312/bin/python -m unittest discover -s test/autoguess -p test_relation_regressions.py
"""
import itertools
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from variables.variables import Variable
from operators.matrix import Matrix, GF2Linear_Trans
from operators.Sbox import Skinny_4bit_Sbox, Sbox
from operators.operators import Equal, Rot
from operators.boolean_operators import ConstantXOR, XOR
from tools.relation_generator import generate_relations, _format_with_headers
from tools.relation_generator_modules.cleaner import clean_relations
from tools.relation_generator_modules.emitter import emit_function, emit_cipher


def variables(prefix, count, width=1):
    return [Variable(width, ID=f"{prefix}{i}") for i in range(count)]


def directional_rules(lines):
    """Interpret connection relations independently of the AutoGuess parser."""
    rules = []
    section = "connection relations"
    for line in lines:
        if line in ("connection relations", "algebraic relations", "known", "target", "not guessed", "end"):
            section = line
            continue
        if section != "connection relations":
            continue
        line = line.replace(", KNOWLEDGE_EQ", "").replace(", NONRENAME", "")
        if "=>" in line:
            lhs, rhs = line.split("=>")
            rules.append((frozenset(v.strip() for v in lhs.split(",") if v.strip()), rhs.strip()))
        else:
            terms = [v.strip() for v in line.split(",")]
            for idx, target in enumerate(terms):
                rules.append((frozenset(terms[:idx] + terms[idx + 1:]), target))
    return rules


def closure(lines, known):
    known = set(known)
    rules = directional_rules(lines)
    while True:
        updated = known | {target for inputs, target in rules if inputs <= known}
        if updated == known:
            return known
        known = updated


def finite_field_product(a, b, width, polynomial):
    """Independent polynomial multiplication/reduction used by the test oracle."""
    product = 0
    for bit in range(width):
        if b & (1 << bit):
            product ^= a << bit
    for bit in range(2 * width - 2, width - 1, -1):
        if product & (1 << bit):
            product ^= polynomial << (bit - width)
    return product


def matrix_values(matrix, inputs, width=1, polynomial=0b11):
    outputs = []
    for row in matrix:
        value = 0
        for coefficient, word in zip(row, inputs):
            value ^= finite_field_product(coefficient, word, width, polynomial)
        outputs.append(value)
    return dict(zip([f"x{i}" for i in range(len(inputs))] + [f"y{i}" for i in range(len(outputs))], list(inputs) + outputs))


def tiny_function(ops):
    return SimpleNamespace(name="probe", nbr_rounds=1, nbr_layers=0,
                           constraints={1: {0: ops}}, vars={1: {0: []}})


class MatrixRelations(unittest.TestCase):
    SKINNY = [[1, 0, 1, 1], [1, 0, 0, 0], [0, 1, 1, 0], [1, 0, 1, 0]]

    def assert_rules_sound(self, relations, assignments):
        for antecedent, target in directional_rules(relations):
            observations = {}
            for assignment in assignments:
                key = tuple(assignment[var] for var in sorted(antecedent))
                if key in observations:
                    self.assertEqual(observations[key], assignment[target], (antecedent, target))
                observations[key] = assignment[target]

    def test_skinny_implications_match_actual_values(self):
        operator = Matrix("skinny", variables("x", 4), variables("y", 4), self.SKINNY)
        relations = operator.gen_autoguess_constr()
        assignments = [matrix_values(self.SKINNY, values) for values in itertools.product(range(2), repeat=4)]
        self.assert_rules_sound(relations, assignments)
        self.assertIn("x0", closure(relations, ["y1"]))
        self.assertNotIn("x3", closure(relations, ["x0", "x1", "x2", "y1"]))

    def test_binary_rank_rules_are_complete_on_small_systems(self):
        rng = random.Random(20261015)
        for _ in range(12):
            matrix = [[rng.randrange(2) for _ in range(3)] for _ in range(3)]
            operator = Matrix("binary", variables("x", 3), variables("y", 3), matrix)
            relations = operator.gen_autoguess_constr()
            assignments = [matrix_values(matrix, values) for values in itertools.product(range(2), repeat=3)]
            names = list(assignments[0])
            for bits in itertools.product(range(2), repeat=len(names)):
                known = [name for name, bit in zip(names, bits) if bit]
                determined = set()
                for target in names:
                    observations = {}
                    valid = True
                    for assignment in assignments:
                        key = tuple(assignment[name] for name in known)
                        if key in observations and observations[key] != assignment[target]:
                            valid = False
                            break
                        observations[key] = assignment[target]
                    if valid:
                        determined.add(target)
                self.assertEqual(closure(relations, known), determined, (matrix, known))

    def test_nonbinary_field_coefficients_are_preserved(self):
        matrix = [[1, 1], [1, 2]]
        operator = Matrix("gf4", variables("x", 2, 2), variables("y", 2, 2), matrix, polynomial=0b111)
        relations = operator.gen_autoguess_constr()
        assignments = [matrix_values(matrix, values, 2, 0b111) for values in itertools.product(range(4), repeat=2)]
        self.assert_rules_sound(relations, assignments)
        self.assertEqual(len(relations), 12)

    def test_aes_mds_relations_still_have_any_four_coordinates(self):
        matrix = [[2, 3, 1, 1], [1, 2, 3, 1], [1, 1, 2, 3], [3, 1, 1, 2]]
        operator = Matrix("aes", variables("x", 4, 8), variables("y", 4, 8), matrix, polynomial=0x1b)
        relations = operator.gen_autoguess_constr()
        self.assertEqual(len(relations), 280)
        self.assertTrue(all(len(antecedent) == 4 for antecedent, _ in directional_rules(relations)))
        with self.assertRaisesRegex(ValueError, "binary coefficients only"):
            operator.gen_autoguess_constr(algebraic_mode=True)

    def test_binary_algebraic_mode_emits_true_row_equations(self):
        operator = Matrix("skinny", variables("x", 4), variables("y", 4), self.SKINNY)
        equations = operator.gen_autoguess_constr(algebraic_mode=True)
        self.assertTrue(all("+" in line for line in equations))
        for values in itertools.product(range(2), repeat=4):
            assignment = matrix_values(self.SKINNY, values)
            for equation in equations:
                parity = 0
                for term in equation.split("+"):
                    parity ^= assignment[term.strip()]
                self.assertEqual(parity, 0)

    def test_zero_row_produces_an_unconditionally_known_word(self):
        operator = Matrix("zero", variables("x", 1), variables("y", 1), [[0]])
        relations = clean_relations(_format_with_headers(operator.gen_autoguess_constr(), None, ["y0"], None))
        self.assertIn("y0", closure(relations, []))
        self.assertNotIn("x0", closure(relations, []))


class AliasRelations(unittest.TestCase):
    def test_duplicate_symmetric_operands_never_invent_an_inverse(self):
        x, y, z = "vs_1_0_0", "vs_1_1_0", "vs_1_2_0"
        relations = clean_relations(_format_with_headers([f"{x}, {y}", f"{x}, {y}, {z}"], [z], [x], None))
        self.assertNotIn(x, closure(relations, [z]))
        self.assertIn(z, closure(relations, [x]))

    def test_direct_duplicate_tokens_have_the_same_safe_semantics(self):
        relations = clean_relations(_format_with_headers(["x, x, z"], ["z"], ["x"], None))
        self.assertNotIn("x", closure(relations, ["z"]))
        self.assertIn("z", closure(relations, ["x"]))

    def test_sbox_knowledge_alias_is_preserved_in_a_polynomial_model(self):
        x, y, z = [Variable(4, ID=f"vs_1_{i}_0") for i in range(3)]
        sbox = Skinny_4bit_Sbox([x], [y])
        raw = sbox.gen_autoguess_constr() + XOR([x, y], [z]).gen_autoguess_constr(algebraic_mode=True)
        relations = clean_relations(_format_with_headers(raw, None, None, None))
        self.assertIn(f"{x.ID} + {y.ID} + {z.ID}", relations)
        self.assertIn(f"{x.ID}, {y.ID}", relations)
        self.assertEqual(sbox.table[0] ^ 0, 12)  # the equation must not become z=0

    def test_bijection_alias_still_collapses_for_connection_only_models(self):
        x, y, z = [Variable(4, ID=f"vs_1_{i}_0") for i in range(3)]
        raw = Skinny_4bit_Sbox([x], [y]).gen_autoguess_constr() + [f"{y.ID}, {z.ID}, NONRENAME"]
        relations = clean_relations(_format_with_headers(raw, [x.ID], [z.ID], None))
        self.assertNotIn(y.ID, "\n".join(relations))
        self.assertIn(z.ID, closure(relations, [x.ID]))

    def test_rotation_and_constant_do_not_replace_values_in_polynomials(self):
        x, y, z = [Variable(4, ID=f"vs_1_{i}_0") for i in range(3)]
        for operator in (Rot([x], [y], "l", 1), ConstantXOR([x], [y], [[1]], round=1)):
            raw = operator.gen_autoguess_constr() + [f"{x.ID} + {y.ID} + {z.ID}"]
            relations = clean_relations(_format_with_headers(raw, None, None, None))
            self.assertIn(f"{x.ID} + {y.ID} + {z.ID}", relations)

    def test_identity_only_roles_remain_in_the_solver_universe(self):
        x, y = "vs_1_0_0", "vs_1_1_0"
        relations = clean_relations(_format_with_headers([f"{x}, {y}"], [x], [y], None))
        self.assertIn(f"{x} => {x}", relations)

    def test_unknown_role_is_not_promoted_to_a_modeled_variable(self):
        relations = clean_relations(_format_with_headers(["a,b"], None, ["typo"], None))
        self.assertNotIn("typo => typo", relations)


class OperatorEmission(unittest.TestCase):
    def test_invertible_skinny_lfsr_has_both_word_directions(self):
        matrix = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [1, 1, 0, 0]]
        x, y = variables("x", 1, 4)[0], variables("y", 1, 4)[0]
        operator = GF2Linear_Trans([x], [y], matrix)
        relations = operator.gen_autoguess_constr()
        self.assertIn(y.ID, closure(relations, [x.ID]))
        self.assertIn(x.ID, closure(relations, [y.ID]))
        images = set()
        for value in range(16):
            output = 0
            for i, row in enumerate(matrix):
                bit = 0
                for j, coefficient in enumerate(row):
                    bit ^= coefficient & ((value >> (3 - j)) & 1)
                output |= bit << (3 - i)
            images.add(output)
        self.assertEqual(len(images), 16)

    def test_singular_transform_does_not_invent_an_inverse(self):
        operator = GF2Linear_Trans(variables("x", 1, 2), variables("y", 1, 2), [[1, 0], [0, 0]])
        relations = operator.gen_autoguess_constr()
        self.assertIn("y0", closure(relations, ["x0"]))
        self.assertNotIn("x0", closure(relations, ["y0"]))

    def test_noninjective_sbox_only_determines_output(self):
        operator = Sbox(variables("x", 1, 2), variables("y", 1, 2), 2, 2)
        operator.table = [0, 0, 1, 1]
        relations = operator.gen_autoguess_constr(flat_sbox_mode=False)
        self.assertIn("y0", closure(relations, ["x0"]))
        self.assertNotIn("x0", closure(relations, ["y0"]))

    def test_default_form_falls_back_to_implications_for_noninjective_sboxes(self):
        operator = Sbox(variables("x", 1, 2), variables("y", 1, 2), 2, 2)
        operator.table = [0, 0, 1, 1]
        relations = emit_function(tiny_function([operator]))
        self.assertIn("y0", closure(relations, ["x0"]))
        self.assertNotIn("x0", closure(relations, ["y0"]))

    def test_default_form_supports_injective_sboxes_with_unequal_widths(self):
        operator = Sbox(variables("x", 1, 2), variables("y", 1, 3), 2, 3)
        operator.table = [0, 2, 5, 7]
        relations = emit_function(tiny_function([operator]))
        self.assertIn("y0", closure(relations, ["x0"]))
        self.assertIn("x0", closure(relations, ["y0"]))

    def test_permutation_flag_does_not_leak_to_sboxes(self):
        x, y = variables("x", 1, 4), variables("y", 1, 4)
        sbox = Skinny_4bit_Sbox(x, y, ID="SB_1_0_0")
        permutation = Equal(x, y, ID="K_P_EQ_1_1_0")
        relations = emit_function(tiny_function([sbox, permutation]), nonrename_perm=True)
        self.assertIn("x0, y0, NONRENAME", relations)
        self.assertIn("x0, y0, KNOWLEDGE_EQ", relations)

    def test_unsupported_operators_fail_unless_explicitly_skipped(self):
        class Unsupported:
            ID = "op_1_0_0"
        function = tiny_function([Unsupported()])
        with self.assertRaisesRegex(NotImplementedError, "explicitly skip"):
            emit_function(function)
        self.assertEqual(emit_function(function, skip_ops=["Unsupported"]), [])

    def test_public_primitive_variables_have_boundary_links(self):
        a, b, public = [Variable(1, ID=name) for name in ("vs_1_0_0", "vs_1_1_0", "plaintext0")]
        function = tiny_function([Equal([a], [b])])
        cipher = SimpleNamespace(functions={"PERMUTATION": function},
                                 inputs_constraints=[Equal([public], [a])], outputs_constraints=[])
        relations = emit_cipher(cipher)
        self.assertIn(a.ID, closure(relations, [public.ID]))
        self.assertIn(b.ID, closure(relations, [public.ID]))
        self.assertEqual(emit_cipher(cipher, skip_functions=["PERMUTATION"]), [])

    def test_disabled_cleaning_does_not_emit_internal_markers(self):
        function = tiny_function([Skinny_4bit_Sbox(variables("x", 1, 4), variables("y", 1, 4))])
        with tempfile.TemporaryDirectory() as directory:
            relations = generate_relations(function, function_mode=True, enable_cleaning=False,
                                           save_dirty=False, output_file=str(Path(directory) / "relations.txt"))
        self.assertFalse(any("KNOWLEDGE_EQ" in line or "NONRENAME" in line for line in relations))


if __name__ == "__main__":
    unittest.main()
