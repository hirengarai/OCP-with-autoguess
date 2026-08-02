from abc import ABC, abstractmethod
from tools.model_constraints import gen_xor_constraints, gen_word_xor_constraints, gen_nxor_constraints, gen_word_nxor_constraints


def RaiseExceptionVersionNotExisting(class_name, model_version, model_type):
    raise Exception(class_name + ": version " + str(model_version) + " not existing for " + model_type)


# ********************* OPERATORS ********************* #
# Class that represents a constraint/operator object, i.e. a type of node in our graph modeling (the other type being the variables)
# An Operator/Constraint node can only be linked to a Variable node in the graph representation
# Operators/Constraints are relationships between a group of variables

class Operator(ABC):
    def __init__(self, input_vars, output_vars, model_version=None, ID=None):
        self.input_vars = input_vars        # input variables of that operator
        self.output_vars = output_vars      # output variables of that operator
        self.model_version = model_version  # model version that will be used for that operator
        self.ID = ID                        # ID of the operator
        self.is_ghost = False               # indicates whether that operator is a ghost operator (i.e., an operator that has been marked as ghost during the dead-end removal process)

        # For this new operator created, update the connected_vars list for each input and output variables
        if self.__class__.__name__!="NoneOperator":
            for var_in in input_vars:
                for var_out in output_vars:
                    var_in.connected_vars.append((var_out,self,'in'))
                    var_out.connected_vars.append((var_in,self,'out'))

    def display(self):
        print("ID: ", self.ID)

        print("Input:")
        for i in range(len(self.input_vars)):
            if not isinstance(self.input_vars[i], list):
                self.input_vars[i].display()
            else:
                for j in range(len(self.input_vars[i])):
                    self.input_vars[i][j].display()

        print("Output:")
        for i in range(len(self.output_vars)):
            if not isinstance(self.output_vars[i], list):
                self.output_vars[i].display()
            else:
                for j in range(len(self.output_vars[i])):
                    self.output_vars[i][j].display()
        return self.__class__.__name__

    # obtain the ID of the variable located at "index" of input or output (in_out) for that operator. Compresses the ID if unroll is False
    def get_var_ID(self, in_out, index, unroll=False):
        if in_out == 'out':
            return self.output_vars[index].ID if unroll else self.output_vars[index].remove_round_from_ID()
        elif in_out == 'in':
            return self.input_vars[index].ID if unroll else self.input_vars[index].remove_round_from_ID()
        else:
            raise Exception(str(self.__class__.__name__) + ": unknown in_out type '" + in_out + "'")

    def get_header_ID(self):
        return [self.__class__.__name__, self.model_version]

    def generate_implementation_header(self, implementation_type='python'):    # generic method that generates the code for the header of the modeling of that operator
        return None

    # method that returns the ID of the variable located at "index" of either the input or output of the operator, with options for bitwise listing and dimension unrolling
    def get_var_model(self, in_out, index, bitwise=True, dim=1):
        var = self.input_vars[index] if in_out == 'in' else self.output_vars[index]
        if bitwise and var.bitsize > 1:
            return [f"{var.ID}_{i}_{j}" for i in range(var.bitsize) for j in range(dim)] if dim > 1 else [f"{var.ID}_{i}" for i in range(var.bitsize)]
        else:
            return [f"{var.ID}_{j}" for j in range(dim)] if dim > 1 else [f"{var.ID}"]

    @abstractmethod
    def generate_implementation(self, implementation_type='python'):  # generic method (abstract) that generates the code for the implementation of that operator
        pass

    @abstractmethod
    def generate_model(self, model_type='python'):  # generic method (abstract) that generates the code for the modeling of that operator
        pass


class CastingOperator(Operator):    # Operator for casting from on type to another
    def __init__(self, input_vars, output_vars, ID = None):
        if sum([input_vars[i].bitsize for i in range(len(input_vars))]) != sum([output_vars[i].bitsize for i in range(len(output_vars))]): raise Exception("CastingOperator: the total input size does not match the total output size")
        super().__init__(input_vars, output_vars, ID = ID)
        pass   # TODO


class CastingWordtoBitVector(CastingOperator):   # Operator for casting a bit word to a vector of bits
    def __init__(self, input_vars, output_vars, ID = None):
        pass   # TODO


