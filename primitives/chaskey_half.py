from primitives.primitives import Permutation
from operators.boolean_operators import XOR
from operators.modular_operators import ModAdd
import variables.variables as var
import math


class Chaskey_permutation(Permutation):
    def __init__(self, name, s_input, s_output,
                 chaskey_rounds,  # can be 0.5, 1.0, 1.5, ...
                 represent_mode=0):

        """
        chaskey_rounds: logical number of Chaskey rounds (can be k or k+0.5)
                        1 round = 2 half-rounds.
        """

        if chaskey_rounds is None:
            raise ValueError("chaskey_rounds must be specified")

        # Number of half-rounds (integer)
        # e.g. 1.0 -> 2, 0.5 -> 1, 7.5 -> 15
        half_rounds = int(round(2 * chaskey_rounds))
        if half_rounds <= 0:
            raise ValueError("chaskey_rounds must be > 0")

        # Number of integer 'rounds' for the framework
        physical_rounds = math.ceil(chaskey_rounds)

        nbr_layers = 10          # maximum layers per framework round
        nbr_words = 4
        nbr_temp_words = 0
        word_bitsize = 32

        super().__init__(
            name,
            s_input,
            s_output,
            physical_rounds,
            [nbr_layers, nbr_words, nbr_temp_words, word_bitsize]
        )

        S = self.functions["PERMUTATION"]

        if represent_mode == 0:
            # h = how many half-rounds we have instantiated so far
            h = 0
            for i in range(1, physical_rounds + 1):
                # ---- first half of round i: ADD1..PERM1 ----
                if h < half_rounds:
                    S.SingleOperatorLayer("ADD1", i, 0, ModAdd, [[0, 1], [2, 3]], [0, 2])
                    S.RotationLayer("ROT1", i, 1, [['l', 5, 1], ['l', 8, 3]])
                    S.SingleOperatorLayer("XOR1", i, 2, XOR, [[0, 1], [2, 3]], [1, 3])
                    S.RotationLayer("ROT2", i, 3, [['l', 16, 0]])
                    S.PermutationLayer("PERM1", i, 4, [2, 1, 0, 3])
                    h += 1

                # ---- second half of round i: ADD2..PERM2 ----
                if h < half_rounds:
                    S.SingleOperatorLayer("ADD2", i, 5, ModAdd, [[0, 1], [2, 3]], [0, 2])
                    S.RotationLayer("ROT3", i, 6, [['l', 7, 1], ['l', 13, 3]])
                    S.SingleOperatorLayer("XOR2", i, 7, XOR, [[0, 1], [2, 3]], [1, 3])
                    S.RotationLayer("ROT4", i, 8, [['l', 16, 0]])
                    S.PermutationLayer("PERM2", i, 9, [2, 1, 0, 3])
                    h += 1

        self.test_vectors = self.gen_test_vectors()

    def gen_test_vectors(self):
        # These are for the full Chaskey permutation with the
        # original number of rounds (you’ll need to match chaskey_rounds).
        IN = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
        OUT = [0x6500f8ff, 0xa54ac3b5, 0xeb5f3dab, 0x873fc95d]
        return [[IN], OUT]
    
    
def CHASKEY_PERMUTATION(r, represent_mode=0):
    """
    r: logical Chaskey rounds; can be:
       1    -> 1 full round  (2 halves)
       0.5  -> half round    (1 half)
       7.5  -> 7.5 rounds    (15 halves)
    """

    # Sanity: only multiples of 0.5
    if (2 * r) % 1 != 0:
        raise ValueError("r must be a multiple of 0.5")

    my_input = [var.Variable(32, ID=f"in{i}") for i in range(4)]
    my_output = [var.Variable(32, ID=f"out{i}") for i in range(4)]

    my_permutation = Chaskey_permutation(
        "Chaskey_half_PERM",
        my_input,
        my_output,
        chaskey_rounds=r,
        represent_mode=represent_mode,
    )
    return my_permutation