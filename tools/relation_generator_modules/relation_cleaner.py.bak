"""
Relation Cleaner using Union-Find (Optimized)

Algorithm:
1. Parse relations -> rename, non-rename
2. Extract pairs from rename relations (separate same-round and cross-round)
3. Find output variables from non-rename relations
4. Build Union-Find from same-round pairs only
5. Get equivalence classes
6. Choose representative for each class:
   - Has output var -> highest (round, layer)
   - No output var -> lowest (round, layer)
7. Build substitution map
8. Apply substitutions to non-rename relations
9. Handle cross-round substitutions
10. Return cleaned relations
"""

import re
from typing import Dict, List, Set, Tuple, Optional


# Regex cache for faster token replacement
_REGEX_CACHE: Dict[str, re.Pattern] = {}


def get_regex_pattern(var: str) -> re.Pattern:
    """Get cached regex pattern for a variable."""
    if var not in _REGEX_CACHE:
        _REGEX_CACHE[var] = re.compile(
            r'(?<![0-9A-Za-z_])' + re.escape(var) + r'(?![0-9A-Za-z_])'
        )
    return _REGEX_CACHE[var]


def parse_var(var: str) -> Optional[Tuple[int, int, int]]:
    """Parse variable name like 'vk_1_2_3' into (round, layer, word)."""
    parts = var.rsplit("_", 3)
    if len(parts) != 4:
        return None
    
    prefix, r, l, w = parts
    
    try:
        return (int(r), int(l), int(w))
    except ValueError:
        return None


def extract_variables(line: str) -> List[str]:
    """Extract all variable tokens from a line."""
    return re.findall(r'[A-Za-z_][A-Za-z0-9_]*', line)


def has_prefix(var: str, prefix: str) -> bool:
    """Check if a variable has a given prefix."""
    return var.startswith(prefix)


def get_prefix(var: str) -> Optional[str]:
    """Get the prefix of a variable (e.g., 'vk', 'vs', 'vsk')."""
    parts = var.split("_")
    if len(parts) >= 1:
        return parts[0]
    return None


def is_rename_relation(line: str) -> bool:
    """Rename relation: exactly 2 variables, no '+', no '=>'"""
    if "+" in line or "=>" in line:
        return False
    
    tokens = [t.strip() for t in line.split(",") if t.strip()]
    return len(tokens) == 2


def parse_file(lines: List[str]) -> Dict:
    """
    Parse input file into sections.
    
    Returns dict with keys: 'connection', 'algebraic', 'known', 'target'
    """
    result = {
        'connection': [],
        'algebraic': [],
        'known': [],
        'target': []
    }
    
    current_section = None
    
    for line in lines:
        line = line.strip()
        
        if not line or line.startswith("#"):
            continue
        
        lower = line.lower()
        
        if lower == "connection relations":
            current_section = 'connection'
            continue
        elif lower == "algebraic relations":
            current_section = 'algebraic'
            continue
        elif lower == "known":
            current_section = 'known'
            continue
        elif lower == "target":
            current_section = 'target'
            continue
        elif lower == "end":
            break
        
        if current_section:
            result[current_section].append(line)
    
    return result


def parse_relations(connection: List[str], algebraic: List[str]) -> Tuple[List[str], List[str]]:
    """Separate relations into rename and non-rename."""
    rename_relations = []
    non_rename_relations = []
    
    # Process connection relations
    for line in connection:
        if is_rename_relation(line):
            rename_relations.append(line)
        else:
            non_rename_relations.append(line)
    
    # All algebraic relations are non-rename
    non_rename_relations.extend(algebraic)
    
    return rename_relations, non_rename_relations


def is_cross_round(a: str, b: str) -> bool:
    """Check if two variables are from different rounds."""
    pa = parse_var(a)
    pb = parse_var(b)
    
    if pa is None or pb is None:
        return False
    
    r1, l1, w1 = pa
    r2, l2, w2 = pb
    
    return r1 != r2


