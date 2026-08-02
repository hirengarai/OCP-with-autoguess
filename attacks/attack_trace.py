from abc import ABC, abstractmethod
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1] # this file -> attacks -> <ROOT>
FILES_DIR = ROOT / "files"


def _bin_to_hex(bits): # Format bits as hex (with "-" for unknown nibbles).
    if len(bits) % 4 != 0:
        pad = 4 - len(bits) % 4
        bits = "0" * pad + bits  # Pad with zeros to make length a multiple of 4
        print(f"[WARNING] Padded {pad} trailing '0'(s) to align to 4-bit nibbles for hex formatting.")
    hex_digits = []
    # Convert each 4-bit group to hex, but keep "-" when any bit is unknown.
    for i in range(0, len(bits), 4):
        chunk = bits[i:i + 4]
        if "-" in chunk:
            if chunk != "----":
                print(f"[WARNING] Nibble '{chunk}' contains mixed unknown bits; using '-' as a lossy representation.")
            hex_digits.append("-")
        else:
            hex_digits.append(hex(int(chunk, 2))[2:])
    return "".join(hex_digits)


class AttackTrace(ABC):
    """Abstract base for an attack result.

    Args:
        attack_type (str): The type of the trail (e.g. ``"differential"``, ``"linear"``, ``"integral"``).
        data (dict): Attack data. Must contain ``"cipher"`` (str, cipher name,
            e.g. ``"AES"``); other keys are read on demand by the concrete subclasses.
        solution_trace (dict, optional): Mapping from variable name to its value,
            e.g. the solution returned by a MILP/SAT solver. Defaults to None.
    """

    def __init__(self, attack_type, data, solution_trace=None):
        if "cipher" not in data:
            raise ValueError("data must contain 'cipher'")

        self.type = attack_type
        self.data = data
        self.solution_trace = solution_trace or {}

    def to_dict(self):
        """Return the attack result as a JSON-serializable dictionary.

        Returns:
            dict: A mapping with the keys ``"type"`` (uppercased attack type),
            ``"data"``, ``"solution_trace"``, and ``"tool"`` (the OCP version tag).
        """
        return {
            "type": str(self.type).upper(),
            "data": dict(self.data),
            "solution_trace": dict(self.solution_trace),
            "tool": "OCP1.0",
        }

    def _set_output_filenames(self, suffix):
        # Set output filenames to "<name>_<type>_<solver>_<suffix>.{json,txt,pdf,tex}":
        config_model = self.data.get("config_model", {})
        solver_name = self.data.get("config_solver", {}).get("solver", "DEFAULT")
        if "filename" in config_model:
            model_path = Path(config_model["filename"])
            stem = model_path.stem
            base_name = stem[:-len("_model")] if stem.endswith("_model") else stem
            base_path = model_path.with_name(f"{base_name}_{self.type}_{solver_name}_{suffix}")
        else:
            base_path = FILES_DIR / f"{self.data['cipher']}_{self.type}_{solver_name}_{suffix}"
        self.json_filename = f"{base_path}.json"
        self.txt_filename = f"{base_path}.txt"
        self.pdf_filename = f"{base_path}.pdf"
        self.tex_filename = f"{base_path}.tex"

    @abstractmethod
    def save_json(self, **kwargs):
        """Save the attack result to a ``.json`` file."""
        pass

    @abstractmethod
    def save_txt(self, **kwargs):
        """Save the attack result as human-readable text to a ``.txt`` file."""
        pass

    @abstractmethod
    def save_tex(self, **kwargs):
        """Save the attack result as a LaTeX ``.tex`` file."""
        pass

    @abstractmethod
    def save_pdf(self, **kwargs):
        """Save the attack result to a ``.pdf`` file."""
        pass


