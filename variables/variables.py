"""
A cipher is modeled as a graph of two node types: variables and operators.

This module defines the :class:`Variable` node. A Variable can only be linked to an
operator node in the graph.
"""


class Variable:
    """A variable node in OCP's graph representation.

    Example:
        >>> from variables.variables import Variable
        >>> v = Variable(8, value=10, ID="v_1_0_3")
        >>> v.display_value("hexadecimal")
        '0a'

    Args:
        bitsize (int): Bit-width of the variable (must be a positive integer).
        value (int, optional): Concrete value, if set. Must fit in ``bitsize``
            bits. Defaults to None (value not set).
        ID (str, optional): Identifier string, typically ``'name_round_layer_pos'``.
            Defaults to None.
        copyorigin (Variable, optional): The variable this one is a copy of, or
            None if it is not a copy. Defaults to None.

    Besides the constructor arguments (stored as same-named attributes), a
    Variable also holds:

    Attributes:
        connected_vars (list): Connected variables, each stored with the
            operator linking them and the input/output role.
        copied_vars (list): Copies of this variable, stored as tuples
            ``(variable, target operator, copy operator)``.

    Raises:
        ValueError: If ``bitsize`` is not a positive integer, ``ID`` is not a
            string, or ``value`` does not fit in ``bitsize`` bits.
    """

    def __init__(self, bitsize, value=None, ID=None, copyorigin=None):
        if not isinstance(bitsize, int) or bitsize <= 0:
            raise ValueError("Variable bitsize must be a positive integer.")
        if ID is not None and not isinstance(ID, str):
            raise ValueError("Variable ID must be None or a string.")
        if value is not None and (not isinstance(value, int) or value < 0 or value >= 2**bitsize):
            raise ValueError("Variable value must be an integer fitting in bitsize.")

        self.bitsize = bitsize
        self.value = value
        self.ID = ID
        self.connected_vars = []
        self.copied_vars = []
        self.copyorigin = copyorigin

    def display_value(self, representation='binary'):
        """Return the variable's value as a string in the given representation.

        Args:
            representation (str): ``'binary'``, ``'hexadecimal'``, or
                ``'integer'``. Defaults to ``'binary'``.

        Returns:
            str: The formatted value, ``"None"`` if the value is unset, or
            ``"Invalid representation"`` if ``representation`` is unknown.
        """
        if self.value is None:
            return "None"
        if representation == 'binary':
            return bin(self.value)[2:].zfill(self.bitsize)
        elif representation == 'hexadecimal':
            return hex(self.value)[2:].zfill((self.bitsize + 3) // 4)
        elif representation == 'integer':
            return str(self.value)
        else:
            return "Invalid representation"

    def display(self, representation='binary'):
        """Print the variable's ID, bitsize, and value.

        Args:
            representation (str): Value representation passed to
                :meth:`display_value`. Defaults to ``'binary'``.
        """
        display_id = "" if self.ID is None else self.ID
        print(f"ID: {display_id} / bitsize: {self.bitsize} / value: {self.display_value(representation)}")

    def remove_round_from_ID(self):
        """Return the ID with the round field removed (``'name_round_layer_pos'`` -> ``'name_layer_pos'``).

        Used when unroll mode is off. Assumes ``name`` has no underscores, so splitting
        on ``_`` puts the round in the second field; if that field is not a digit, the
        ID is returned unchanged (``""`` if the ID is None).

        Example:
            >>> from variables.variables import Variable
            >>> Variable(8, ID="v_1_0_3").remove_round_from_ID()
            'v_0_3'
        """
        if self.ID is None:
            return ""
        parts = self.ID.split("_")
        if len(parts) >= 4 and parts[1].isdigit():
            return '_'.join(part for i, part in enumerate(parts) if i != 1)
        return self.ID
