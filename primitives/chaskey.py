from primitives.primitives import Permutation
from operators.boolean_operators import XOR
from operators.modular_operators import ModAdd
import variables.variables as var


# The Chaskey internal permutation
class Chaskey_permutation(Permutation):
    def __init__(self, name, s_input, s_output, nbr_rounds=None, represent_mode=0):
        """
        Initialize the Chaskey internal permutation
        :param name: Name of the permutation
        :param s_input: Input state
        :param s_output: Output state
        :param nbr_rounds: Number of rounds
        :param represent_mode: Integer specifying the mode of representation used for encoding the permutation.
        """
        if nbr_rounds is None: nbr_rounds = 8   # default to Chaskey-8; Chaskey-LTS uses 12
        nbr_layers = 10
        nbr_words = 4
        nbr_temp_words = 0
        word_bitsize = 32
        super().__init__(name, s_input, s_output, nbr_rounds, [nbr_layers, nbr_words, nbr_temp_words, word_bitsize])
        S = self.functions["PERMUTATION"]

        # create constraints
        if represent_mode==0:
            for i in range(1,nbr_rounds+1):  
                S.SingleOperatorLayer("ADD1", i, 0, ModAdd, [[0,1], [2,3]], [0, 2]) # Modular addition layer
                S.RotationLayer("ROT1", i, 1, [['l', 5, 1], ['l', 8, 3]]) # Rotation layer
                S.SingleOperatorLayer("XOR1", i, 2, XOR, [[0,1], [2,3]], [1, 3]) # XOR layer
                S.RotationLayer("ROT2", i, 3, [['l', 16, 0]]) # Rotation layer
                S.PermutationLayer("PERM1", i, 4, [2,1,0,3]) # Permutation layer
                S.SingleOperatorLayer("ADD2", i, 5, ModAdd, [[0,1], [2,3]], [0, 2]) # Modular addition layer
                S.RotationLayer("ROT3", i, 6, [['l', 7, 1], ['l', 13, 3]]) # Rotation layer
                S.SingleOperatorLayer("XOR2", i, 7, XOR, [[0,1], [2,3]], [1, 3]) # XOR layer
                S.RotationLayer("ROT4", i, 8, [['l', 16, 0]]) # Rotation layer
                S.PermutationLayer("PERM2", i, 9, [2,1,0,3]) # Permutation layer

    def gen_test_vectors(self):
        # π-only test vectors: arbitrary input, outputs computed from the spec
        # round function (Mouha et al., SAC 2014, Sec. 3) for r=8 (Chaskey) and
        # r=12 (Chaskey-LTS). These are NOT the reference C MAC tags -- those
        # depend on the key, the subkeys K1/K2 and the padding, so they are not
        # comparable to the bare permutation.
        # Ref: https://mouha.be/chaskey/
        IN = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
        OUT_BY_ROUNDS = {
            8:  [0xd5553d2f, 0xb79dab7e, 0x126887ad, 0xb87a8189],
            12: [0x6500f8ff, 0xa54ac3b5, 0xeb5f3dab, 0x873fc95d],
        }
        if self.nbr_rounds in OUT_BY_ROUNDS:
            self.test_vectors.append([[IN], OUT_BY_ROUNDS[self.nbr_rounds]])


def CHASKEY_PERMUTATION(r=None, represent_mode=0, copy_operator=False):
    my_input  = [var.Variable(32, ID="in"+str(i))  for i in range(4)]
    my_output = [var.Variable(32, ID="out"+str(i)) for i in range(4)]
    my_permutation = Chaskey_permutation("Chaskey_PERM", my_input, my_output,
                                          nbr_rounds=r, represent_mode=represent_mode)
    my_permutation.gen_test_vectors()
    my_permutation.post_initialization(copy_operator=copy_operator)
    return my_permutation