class Trail(AttackTrace):
    """Abstract base for trail-type attack results (differential, linear, ...).

    Args:
        attack_type (str): See :class:`AttackTrace`.
        data (dict): In addition to the base keys, may contain ``"functions"`` 
            (list of str, e.g. ``["PERMUTATION", "KEY_SCHEDULE"]``), ``"config_model"`` 
            (model configuration), and ``"config_solver"`` (solver configuration).
        solution_trace (dict, optional): See :class:`AttackTrace`. Defaults to None.
    """

    def __init__(self, attack_type, data, solution_trace=None):
        super().__init__(attack_type, data, solution_trace=solution_trace)
        self._set_output_filenames("trail")

    def print_trail(self, show_mode=2, hex_format=True):
        """Format the trail and print it to stdout.

        Args:
            show_mode (int): Level of detail, see :meth:`format_trail`.
            hex_format (bool): If True, format the values in hexadecimal; otherwise, in binary.
        """
        print(self.format_trail(show_mode, hex_format=hex_format))
    
    def save_json(self):
        trail_dict = self.to_dict()
        Path(self.json_filename).parent.mkdir(parents=True, exist_ok=True)
        with open(self.json_filename, "w", encoding="utf-8") as f:
            json.dump(trail_dict, f, ensure_ascii=False, indent='\t')

    def save_txt(self, show_mode=2, hex_format=True):
        """Save the trail as human-readable text to a ``.txt`` file.

        Args:
            show_mode (int): Level of detail, see :meth:`format_trail`.
            hex_format (bool): If True, format the values in hexadecimal; otherwise, in binary.
        """
        lines = self.format_trail(show_mode, hex_format=hex_format)
        Path(self.txt_filename).parent.mkdir(parents=True, exist_ok=True)
        with open(self.txt_filename, "w", encoding="utf-8") as f:
            f.write(lines)

    def save_tex(self): # TO DO
        raise NotImplementedError("LaTeX export is not implemented yet.")

    def save_pdf(self): # TO DO
        raise NotImplementedError("PDF export is not implemented yet.")

    @abstractmethod
    def format_trail(self, show_mode=2, hex_format=True):
        """Return the trail as a human-readable string.

        Args:
            show_mode (int): Level of detail:

                * ``0`` - first and last round only (first layer), excluding temporary variables.
                * ``1`` - all rounds (first layer only), excluding temporary variables.
                * ``2`` - all rounds and all layers, excluding temporary variables.
                * ``3`` - all rounds and all layers, including temporary variables.

            hex_format (bool): If True, format the values in hexadecimal; otherwise, in binary.

        Returns:
            str: The formatted trail.
        """
        lines = "========== Trail ==========\n"
        lines += f"Type: {self.type} ({'hexadecimal' if hex_format else 'binary'})\n"
        lines += f"Cipher: {self.data['cipher']}\n"

        if show_mode == 0:
            lines += "Show Mode: First Layer of First and Last Round.\n"
        elif show_mode == 1:
            lines += "Show Mode: First Layer of All Rounds (layer 0)\n"
        elif show_mode == 2:
            lines += "Show Mode: All Layers of All Rounds\n"
        elif show_mode == 3:
            lines += "Show Mode: All Layers of All Rounds (Including Temporary Words)\n"
        else:
            lines += f"[ERROR] Invalid show_mode {show_mode}. Cannot format the trail.\n"
            return lines

        def _validate_trail_struct(trail_struct):
            """
            Validate the basic structure of trail_struct. For example:
            trail_struct = {
                            "inputs": {...},
                            "outputs": {...},
                            "functions": {
                                "PERMUTATION": {
                                    "rounds": [],
                                    "nbr_words": ...,
                                    "nbr_temp_words": ...,
                                    1: {...},
                                    2: {...},
                                    3: {...},
                                },
                                ...
                            }
                        }
            """
            if not isinstance(trail_struct, dict):
                return "[WARNING] trail_struct is not a dictionary. Cannot format the trail structure.\n"

            for key in ("inputs", "functions", "outputs"):
                if key in trail_struct and not isinstance(trail_struct[key], dict):
                    return f"[WARNING] trail_struct['{key}'] is not a dictionary.\n"

            if "functions" not in trail_struct:
                return "[WARNING] trail_struct does not contain 'functions'. Cannot format the trail structure.\n"

            for fun, fun_struct in trail_struct["functions"].items():
                if not isinstance(fun_struct, dict):
                    return f"[WARNING] trail_struct['functions']['{fun}'] is not a dictionary.\n"

                if "rounds" not in fun_struct or not isinstance(fun_struct["rounds"], list) or len(fun_struct["rounds"]) == 0:
                    return f"[WARNING] 'rounds' is missing or invalid for function '{fun}'.\n"

                if "nbr_words" not in fun_struct or not isinstance(fun_struct["nbr_words"], int):
                    return f"[WARNING] 'nbr_words' is missing or invalid for function '{fun}'.\n"

                if "nbr_temp_words" not in fun_struct or not isinstance(fun_struct["nbr_temp_words"], int):
                    return f"[WARNING] 'nbr_temp_words' is missing or invalid for function '{fun}'.\n"

                for r in fun_struct["rounds"]:
                    if r not in fun_struct:
                        return f"[WARNING] Round {r} is missing for function '{fun}'.\n"
                    if not isinstance(fun_struct[r], dict):
                        return f"[WARNING] trail_struct['functions']['{fun}'][{r}] is not a dictionary.\n"

            return None

        trail_struct = self.data.get("trail_struct", None)
        warning = _validate_trail_struct(trail_struct)
        if warning is not None:
            lines += warning
            return lines

        # Print inputs
        if "inputs" in trail_struct:
            lines += "######## Input: ########\n"
            for name, node_list in trail_struct["inputs"].items():
                state = "".join(node["bin_values"] for node in node_list)
                lines += f"{name}: " + (_bin_to_hex(state) if hex_format else state) + "\n"

        # Print functions
        for fun, fun_struct in trail_struct["functions"].items():
            lines += f"######## Function: {fun} ########\n"

            rounds = fun_struct["rounds"]
            if show_mode == 0:
                show_rounds = [rounds[0], rounds[-1]] if len(rounds) > 1 else [rounds[0]]
            else:
                show_rounds = rounds

            for r in show_rounds:
                lines += f"Round {r}:\n"
                for l in fun_struct[r]:
                    if show_mode in {0, 1} and l != 0 and fun != "SUBKEYS":
                        continue

                    lines += f"Layer {l}: "

                    nbr_words = fun_struct["nbr_words"]
                    nbr_temp_words = fun_struct["nbr_temp_words"]
                    layer_nodes = fun_struct[r][l]

                    state = "".join(layer_nodes[i]["bin_values"] for i in range(nbr_words))
                    lines += _bin_to_hex(state) if hex_format else state

                    if show_mode == 3 and nbr_temp_words > 0:
                        temp_state = "".join(layer_nodes[nbr_words + i]["bin_values"] for i in range(nbr_temp_words))
                        lines += _bin_to_hex(temp_state) if hex_format else temp_state
                    lines += "\n"

        # Print outputs
        if "outputs" in trail_struct:
            lines += "######## Output: ########\n"
            for name, node_list in trail_struct["outputs"].items():
                state = "".join(node["bin_values"] for node in node_list)
                lines += f"{name}: " + (_bin_to_hex(state) if hex_format else state) + "\n"

        return lines