class UnaryOperator(Operator):   # Generic operator taking one input and one output (must be of same bitsize)
    def __init__(self, input_vars, output_vars, ID = None):
        if len(input_vars) != 1: raise Exception(str(self.__class__.__name__) + ": your input does not contain exactly 1 element")
        if len(output_vars) != 1: raise Exception(str(self.__class__.__name__) + ": your output does not contain exactly 1 element")
        # if input_vars[0].bitsize != output_vars[0].bitsize: raise Exception(str(self.__class__.__name__) + ": your input and output sizes do not match") zcn: can be removed because the input size and output size of sbox may be different
        super().__init__(input_vars, output_vars, ID = ID)


class BinaryOperator(Operator):   # Generic operator taking two inputs and one output (must be of same bitsize)
    def __init__(self, input_vars, output_vars, ID = None):
        if len(input_vars) != 2: raise Exception(str(self.__class__.__name__) + ": your input does not contain exactly 2 element")
        if len(output_vars) != 1: raise Exception(str(self.__class__.__name__) + ": your output does not contain exactly 1 element")
        if input_vars[0].bitsize != input_vars[1].bitsize: raise Exception(str(self.__class__.__name__) + ": your inputs sizes do not match")
        if input_vars[0].bitsize != output_vars[0].bitsize: raise Exception(str(self.__class__.__name__) + ": your input and output sizes do not match")
        super().__init__(input_vars, output_vars, ID = ID)


class NoneOperator(Operator):  # Ghost Operator, does nothing (just a placeholder)
    def __init__(self, input_vars, output_vars, ID = None):
        super().__init__(input_vars, output_vars, ID = ID)

    def generate_implementation(self, implementation_type='python', unroll=False):
        return []

    def generate_model(self, model_type='sat'):
        return []


class CopyOperator(Operator):  # Operator that duplicates one input into multiple outputs: b_0, b_1, ..., b_n = a
    def __init__(self, input_vars, output_vars, ID = None):
        if len(input_vars) != 1:
            raise Exception(f"{self.__class__.__name__}: your input does not contain exactly 1 element")
        if len(output_vars) < 2:
            raise Exception(f"{self.__class__.__name__}: your output must contain at least 2 element")
        super().__init__(input_vars, output_vars, ID=ID)

    def generate_implementation(self, implementation_type='python', unroll=False):
        in_id = self.get_var_ID('in', 0, unroll)
        if implementation_type == 'python':
            return [f"{self.get_var_ID('out', j, unroll)} = {in_id}" for j in range(len(self.output_vars))]
        elif implementation_type == 'c':
            return [f"{self.get_var_ID('out', j, unroll)} = {in_id};" for j in range(len(self.output_vars))]
        elif implementation_type == 'verilog':
            return [f"assign {self.get_var_ID('out', j, unroll)} = {in_id};" for j in range(len(self.output_vars))]
        else:
            raise Exception(f"{self.__class__.__name__}: unknown implementation type '{implementation_type}'")

    def generate_model(self, model_type='sat'):
        model_list = []
        if model_type in ['sat', 'milp']:
            # Modeling for differential cryptanalysis
            if model_type == "sat" and self.model_version in [self.__class__.__name__ + "_XORDIFF"]:
                var_in, var_out = (self.get_var_model("in", 0), [self.get_var_model("out", i) for i in range(len(self.output_vars))])
                for i in range(self.input_vars[0].bitsize):
                    for j in range(len(var_out)):
                        model_list += [f"{var_out[j][i]} -{var_in[i]}", f"-{var_out[j][i]} {var_in[i]}"]
                return model_list
            elif model_type == "milp" and self.model_version in [self.__class__.__name__ + "_XORDIFF"]:
                var_in, var_out = (self.get_var_model("in", 0), [self.get_var_model("out", i) for i in range(len(self.output_vars))])
                for i in range(self.output_vars[0].bitsize):
                    for j in range(len(var_out)):
                        model_list += [f"{var_out[j][i]} - {var_in[i]} = 0"]
                model_list.append('Binary\n' + ' '.join(var_in + sum(var_out, [])))
                return model_list
            # Modeling for truncated differential cryptanalysis
            elif model_type == "sat" and self.model_version == self.__class__.__name__ + "_TRUNCATEDDIFF":
                var_in, var_out = (self.get_var_model("in", 0, bitwise=False), [self.get_var_model("out", i, bitwise=False) for i in range(len(self.output_vars))])
                for j in range(len(var_out)):
                    model_list += [f'{var_in[0]} -{var_out[j][0]}', f'-{var_in[0]} {var_out[j][0]}']
                return model_list
            elif model_type == "milp" and self.model_version == self.__class__.__name__ + "_TRUNCATEDDIFF":
                var_in, var_out = (self.get_var_model("in", 0, bitwise=False), [self.get_var_model("out", i, bitwise=False) for i in range(len(self.output_vars))])
                for j in range(len(var_out)):
                    model_list += [f"{var_out[j][0]} - {var_in[0]} = 0"]
                model_list.append('Binary\n' + ' '.join(var_in + sum(var_out, [])))
                return model_list
            # Modeling for linear cryptanalysis
            elif self.model_version == self.__class__.__name__ + "_LINEAR":
                var_in, var_out = (self.get_var_model("in", 0), [self.get_var_model("out", i) for i in range(len(self.output_vars))])
                if len(var_out) == 2: # Two outputs: out1, out2 = in
                    for i in range(self.input_vars[0].bitsize):
                        model_list.extend(gen_xor_constraints(var_in[i], var_out[0][i], var_out[1][i], model_type))
                elif len(var_out) >= 3: # n outputs: out1, out2, ..., outn = in
                    for i in range(self.input_vars[0].bitsize):
                        if model_type == 'milp':
                            v_dummy = f"{self.ID}_d_{i}"
                        else:
                            v_dummy = None
                        model_list.extend(gen_nxor_constraints([var_out[j][i] for j in range(len(var_out))], var_in[i], model_type=model_type, v_dummy=v_dummy))
                return model_list
            # Modeling for integral cryptanalysis
            elif model_type == "milp" and self.model_version == self.__class__.__name__ + "_INTEGRAL_TWOSUBSET":
                var_in, var_out = (self.get_var_model("in", 0), [self.get_var_model("out", i) for i in range(len(self.output_vars))])
                for i in range(self.input_vars[0].bitsize):
                    model_list += [f"{var_in[i]} - " + " - ".join(var_out[j][i] for j in range(len(var_out))) + " = 0"]
                model_list.append('Binary\n' + ' '.join(var_in + sum(var_out, [])))
                return model_list
            # Modeling for truncated linear cryptanalysis
            elif len(self.output_vars) == 2 and self.model_version == self.__class__.__name__ + "_TRUNCATEDLINEAR":
                var_in, var_out1, var_out2 = (self.get_var_model("in", 0, bitwise=False),  self.get_var_model("out", 0, bitwise=False), self.get_var_model("out", 1, bitwise=False))
                model_list.extend(gen_word_xor_constraints(var_out1[0], var_out2[0], var_in[0], model_type))
                return model_list
            elif len(self.output_vars) >= 3 and model_type == "milp" and self.model_version == self.__class__.__name__ + "_TRUNCATEDLINEAR":
                var_in, var_out = (self.get_var_model("in", 0, bitwise=False), [self.get_var_model("out", i, bitwise=False) for i in range(len(self.output_vars))])
                model_list.extend(gen_word_nxor_constraints([var_out[j][0] for j in range(len(var_out))], var_in[0], model_type))
                return model_list
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'cp': RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        else: raise Exception(str(self.__class__.__name__) + ": unknown model type '" + model_type + "'")