def extract_pairs(rename_relations: List[str]) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Extract variable pairs from rename relations.
    Separate into same-round and cross-round.
    """
    same_round_pairs = []
    cross_round_pairs = []
    
    for line in rename_relations:
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        if len(tokens) == 2:
            a, b = tokens
            if is_cross_round(a, b):
                cross_round_pairs.append((a, b))
            else:
                same_round_pairs.append((a, b))
    
    return same_round_pairs, cross_round_pairs


def get_output_variable(line: str) -> Optional[str]:
    """Get the output variable from a non-rename relation."""
    if "=>" in line:
        right_part = line.split("=>")[1]
        tokens = [t.strip() for t in right_part.split(",") if t.strip()]
        if tokens:
            return tokens[0]
        return None
    
    variables = extract_variables(line)
    
    if not variables:
        return None
    
    best_var = None
    best_round = -1
    best_layer = -1
    
    for var in variables:
        parsed = parse_var(var)
        if parsed:
            r, l, w = parsed
            if (r, l) > (best_round, best_layer):
                best_round = r
                best_layer = l
                best_var = var
    
    return best_var


def find_output_vars(non_rename_relations: List[str]) -> Set[str]:
    """Find output variables from non-rename relations."""
    output_vars = set()
    
    for line in non_rename_relations:
        output = get_output_variable(line)
        if output:
            output_vars.add(output)
    
    return output_vars


class UnionFind:
    """Simple Union-Find data structure."""
    
    def __init__(self):
        self.parent: Dict[str, str] = {}
    
    def find(self, x: str) -> str:
        """Find root of x with path compression."""
        if x not in self.parent:
            self.parent[x] = x
        
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        
        return self.parent[x]
    
    def union(self, a: str, b: str) -> None:
        """Union the sets containing a and b."""
        ra = self.find(a)
        rb = self.find(b)
        
        if ra != rb:
            self.parent[ra] = rb
    
    def get_classes(self) -> Dict[str, Set[str]]:
        """Get all equivalence classes."""
        classes: Dict[str, Set[str]] = {}
        
        for x in self.parent:
            root = self.find(x)
            if root not in classes:
                classes[root] = set()
            classes[root].add(x)
        
        return classes


def build_union_find(same_round_pairs: List[Tuple[str, str]]) -> UnionFind:
    """Build Union-Find from same-round pairs."""
    uf = UnionFind()
    
    for a, b in same_round_pairs:
        uf.union(a, b)
    
    return uf


def get_equivalence_classes(uf: UnionFind) -> List[Set[str]]:
    """Get all equivalence classes from Union-Find."""
    classes_dict = uf.get_classes()
    return list(classes_dict.values())


def choose_representative(eq_class: Set[str], output_vars: Set[str], protected_vars: Set[str]) -> Optional[str]:
    """
    Choose representative for an equivalence class.
    
    Priority:
    1. If class contains protected variable(s) -> pick protected (warn if multiple)
    2. Else if class contains output variable -> pick highest (round, layer)
    3. Else -> pick lowest (round, layer)
    """
    # Check for protected variables
    protected_in_class = eq_class & protected_vars

    if protected_in_class:
        # Silently handle multiple protected variables - just pick the first one
        # if len(protected_in_class) > 1:
        #     print(f"Warning: Multiple protected variables in same class: {protected_in_class}")
        return list(protected_in_class)[0]
    
    # Check for output variables
    has_output = any(var in output_vars for var in eq_class)
    
    best_var = None
    best_key = None
    
    for var in eq_class:
        parsed = parse_var(var)
        if parsed is None:
            continue
        
        r, l, w = parsed
        key = (r, l)
        
        if best_key is None:
            best_key = key
            best_var = var
        elif has_output and key > best_key:
            best_key = key
            best_var = var
        elif not has_output and key < best_key:
            best_key = key
            best_var = var
    
    return best_var


def build_substitution_map(equivalence_classes: List[Set[str]], output_vars: Set[str], protected_vars: Set[str]) -> Dict[str, str]:
    """Build substitution map from equivalence classes."""
    substitution_map = {}
    
    for eq_class in equivalence_classes:
        rep = choose_representative(eq_class, output_vars, protected_vars)
        
        if rep is None:
            continue
        
        for var in eq_class:
            if var != rep:
                substitution_map[var] = rep
    
    return substitution_map


def handle_cross_round(cross_round_pairs: List[Tuple[str, str]], substitution_map: Dict[str, str]) -> Dict[str, str]:
    """
    Handle cross-round pairs.
    
    For each (a, b) where a is from round r and b is from round r+1:
    - Find what a was substituted to (actual_earlier)
    - Add actual_earlier -> b to substitution map
    """
    for a, b in cross_round_pairs:
        pa = parse_var(a)
        pb = parse_var(b)
        
        if pa is None or pb is None:
            continue
        
        r1, l1, w1 = pa
        r2, l2, w2 = pb
        
        if r1 < r2:
            earlier, later = a, b
        else:
            earlier, later = b, a
        
        actual_earlier = substitution_map.get(earlier, earlier)
        substitution_map[actual_earlier] = later
    
    return substitution_map


def apply_substitutions(lines: List[str], substitution_map: Dict[str, str]) -> List[str]:
    """Apply substitutions to a list of relation lines."""
    result = []
    
    for line in lines:
        variables = extract_variables(line)
        
        new_line = line
        for var in variables:
            if var in substitution_map:
                pattern = get_regex_pattern(var)
                new_line = pattern.sub(substitution_map[var], new_line)
        
        result.append(new_line)
    
    return result


def remove_trivial_relations(lines: List[str]) -> List[str]:
    """Remove trivial relations like 'x, x'."""
    result = []
    
    for line in lines:
        if "=>" in line or "+" in line:
            result.append(line)
            continue
        
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        
        if len(tokens) >= 2 and len(set(tokens)) > 1:
            result.append(line)
    
    return result


def is_algebraic_line(line: str) -> bool:
    """Check if a line is an algebraic relation."""
    return "+" in line and "=>" not in line


def contains_vk_variable(line: str) -> bool:
    """Check if a line contains any vk_* variable."""
    variables = extract_variables(line)
    return any(has_prefix(var, "vk_") for var in variables)


def clean_key_schedule(rename_relations: List[str], non_rename_relations: List[str]) -> Tuple[List[str], List[str]]:
    """
    Clean key schedule relations by replacing vk_* with vsk_*.

    - Build equivalence classes from ALL rename relations containing vk_* (both same-round and cross-round)
    - If class contains vsk_* -> choose the one with lowest (round, layer)
    - Replace all vk_* with their chosen vsk_* representative

    Returns: (cleaned_rename_relations, cleaned_non_rename_relations)
    """
    # Separate key schedule rename relations (those with vk_* or vsk_*)
    ks_rename = []
    other_rename = []

    for line in rename_relations:
        if contains_vk_variable(line) or "vsk_" in line:
            ks_rename.append(line)
        else:
            other_rename.append(line)

    # Extract ALL pairs from key schedule renames (including cross-round!)
    ks_pairs = []
    for line in ks_rename:
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        if len(tokens) == 2:
            ks_pairs.append((tokens[0], tokens[1]))

    # Build Union-Find from ALL pairs (same-round AND cross-round)
    uf = UnionFind()
    for a, b in ks_pairs:
        uf.union(a, b)

    # Get equivalence classes
    equivalence_classes = get_equivalence_classes(uf)

    # Build substitution map: prefer vsk_* with lowest (round, layer) as representative
    substitution_map = {}

    for eq_class in equivalence_classes:
        # Find vsk_* variable with lowest (round, layer) in class
        vsk_var = None
        vsk_key = None

        for var in eq_class:
            if has_prefix(var, "vsk_"):
                parsed = parse_var(var)
                if parsed:
                    r, l, w = parsed
                    key = (r, l)

                    if vsk_key is None or key < vsk_key:
                        vsk_key = key
                        vsk_var = var

        if vsk_var:
            # Replace all vk_* and other vsk_* with the chosen vsk_*
            for var in eq_class:
                if var != vsk_var:
                    substitution_map[var] = vsk_var

    # Apply substitutions to all relations
    cleaned_rename = apply_substitutions(other_rename, substitution_map)
    cleaned_non_rename = apply_substitutions(non_rename_relations, substitution_map)

    # Remove trivial rename relations
    cleaned_rename = remove_trivial_relations(cleaned_rename)

    return cleaned_rename, cleaned_non_rename


def format_output(cleaned: List[str], known: List[str], target: List[str]) -> List[str]:
    """Format cleaned relations into output file format."""
    output = []
    
    # Separate connection and algebraic
    connection = []
    algebraic = []
    
    for line in cleaned:
        if is_algebraic_line(line):
            algebraic.append(line)
        else:
            connection.append(line)
    
    if connection:
        output.append("connection relations")
        output.extend(connection)
    
    if algebraic:
        output.append("algebraic relations")
        output.extend(algebraic)
    
    if known:
        output.append("known")
        output.extend(known)
    
    if target:
        output.append("target")
        output.extend(target)
    
    output.append("end")
    
    return output


def clean_relations(lines: List[str], clean_key_schedule_flag: bool = False) -> List[str]:
    """
    Main function to clean relations.
    
    Args:
        lines: list of relation strings (file content)
        clean_key_schedule_flag: if True, replace vk_* with vsk_*
    
    Returns:
        list of cleaned relation strings in output format
    """
    # Parse file into sections
    parsed = parse_file(lines)
    connection = parsed['connection']
    algebraic = parsed['algebraic']
    known = parsed['known']
    target = parsed['target']
    
    # Build protected variables set
    protected_vars = set(known) | set(target)

    # Separate rename and non-rename
    rename_relations, non_rename_relations = parse_relations(connection, algebraic)

    # Key schedule cleaning (vk_* -> vsk_*) - Do this FIRST
    if clean_key_schedule_flag:
        rename_relations, non_rename_relations = clean_key_schedule(rename_relations, non_rename_relations)

    # Extract pairs
    same_round_pairs, cross_round_pairs = extract_pairs(rename_relations)

    # Find output variables
    output_vars = find_output_vars(non_rename_relations)

    # Build Union-Find from same-round pairs only
    uf = build_union_find(same_round_pairs)

    # Get equivalence classes
    equivalence_classes = get_equivalence_classes(uf)

    # Build substitution map (with protected vars)
    substitution_map = build_substitution_map(equivalence_classes, output_vars, protected_vars)

    # Apply substitutions to non-rename relations
    cleaned = apply_substitutions(non_rename_relations, substitution_map)

    # Handle cross-round pairs
    substitution_map = handle_cross_round(cross_round_pairs, substitution_map)
    cleaned = apply_substitutions(cleaned, substitution_map)

    # Remove trivial relations
    cleaned = remove_trivial_relations(cleaned)
    
    # Format output
    return format_output(cleaned, known, target)


def clean_file(input_path: str, output_path: str, clean_key_schedule_flag: bool = False) -> None:
    """
    Clean relations from input file and write to output file.
    
    Args:
        input_path: path to input .txt file
        output_path: path to output .txt file
        clean_key_schedule_flag: if True, replace vk_* with vsk_*
    """
    # Read input
    with open(input_path, 'r') as f:
        lines = f.readlines()
    
    # Clean
    result = clean_relations(lines, clean_key_schedule_flag)
    
    # Write output
    with open(output_path, 'w') as f:
        for line in result:
            f.write(line + '\n')

    # Removed verbose output - handled by relation_generator.py
    # print(f"Cleaned relations written to: {output_path}")