class DifferentialTrail(Trail):
    """A differential trail.

    Args:
        data (dict): In addition to the base keys, may contain ``"diff_weight"``
            (float, int, or None; the trail weight, i.e. the negative base-2
            logarithm of the differential probability, e.g. ``2``),
            ``"rounds_diff_weight"`` (list of float or None; per-round weights,
            e.g. ``[0, 1, 1]``), and ``"trail_struct"`` (dict; the trail structure).
        solution_trace (dict, optional): See :class:`AttackTrace`. Defaults to None.
    """

    def __init__(self, data, solution_trace=None):
        super().__init__("differential", data, solution_trace=solution_trace)


    def format_trail(self, show_mode=2, hex_format=True):
        lines = super().format_trail(show_mode, hex_format=hex_format)

        if "diff_weight" in self.data and self.data["diff_weight"] is not None:
            lines += f"\nTotal Weight: {self.data['diff_weight']}\n"
        if "rounds_diff_weight" in self.data and self.data["rounds_diff_weight"] is not None:
            lines += f"rounds_diff_weight: {self.data['rounds_diff_weight']}\n"
        return lines


class LinearTrail(Trail):
    """A linear trail.

    Args:
        data (dict): In addition to the base keys, may contain ``"linear_weight"``
            (float, int, or None; the trail weight, i.e. the negative base-2
            logarithm of the linear correlation, e.g. ``2``),
            ``"rounds_linear_weight"`` (list of float or None; per-round weights,
            e.g. ``[0, 1, 1]``), and ``"trail_struct"`` (dict; the trail structure).
        solution_trace (dict, optional): See :class:`AttackTrace`. Defaults to None.
    """

    def __init__(self, data, solution_trace=None):
        super().__init__("linear", data, solution_trace=solution_trace)


    def format_trail(self, show_mode=2, hex_format=True):
        lines = super().format_trail(show_mode, hex_format=hex_format)

        if "linear_weight" in self.data and self.data["linear_weight"] is not None:
            lines += f"\nTotal Weight: {self.data['linear_weight']}\n"
        if "rounds_linear_weight" in self.data and self.data["rounds_linear_weight"] is not None:
            lines += f"rounds_linear_weight: {self.data['rounds_linear_weight']}\n"
        return lines


class IntegralDistinguisher(AttackTrace):
    """An integral (division-property) distinguisher result.

    Args:
        data (dict): In addition to the base keys, may contain ``"goal"``,
            ``"status"``, ``"balanced_bits"`` (list), ``"config_model"``, and
            ``"config_solver"``.
        solution_trace (dict, optional): See :class:`AttackTrace`. Defaults to None.
    """

    def __init__(self, data, solution_trace=None):
        super().__init__("integral", data, solution_trace=solution_trace)
        self._set_output_filenames("distinguisher")

    def format_distinguisher(self):
        """Return the distinguisher as a human-readable string.

        Returns:
            str: The formatted distinguisher.
        """
        lines = []
        lines.append("========== Integral Distinguisher ==========")
        lines.append(f"Cipher: {self.data['cipher']}")
        lines.append(f"Goal: {self.data.get('goal')}")
        lines.append(f"Status: {self.data.get('status')}")
        lines.append(f"Balanced bits: {self.data.get('balanced_bits', [])}")
        lines.append(f"Model file: {self.data.get('config_model', {}).get('filename')}")
        lines.append("")
        return "\n".join(lines)

    def print_distinguisher(self):
        """Format the distinguisher and print it to stdout."""
        print(self.format_distinguisher())

    def save_json(self):
        Path(self.json_filename).parent.mkdir(parents=True, exist_ok=True)
        with open(self.json_filename, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent='\t')
    
    def save_txt(self):
        text = self.format_distinguisher()
        Path(self.txt_filename).parent.mkdir(parents=True, exist_ok=True)
        with open(self.txt_filename, "w", encoding="utf-8") as f:
            f.write(text)

    def save_tex(self): # TO DO
        raise NotImplementedError("LaTeX export is not implemented yet.")

    def save_pdf(self): # TO DO
        raise NotImplementedError("PDF export is not implemented yet.")
