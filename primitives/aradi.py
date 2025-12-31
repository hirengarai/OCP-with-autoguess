from primitives.primitives import Permutation, Block_cipher
from operators.boolean_operators import XOR, ANDXOR
from operators.operators import ARADI_L32
import variables.variables as var


# Factory for ARADI_L32 so it works with SingleOperatorLayer
def ARADI_L32_ABC(a, b, c):
    class _ARADI_L32_ABC(ARADI_L32):
        def __init__(self, input_vars, output_vars, ID=None):
            super().__init__(input_vars, output_vars, a, b, c, ID=ID)
    _ARADI_L32_ABC.__name__ = f"ARADI_L32_a{a}_b{b}_c{c}"
    return _ARADI_L32_ABC



# The ARADI internal permutation
class ARADI_permutation(Permutation):
    def __init__(self, name, s_input, s_output, nbr_rounds=None, represent_mode=0):
        """
        Initialize the ARADI internal permutation
        :param name: Name of the permutation
        :param version: Bit size of the permutation
        :param s_input: Input state
        :param s_output: Output state
        :param nbr_rounds: Number of rounds
        :param represent_mode: Integer specifying the mode of representation used for encoding the permutation.
        """
        
        if nbr_rounds is None:
            nbr_rounds = 16

        if represent_mode==0: nbr_layers, nbr_words, nbr_temp_words, word_bitsize = (5, 4, 0, 32) 

        super().__init__(
            name,
            s_input,
            s_output,
            nbr_rounds,
            [nbr_layers, nbr_words, nbr_temp_words, word_bitsize]
        )

        S = self.functions["PERMUTATION"]

        a_tab = [11, 10, 9, 8]
        b_tab = [8, 9, 4, 9]
        c_tab = [14, 11, 14, 7]
        if represent_mode==0:
            for i in range(1, nbr_rounds + 1):
                r = i - 1
                j = r % 4

                # --- S-box ---
                S.SingleOperatorLayer("AX", i, 0, ANDXOR, [[0, 2, 1]], [1])
                S.SingleOperatorLayer("AX", i, 1, ANDXOR, [[1, 2, 3]], [3])
                S.SingleOperatorLayer("AX", i, 2, ANDXOR, [[0, 3, 2]], [2])
                S.SingleOperatorLayer("AX", i, 3, ANDXOR, [[1, 3, 0]], [0])

                # --- Linear layer ---
                Lop = ARADI_L32_ABC(a_tab[j], b_tab[j], c_tab[j])
                S.SingleOperatorLayer(
                    "L",
                    i,
                    4,
                    Lop,
                    [[0], [1], [2], [3]],
                    [0, 1, 2, 3]
                )


def ARADI_PERMUTATION(r= None, represent_mode=0):
    
    my_input, my_output = [var.Variable(32, ID=f"in{i}")  for i in range(4)], [var.Variable(32, ID=f"out{i}") for i in range(4)]
    return ARADI_permutation("ARADI_PERM", my_input, my_output, nbr_rounds=r, represent_mode=represent_mode)