class Equal(UnaryOperator):  # Operator assigning equality between the input variable and output variable (must be of same bitsize)
    def __init__(self, input_vars, output_vars, ID = None):
        super().__init__(input_vars, output_vars, ID = ID)

    def generate_implementation(self, implementation_type='python', unroll=False):
        if implementation_type == 'python':
            return [self.get_var_ID('out', 0, unroll) + ' = ' + self.get_var_ID('in', 0, unroll)]
        elif implementation_type == 'c':
            return [self.get_var_ID('out', 0, unroll) + ' = ' + self.get_var_ID('in', 0, unroll) + ';']
        elif implementation_type == 'verilog':
            return ["assign " + self.get_var_ID('out', 0, unroll) + ' = ' + self.get_var_ID('in', 0, unroll) + ';']
        else: raise Exception(str(self.__class__.__name__) + ": unknown implementation type '" + implementation_type + "'")

    def generate_model(self, model_type='sat'):
        if model_type == 'sat':
            if self.model_version in [self.__class__.__name__ + "_XORDIFF", self.__class__.__name__ + "_LINEAR"]:
                var_in, var_out = (self.get_var_model("in", 0), self.get_var_model("out", 0))
                return [clause for vin, vout in zip(var_in, var_out) for clause in (f"-{vin} {vout}", f"{vin} -{vout}")]
            elif self.model_version in [self.__class__.__name__ + "_TRUNCATEDDIFF", self.__class__.__name__ + "_TRUNCATEDLINEAR"]:
                var_in, var_out = (self.get_var_model("in", 0, bitwise=False), self.get_var_model("out", 0, bitwise=False))
                return [f"-{var_in[0]} {var_out[0]}", f"{var_in[0]} -{var_out[0]}"]
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'milp':
            if self.model_version in [self.__class__.__name__ + "_XORDIFF", self.__class__.__name__ + "_LINEAR", self.__class__.__name__ + "_INTEGRAL_TWOSUBSET"]:
                var_in, var_out = (self.get_var_model("in", 0), self.get_var_model("out", 0))
                model_list = [f"{vin} - {vout} = 0" for vin, vout in zip(var_in, var_out)]
                model_list.append('Binary\n' +  ' '.join(v for v in var_in + var_out))
                return model_list
            elif self.model_version in [self.__class__.__name__ + "_TRUNCATEDDIFF", self.__class__.__name__ + "_TRUNCATEDLINEAR"]:
                var_in, var_out = (self.get_var_model("in", 0, bitwise=False), self.get_var_model("out", 0, bitwise=False))
                model_list = [f"{var_in[0]} - {var_out[0]} = 0"]
                model_list.append('Binary\n' +  ' '.join(v for v in var_in + var_out))
                return model_list
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'cp': RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        else: raise Exception(str(self.__class__.__name__) + ": unknown model type '" + model_type + "'")
        
    def gen_autoguess_constr(self, *, algebraic_mode=False, treat_as_nonrename=False):
        """
        Generate Autoguess-style constraints for Equal operation.
        - algebraic_mode=False (default): connection relation "a, b"
        - algebraic_mode=True:             algebraic relation   "a + b"
        - treat_as_nonrename=True appends ", NONRENAME" to connection lines so
          the cleaner does not collapse them. Has no effect when algebraic_mode
          is True (algebraic relations are not renames in the first place).

        Supports:
        - Single input to single output: a = b
        - Multiple inputs to multiple outputs: generates pairwise equality constraints

        Configuration errors (empty/mismatched wiring, missing ``input_vars`` /
        ``output_vars``) raise rather than returning ``# ...`` comment lines —
        downstream stages strip ``#``-prefixed lines, so silent emission of
        them would make real bugs invisible.
        """

        def _flatten(vars_):
            for v in vars_:
                if isinstance(v, (list, tuple)):
                    for u in v:
                        yield u
                else:
                    yield v

        opid = getattr(self, 'ID', '?')
        in_vars = [v.ID for v in _flatten(self.input_vars)]
        out_vars = [v.ID for v in _flatten(self.output_vars)]

        if not in_vars or not out_vars:
            raise ValueError(
                f"Equal {opid}: empty inputs or outputs "
                f"(in={len(in_vars)}, out={len(out_vars)})"
            )

        if len(in_vars) != len(out_vars):
            raise ValueError(
                f"Equal {opid}: mismatched dimensions "
                f"{len(in_vars)} inputs vs {len(out_vars)} outputs"
            )

        constraints = []
        for a, b in zip(in_vars, out_vars):
            if algebraic_mode:
                constraints.append(f"{a} + {b}")
            elif treat_as_nonrename:
                constraints.append(f"{a}, {b}, NONRENAME")
            else:
                constraints.append(f"{a}, {b}")
        return constraints


class Rot(UnaryOperator):     # Operator for the rotation function: rotation of the input variable to the output variable with "direction" ('l' or 'r') and "amount" of bits
    def __init__(self, input_vars, output_vars, direction, amount, ID = None):
        super().__init__(input_vars, output_vars, ID = ID)
        if direction!='l' and direction!='r': raise Exception(str(self.__class__.__name__) + ": unknown direction value")
        self.direction = direction
        if amount<=0 or amount>= input_vars[0].bitsize: raise Exception(str(self.__class__.__name__) + ": wrong amount value")
        self.amount = amount

    def generate_implementation(self, implementation_type='python', unroll=False):
        if implementation_type == 'python':
            if self.direction == 'r': return [self.get_var_ID('out', 0, unroll) + ' = ROTR(' + self.get_var_ID('in', 0, unroll) + ', ' + str(self.amount) + ', ' + str(self.input_vars[0].bitsize) + ')']
            else: return [self.get_var_ID('out', 0, unroll) + ' = ROTL(' + self.get_var_ID('in', 0, unroll) + ', ' + str(self.amount) + ', ' + str(self.input_vars[0].bitsize) + ')']
        elif implementation_type == 'c':
            if self.direction == 'r': return [self.get_var_ID('out', 0, unroll) + ' = ROTR(' + self.get_var_ID('in', 0, unroll) + ', ' + str(self.amount) + ', ' + str(self.input_vars[0].bitsize) + ');']
            else: return [self.get_var_ID('out', 0, unroll) + ' = ROTL(' + self.get_var_ID('in', 0, unroll) + ', ' + str(self.amount) + ', ' + str(self.input_vars[0].bitsize) + ');']
        elif implementation_type == 'verilog':
            if self.direction == 'r': return ["assign " + self.get_var_ID('out', 0, unroll) + ' = `ROTR(' + self.get_var_ID('in', 0, unroll) + ', ' + str(self.amount) + ', ' + str(self.input_vars[0].bitsize) + ');']
            else: return ["assign " + self.get_var_ID('out', 0, unroll) + ' = `ROTL(' + self.get_var_ID('in', 0, unroll) + ', ' + str(self.amount) + ', ' + str(self.input_vars[0].bitsize) + ');']
        else: raise Exception(str(self.__class__.__name__) + ": unknown implementation type '" + implementation_type + "'")

    def generate_implementation_header_unique(self, implementation_type='python'):
        if implementation_type == 'python':
            return ["#Rotation Macros ", "def ROTL(n, d, bitsize): return ((n << d) | (n >> (bitsize - d))) & (2**bitsize - 1)", "def ROTR(n, d, bitsize): return ((n >> d) | (n << (bitsize - d))) & (2**bitsize - 1)"]
        elif implementation_type == 'c':
            if self.input_vars[0].bitsize < 32:
                return ["//Rotation Macros", "#define ROTL(n, d, bitsize) (((n << d) | (n >> (bitsize - d))) & ((1<<bitsize) - 1)) ", "#define ROTR(n, d, bitsize) (((n >> d) | (n << (bitsize - d))) & ((1<<bitsize) - 1))"]
            elif 32 <= self.input_vars[0].bitsize < 64:
                return ["//Rotation Macros", "#define ROTL(n, d, bitsize) (((n << d) | (n >> ((unsigned long long)(bitsize) - d))) & ((1ULL << (bitsize)) - 1))", "#define ROTR(n, d, bitsize) (((n >> d) | (n << ((unsigned long long)(bitsize) - d))) & ((1ULL << (bitsize)) - 1))"]
            else:
                return ["//Rotation Macros", "#define ROTL(n, d, bitsize) (((n << d) | (n >> ((__uint128_t)(bitsize) - d))) & (((__uint128_t)1 << (bitsize)) - 1))", "#define ROTR(n, d, bitsize) (((n >> d) | (n << ((__uint128_t)(bitsize) - d))) & (((__uint128_t)1 << (bitsize)) - 1))"]
        elif implementation_type == 'verilog':
            return ["//Rotation Macros", "`define ROTL(n, d, bitsize) {n[bitsize-1-d:0],n[bitsize-1:bitsize-d]}", "`define ROTR(n, d, bitsize) {n[d-1:0],n[bitsize-1:d]}"]
        else: return None

    def generate_model(self, model_type='sat'):
        if model_type == 'sat':
            var_in, var_out = (self.get_var_model("in", 0), self.get_var_model("out", 0))
            if (self.direction =='r' and self.model_version in [self.__class__.__name__ + "_XORDIFF", self.__class__.__name__ + "_LINEAR"]):
                return [clause for i in range(len(var_in)) for clause in (f"-{var_in[i]} {var_out[(i+self.amount)%len(var_in)]}", f"{var_in[i]} -{var_out[(i+self.amount)%len(var_in)]}")]
            elif (self.direction =='l' and self.model_version in [self.__class__.__name__ + "_XORDIFF", self.__class__.__name__ + "_LINEAR"]):
                return [clause for i in range(len(var_in)) for clause in (f"-{var_in[(i+self.amount)%len(var_in)]} {var_out[i]}", f"{var_in[(i+self.amount)%len(var_in)]} -{var_out[i]}")]
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'milp':
            var_in, var_out = (self.get_var_model("in", 0), self.get_var_model("out", 0))
            if (self.direction == 'r' and self.model_version in [self.__class__.__name__ + "_XORDIFF", self.__class__.__name__ + "_LINEAR", self.__class__.__name__ + "_INTEGRAL_TWOSUBSET"]):
                model_list = [f'{var_in[i]} - {var_out[(i + self.amount) % len(var_in)]} = 0' for i in range(len(var_in))]
                model_list.append('Binary\n' +  ' '.join(v for v in var_in + var_out))
                return model_list
            elif (self.direction =='l' and self.model_version in [self.__class__.__name__ + "_XORDIFF", self.__class__.__name__ + "_LINEAR", self.__class__.__name__ + "_INTEGRAL_TWOSUBSET"]):
                model_list = [f'{var_in[(i+self.amount)%len(var_in)]} - {var_out[i]} = 0' for i in range(len(var_in))]
                model_list.append('Binary\n' +  ' '.join(v for v in var_in + var_out))
                return  model_list
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'cp': RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        else: raise Exception(str(self.__class__.__name__) + ": unknown model type '" + model_type + "'")
        
    def gen_autoguess_constr(self, *, treat_as_nonrename=False):
        """
        Generate Autoguess-style constraints for Rotation operation.
        Emits pairwise connection relations for bit-wise rotation.

        For rotation by r positions: input bit i maps to output bit (i+r) % n.
        Generates n constraints connecting each input bit to its rotated output bit.

        treat_as_nonrename=True appends ", NONRENAME" so the cleaner does not
        collapse the bit pairs (use this when you want the rotation kept as a
        real relation in the cleaned output).

        Configuration errors raise; see :meth:`Equal.gen_autoguess_constr` for
        rationale.
        """

        def _flatten(vars_):
            for v in vars_:
                if isinstance(v, (list, tuple)):
                    yield from v
                else:
                    yield v

        opid = getattr(self, 'ID', '?')
        in_vars = [v.ID for v in _flatten(self.input_vars)]
        out_vars = [v.ID for v in _flatten(self.output_vars)]

        if not in_vars or not out_vars:
            raise ValueError(
                f"Rotation {opid}: empty inputs or outputs "
                f"(in={len(in_vars)}, out={len(out_vars)})"
            )

        if len(in_vars) != len(out_vars):
            raise ValueError(
                f"Rotation {opid}: mismatched dimensions "
                f"{len(in_vars)} inputs vs {len(out_vars)} outputs"
            )

        suffix = ", NONRENAME" if treat_as_nonrename else ""
        return [f"{in_bit}, {out_bit}{suffix}" for in_bit, out_bit in zip(in_vars, out_vars)]