# The ARADI block cipher
class ARADI_block_cipher(Block_cipher):
    def __init__(self, name, version, p_input, k_input, c_output, nbr_rounds=None, represent_mode=0):
        """
        Initializes the ARADI block cipher.
        :param name: Cipher name
        :param version: (p_bitsize, k_bitsize), e.g., (128, 256)
        :param p_input: Plaintext input
        :param k_input: Key input
        :param c_output: Ciphertext output
        :param nbr_rounds: Number of rounds (optional)
        :param represent_mode: Integer specifying the mode of representation used for encoding the cipher.
        """

        assert version in [[128,256]], f"Unsupported version: {version}."
        if nbr_rounds is None:
            nbr_rounds = 16
        
        
        nbr_rounds += 1     
        k_nbr_rounds = nbr_rounds

        s_settings  = [6, 4, 0, 32]
        k_settings  = [6, 8, 0, 32]
        sk_settings = [1, 4, 0, 32]

        super().__init__(
            name,
            p_input,
            k_input,
            c_output,
            nbr_rounds,
            k_nbr_rounds,
            s_settings,
            k_settings,
            sk_settings
        )

        S  = self.functions["PERMUTATION"]
        KS = self.functions["KEY_SCHEDULE"]
        SK = self.functions["SUBKEYS"]

        a_tab = [11, 10, 9, 8]
        b_tab = [8, 9, 4, 9]
        c_tab = [14, 11, 14, 7]

        # subkeys extraction
        for i in range(1, k_nbr_rounds):
            base = 4* ((i - 1) & 1)
            SK.ExtractionLayer(
                "SK_EX",
                i,
                0,
                [0, 1, 2, 3],
                KS.vars[i][0][base:base + 4]
            )

        # Whitening key
        base = 4* ((k_nbr_rounds-1) & 1)
        SK.ExtractionLayer(
            "SK_EX",
            k_nbr_rounds,
            0,
            [0, 1, 2, 3],
            KS.vars[k_nbr_rounds][0][base: base+4]
        )

        # ---- build constant table ONCE (outside the loop) ----
        constant_table = [[rr] for rr in range(k_nbr_rounds)]

        # key schedule
        for i in range(1, k_nbr_rounds):
            r = i - 1
            
            KS.RotationLayer("K_R", i, 0,[['l', 1, 0, 0], ['l', 9, 2, 2], ['l', 1, 4, 4], ['l', 9, 6, 6]])
            
            KS.SingleOperatorLayer("K_X",i,1,XOR,[[0,1],[2,3],[4,5],[6,7]],[[0],[2],[4],[6]])
            
            KS.RotationLayer("K_R",i, 2, [['l', 3,1,1], ['l', 28, 3,3], ['l', 3,5,5], ['l', 28, 7,7]])
            
            KS.SingleOperatorLayer("K_X",i,3,XOR,[[0,1],[2,3],[4,5],[6,7]],[[1],[3],[5],[7]])

            # Round constant: only word 7 gets XOR with r (match your earlier convention)
            KS.AddConstantLayer(
                "K_C",
                i, 4,
                "xor",
                [None]*7+[True],
                constant_table
            )

            # Permutation (keep your same perms)
            if r & 1:
                perm = [0, 4, 2, 6, 1, 5, 3, 7]
            else:
                perm = [0, 2, 1, 3, 4, 6, 5, 7]

            KS.PermutationLayer("K_P", i, 5, perm)
            
        # Internal permutation
        for i in range(1, nbr_rounds):
            r = i - 1
            j = r % 4

            S.AddRoundKeyLayer("ARK", i, 0, XOR, SK, mask=[1, 1, 1, 1])

            S.SingleOperatorLayer("AX", i, 1, ANDXOR, [[0, 2, 1]], [1])
            S.SingleOperatorLayer("AX", i, 2, ANDXOR, [[1, 2, 3]], [3])
            S.SingleOperatorLayer("AX", i, 3, ANDXOR, [[0, 3, 2]], [2])
            S.SingleOperatorLayer("AX", i, 4, ANDXOR, [[1, 3, 0]], [0])

            Lop = ARADI_L32_ABC(a_tab[j], b_tab[j], c_tab[j])
            S.SingleOperatorLayer("L", i, 5, Lop, [[0], [1], [2], [3]], [0, 1, 2, 3])
            

        # --- final whitening ---
        S.AddRoundKeyLayer("ARK", k_nbr_rounds, 0, XOR, SK, mask=[1, 1, 1, 1])
        for L in range(1, s_settings[0]):
            S.AddIdentityLayer("ID", nbr_rounds, L)

        self.test_vectors = self.gen_test_vectors(version)

    
    # Test vectors for ARADI from https://eprint.iacr.org/2024/1240.pdf
    def gen_test_vectors(self, version):
        if version == [128, 256]:
            plaintext  = [0x00000000, 0x00000000, 0x00000000, 0x00000000]
            key = [
                0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c
            ]
            ciphertext = [0x3f09abf4, 0x00e3bd74, 0x03260def, 0xb7c53912]
        else:
            raise ValueError("Unsupported ARADI version")

        return [[plaintext, key], ciphertext]


def ARADI_BLOCKCIPHER(r=None, version=[128, 256]):
    pt = [var.Variable(32, ID=f"in{i}")  for i in range(4)]
    k  = [var.Variable(32, ID=f"k{i}")   for i in range(8)]
    ct = [var.Variable(32, ID=f"out{i}") for i in range(4)]
    return ARADI_block_cipher("ARADI128_256", version, pt, k, ct, nbr_rounds=r)