class Shift(UnaryOperator):    # Operator for the shift function: shift of the input variable to the output variable with "direction" ('l' or 'r') and "amount" of bits
    def __init__(self, input_vars, output_vars, direction, amount, ID = None):
        super().__init__(input_vars, output_vars, ID = ID)
        if direction!='l' and direction!='r': raise Exception(str(self.__class__.__name__) + ": unknown direction value")
        self.direction = direction
        if amount<=0 or amount>= input_vars[0].bitsize: raise Exception(str(self.__class__.__name__) + ": wrong amount value")
        self.amount = amount

    def generate_implementation(self, implementation_type='python', unroll=False):
        if implementation_type == 'python':
            return [self.get_var_ID('out', 0, unroll) + ' = (' + self.get_var_ID('in', 0, unroll) + [" >> " if self.direction == 'r' else " << "][0] + str(self.amount) + ") & (2**" + str(self.input_vars[0].bitsize) + " - 1)"]
        elif implementation_type == 'c':
            return [self.get_var_ID('out', 0, unroll) + ' = (' + self.get_var_ID('in', 0, unroll) + [" >> " if self.direction == 'r' else " << "][0] + str(self.amount) + ') & ((1<<' + str(self.input_vars[0].bitsize) + ') - 1);']
        elif implementation_type == 'verilog':
            return ["assign " + self.get_var_ID('out', 0, unroll) + ' = (' + self.get_var_ID('in', 0, unroll) + [" >> " if self.direction == 'r' else " << "][0] + str(self.amount) + ') & ((1<<' + str(self.input_vars[0].bitsize) + ') - 1);']
        else: raise Exception(str(self.__class__.__name__) + ": unknown implementation type '" + implementation_type + "'")

    def generate_model(self, model_type='sat'):
        if model_type == 'sat':
            var_in, var_out = self.get_var_model("in", 0), self.get_var_model("out", 0)

            n = len(var_in)
            s = self.amount

            def eq_clause(a, b): # a = b  <=>  (not a or b) and (a or not b)
                return [f"-{a} {b}", f"{a} -{b}"]

            def zero_clause(a): # a = 0
                return f"-{a}"

            def tautology_clause(a): # a or not a. This is only used to keep shifted-out variables visible in the SAT model.
                return f"{a} -{a}"

            if self.direction == 'r' and self.model_version == self.__class__.__name__ + "_XORDIFF":
                # XOR-difference propagation for y = x >> s:
                # y_i = 0       for 0 <= i < s,
                # y_i = x_{i-s} for s <= i < n.
                model_list = [zero_clause(var_out[i]) for i in range(s)]
                model_list += [
                    clause
                    for i in range(n - s)
                    for clause in eq_clause(var_in[i], var_out[i + s])
                ]
                model_list += [tautology_clause(var_in[i]) for i in range(n - s, n)]
                return model_list

            elif self.direction == 'l' and self.model_version == self.__class__.__name__ + "_XORDIFF":
                # XOR-difference propagation for y = x << s:
                # y_i = x_{i+s} for 0 <= i < n-s,
                # y_i = 0       for n-s <= i < n.
                model_list = [tautology_clause(var_in[i]) for i in range(s)]
                model_list += [
                    clause
                    for i in range(n - s)
                    for clause in eq_clause(var_in[i + s], var_out[i])
                ]
                model_list += [zero_clause(var_out[i]) for i in range(n - s, n)]
                return model_list

            elif self.direction == 'r' and self.model_version == self.__class__.__name__ + "_LINEAR":
                # Linear-mask propagation for y = x >> s:
                # x_i = y_{i+s} for 0 <= i < n-s,
                # x_i = 0       for n-s <= i < n.
                # The output masks y_0,...,y_{s-1} correspond to zero-padded positions and are free.
                model_list = [tautology_clause(var_out[i]) for i in range(s)]
                model_list += [
                    clause
                    for i in range(n - s)
                    for clause in eq_clause(var_in[i], var_out[i + s])
                ]
                model_list += [zero_clause(var_in[i]) for i in range(n - s, n)]
                return model_list

            elif self.direction == 'l' and self.model_version == self.__class__.__name__ + "_LINEAR":
                # Linear-mask propagation for y = x << s:
                # x_i = 0       for 0 <= i < s,
                # x_i = y_{i-s} for s <= i < n.
                # The output masks y_{n-s},...,y_{n-1} correspond to zero-padded positions and are free.
                model_list = [zero_clause(var_in[i]) for i in range(s)]
                model_list += [
                    clause
                    for i in range(n - s)
                    for clause in eq_clause(var_in[i + s], var_out[i])
                ]
                model_list += [tautology_clause(var_out[i]) for i in range(n - s, n)]
                return model_list
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'milp':
            var_in, var_out = self.get_var_model("in", 0), self.get_var_model("out", 0)
            n = len(var_in)
            s = self.amount

            def eq_constraint(a, b): # a = b
                return f"{a} - {b} = 0"

            def zero_constraint(a): # a = 0
                return f"{a} = 0"

            def binary_declaration():
                return "Binary\n" + " ".join(v for v in var_in + var_out)

            if self.direction == 'r' and self.model_version ==  self.__class__.__name__ + "_XORDIFF":
                # XOR-difference propagation for y = x >> s:
                # y_i = 0       for 0 <= i < s,
                # y_i = x_{i-s} for s <= i < n.
                model_list = [zero_constraint(var_out[i]) for i in range(s)]
                model_list += [
                    eq_constraint(var_in[i], var_out[i + s])
                    for i in range(n - s)
                ]
                model_list.append(binary_declaration())
                return model_list

            elif self.direction == 'l' and self.model_version == self.__class__.__name__ + "_XORDIFF":
                # XOR-difference propagation for y = x << s:
                # y_i = x_{i+s} for 0 <= i < n-s,
                # y_i = 0       for n-s <= i < n.
                model_list = [
                    eq_constraint(var_in[i + s], var_out[i])
                    for i in range(n - s)
                ]
                model_list += [
                    zero_constraint(var_out[i])
                    for i in range(n - s, n)
                ]
                model_list.append(binary_declaration())
                return model_list

            elif self.direction == 'r' and self.model_version == self.__class__.__name__ + "_LINEAR":
                # Linear-mask propagation for y = x >> s:
                # x_i = y_{i+s} for 0 <= i < n-s,
                # x_i = 0       for n-s <= i < n.
                model_list = [
                    eq_constraint(var_in[i], var_out[i + s])
                    for i in range(n - s)
                ]
                model_list += [
                    zero_constraint(var_in[i])
                    for i in range(n - s, n)
                ]
                model_list.append(binary_declaration())
                return model_list

            elif self.direction == 'l' and self.model_version == self.__class__.__name__ + "_LINEAR":
                # Linear-mask propagation for y = x << s:
                # x_i = 0       for 0 <= i < s,
                # x_i = y_{i-s} for s <= i < n.
                model_list = [
                    zero_constraint(var_in[i])
                    for i in range(s)
                ]
                model_list += [
                    eq_constraint(var_in[i + s], var_out[i])
                    for i in range(n - s)
                ]
                model_list.append(binary_declaration())
                return model_list
            else: RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        elif model_type == 'cp': RaiseExceptionVersionNotExisting(str(self.__class__.__name__), self.model_version, model_type)
        else: raise Exception(str(self.__class__.__name__) + ": unknown model type '" + model_type + "'")

class ARADI_L32(Operator):
    """
    ARADI linear layer on a 32-bit word, operating on 16-bit halves internally.
    Input:  x (32-bit)
    Output: y (32-bit)
    where y = join( L16(hi), L16(lo) ) with cross terms as per ARADI spec:
      u' = u ^ ROTL16(u,a) ^ ROTL16(l,c)
      l' = l ^ ROTL16(l,a) ^ ROTL16(u,b)
      y  = (u'<<16) | l'
    """
    def __init__(self, input_vars, output_vars, a, b, c, ID=None):
        super().__init__(input_vars, output_vars, ID=ID)
        if len(input_vars) != 1 or len(output_vars) != 1:
            raise Exception(f"{self.__class__.__name__}: expects 1 input and 1 output")
        if input_vars[0].bitsize != 32 or output_vars[0].bitsize != 32:
            raise Exception(f"{self.__class__.__name__}: input/output must be 32-bit")

        self.a, self.b, self.c = a, b, c
        
    def generate_model(self, model_type='python'):
        return super().generate_model(model_type)

    def generate_implementation(self, implementation_type='python', unroll=False):
        x  = self.get_var_ID('in', 0, unroll)
        y  = self.get_var_ID('out', 0, unroll)
        a, b, c = self.a, self.b, self.c

        if implementation_type == 'python':
            return [
                f"u = ({x} >> 16) & 0xFFFF",
                f"l = {x} & 0xFFFF",
                f"ru = ((u << {a}) | (u >> (16-{a}))) & 0xFFFF",
                f"rl = ((l << {a}) | (l >> (16-{a}))) & 0xFFFF",
                f"rlc = ((l << {c}) | (l >> (16-{c}))) & 0xFFFF",
                f"rub = ((u << {b}) | (u >> (16-{b}))) & 0xFFFF",
                f"u2 = (u ^ ru ^ rlc) & 0xFFFF",
                f"l2 = (l ^ rl ^ rub) & 0xFFFF",
                f"{y} = ((u2 << 16) | l2) & 0xFFFFFFFF",
            ]
        elif implementation_type == 'c':
            tag = self.ID if self.ID is not None else f"{x}_{y}"
            # make it a safe C identifier
            tag = ''.join(ch if ch.isalnum() else '_' for ch in str(tag))

            up  = f"up_{tag}"
            lp  = f"lp_{tag}"
            ru  = f"ru_{tag}"
            rl  = f"rl_{tag}"
            rlc = f"rlc_{tag}"
            rub = f"rub_{tag}"
            u2  = f"u2_{tag}"
            l2  = f"l2_{tag}"

            return [
                f"uint32_t {up} = ({x} >> 16) & 0xFFFFu;",
                f"uint32_t {lp} = {x} & 0xFFFFu;",
                f"uint32_t {ru}  = (({up} << {a}) | ({up} >> (16-{a}))) & 0xFFFFu;",
                f"uint32_t {rl}  = (({lp} << {a}) | ({lp} >> (16-{a}))) & 0xFFFFu;",
                f"uint32_t {rlc} = (({lp} << {c}) | ({lp} >> (16-{c}))) & 0xFFFFu;",
                f"uint32_t {rub} = (({up} << {b}) | ({up} >> (16-{b}))) & 0xFFFFu;",
                f"uint32_t {u2} = ({up} ^ {ru} ^ {rlc}) & 0xFFFFu;",
                f"uint32_t {l2} = ({lp} ^ {rl} ^ {rub}) & 0xFFFFu;",
                f"{y} = (({u2} << 16) | {l2});",
            ]
        else:
            raise Exception(f"{self.__class__.__name__}: unknown implementation type '{implementation_type}'")


class CustomOP(Operator):   # generic custom operator (to be defined by the user)
    def __init__(self, input_vars, output_vars, ID = None):
        super().__init__(input_vars, output_vars, ID=ID)
        pass # TODO
