import os
import re
from typing import Dict, Any, List, Optional, Tuple

EXT_TO_LANG = {
    ".php": "php",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
}

AST_METHOD_TYPES = {
    "method_declaration", "function_declaration", "function_definition",
    "method_definition", "arrow_function", "lexical_declaration"
}

def get_ast_parser(lang: str):
    try:
        from tree_sitter_languages import get_parser
        return get_parser(lang)
    except Exception:
        return None

def find_target_in_methods(methods: List[Dict[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    clean_target = target.strip().lower()
    # 1. Exact case-sensitive match
    for m in methods:
        if m["name"] and m["name"] == target.strip():
            return m
    # 2. Case-insensitive match
    for m in methods:
        if m["name"] and m["name"].lower() == clean_target:
            return m
    # 3. Substring match
    for m in methods:
        if m["name"] and (clean_target in m["name"].lower() or m["name"].lower() in clean_target):
            return m
    return None

def parse_php_methods(lines: List[str]) -> List[Dict[str, Any]]:
    parser = get_ast_parser("php")
    methods = []
    if not parser:
        return methods

    content = "".join(lines).encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(content)
    except Exception:
        return methods

    def walk(node):
        if node.type in ("method_declaration", "function_declaration"):
            s_row = node.start_point[0]
            e_row = node.end_point[0]
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8", errors="ignore") if name_node else ""
            methods.append({
                "start": s_row + 1,
                "end": e_row + 1,
                "name": name,
                "type": node.type
            })
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return methods

def parse_py_methods(lines: List[str]) -> List[Dict[str, Any]]:
    parser = get_ast_parser("python")
    methods = []
    if not parser:
        return methods

    content = "".join(lines).encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(content)
    except Exception:
        return methods

    def walk(node):
        if node.type in ("function_definition", "async_function_definition"):
            s_row = node.start_point[0]
            e_row = node.end_point[0]
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8", errors="ignore") if name_node else ""
            methods.append({
                "start": s_row + 1,
                "end": e_row + 1,
                "name": name,
                "type": node.type
            })
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return methods

def parse_ts_js_methods(lines: List[str], lang: str = "typescript") -> List[Dict[str, Any]]:
    parser = get_ast_parser(lang)
    methods = []
    if not parser:
        return methods

    content = "".join(lines).encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(content)
    except Exception:
        return methods

    def walk(node):
        if node.type in ("function_declaration", "method_definition"):
            s_row = node.start_point[0]
            e_row = node.end_point[0]
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8", errors="ignore") if name_node else ""
            methods.append({
                "start": s_row + 1,
                "end": e_row + 1,
                "name": name,
                "type": node.type
            })
        elif node.type == "lexical_declaration" and (node.end_point[0] - node.start_point[0] >= 1):
            for child in node.children:
                if child.type == "variable_declarator":
                    vd_name = child.child_by_field_name("name")
                    name = vd_name.text.decode("utf-8", errors="ignore") if vd_name else ""
                    methods.append({
                        "start": node.start_point[0] + 1,
                        "end": node.end_point[0] + 1,
                        "name": name,
                        "type": "const_declaration"
                    })
                    break
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return methods

def parse_vue_methods(lines: List[str]) -> Tuple[List[Dict[str, Any]], Optional[Tuple[int, int]]]:
    full_text = "".join(lines)
    methods = []
    template_range = None

    # Detect template block
    t_m = re.search(r'<template(\s+[^>]*)?>', full_text, re.IGNORECASE)
    if t_m:
        t_start = full_text[:t_m.start()].count('\n') + 1
        t_end_m = re.search(r'</template>', full_text[t_m.end():], re.IGNORECASE)
        if t_end_m:
            t_end = full_text[:t_m.end() + t_end_m.end()].count('\n') + 1
            template_range = (t_start, t_end)

    # Detect script block
    s_m = re.search(r'<script(\s+[^>]*)?>', full_text, re.IGNORECASE)
    if s_m:
        s_char = s_m.end()
        e_m = re.search(r'</script>', full_text[s_char:], re.IGNORECASE)
        if e_m:
            script_code = full_text[s_char:s_char + e_m.start()]
            script_start_line = full_text[:s_char].count('\n') + 1
            script_lines = script_code.splitlines(keepends=True)
            ts_methods = parse_ts_js_methods(script_lines, "typescript")
            for tm in ts_methods:
                tm["start"] += script_start_line - 1
                tm["end"] += script_start_line - 1
                methods.append(tm)

    return methods, template_range

def extract_file_slice(filepath: str, symbol: str, cwd: str = ".") -> Dict[str, Any]:
    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.isfile(full_path):
        return {
            "status": "error",
            "message": f"File not found: {filepath}"
        }

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        return {"status": "error", "message": str(e)}

    total_lines = len(lines)
    if total_lines == 0:
        return {"status": "ok", "skeleton": "// Empty file", "total_lines": 0, "sliced_lines": 0}

    ext = os.path.splitext(full_path)[1].lower()
    methods: List[Dict[str, Any]] = []
    template_range: Optional[Tuple[int, int]] = None

    if ext == ".php":
        methods = parse_php_methods(lines)
    elif ext == ".py":
        methods = parse_py_methods(lines)
    elif ext in (".ts", ".tsx"):
        methods = parse_ts_js_methods(lines, "typescript")
    elif ext in (".js", ".jsx"):
        methods = parse_ts_js_methods(lines, "javascript")
    elif ext == ".vue":
        methods, template_range = parse_vue_methods(lines)

    # Fallback method extraction via regex if parser produced nothing
    if not methods:
        pattern = re.compile(r'^\s*(?:(?:public|protected|private|static|async)\s+)*function\s+([A-Za-z0-9_]+)', re.MULTILINE)
        full_text = "".join(lines)
        for match in pattern.finditer(full_text):
            line_no = full_text[:match.start()].count('\n') + 1
            methods.append({
                "start": line_no,
                "end": min(line_no + 15, total_lines),
                "name": match.group(1),
                "type": "function"
            })

    target_method = find_target_in_methods(methods, symbol)
    if not target_method:
        return {
            "status": "error",
            "message": f"Target symbol '{symbol}' was not found in {filepath}. Available methods: {', '.join([m['name'] for m in methods if m['name']][:10])}"
        }

    # Sort methods by line
    methods.sort(key=lambda m: m["start"])

    # Build output skeleton
    output_lines = []
    current_line = 1
    t_start = target_method["start"]
    t_end = target_method["end"]

    # Filter non-target methods
    non_target_methods = [m for m in methods if m != target_method and m["start"] <= m["end"]]

    # For non-target methods, also capture preceding docblock comments
    for m in non_target_methods:
        s = m["start"]
        prev_idx = s - 2
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx >= 0 and lines[prev_idx].strip().endswith("*/"):
            comment_start = prev_idx
            while comment_start >= 0 and not lines[comment_start].strip().startswith("/*"):
                comment_start -= 1
            if comment_start >= 0 and comment_start + 1 > 0:
                m["collapse_start"] = comment_start + 1
            else:
                m["collapse_start"] = m["start"]
        else:
            m["collapse_start"] = m["start"]

    # Map line -> method covering it
    method_by_start = {m["collapse_start"]: m for m in non_target_methods}
    skipped_ranges = set()
    for m in non_target_methods:
        for l in range(m["collapse_start"], m["end"] + 1):
            skipped_ranges.add(l)

    # Detect large docblocks (> 8 lines) outside target method
    docblock_ranges = {}
    full_text = "".join(lines)
    for m in re.finditer(r'/\*\*[\s\S]*?\*/', full_text):
        db_start = full_text[:m.start()].count('\n') + 1
        db_end = full_text[:m.end()].count('\n') + 1
        if (db_end - db_start >= 8) and not (db_start <= t_start <= db_end + 2):
            docblock_ranges[db_start] = (db_start, db_end)

    while current_line <= total_lines:
        # Check large docblock collapse
        if current_line in docblock_ranges:
            db_s, db_e = docblock_ranges[current_line]
            db_len = db_e - db_s + 1
            indent = " " * (len(lines[current_line - 1]) - len(lines[current_line - 1].lstrip()))
            output_lines.append(f"{current_line:>5}: {indent}/** /* ... {db_len} lines docblock pruned ... */ */")
            current_line = db_e + 1
            continue

        # Check template collapse for Vue
        if template_range and current_line == template_range[0] and not (template_range[0] <= t_start <= template_range[1]):
            t_len = template_range[1] - template_range[0] + 1
            if t_len > 10:
                output_lines.append(f"{current_line:>5}: <template> /* ... {t_len} lines template collapsed ... */ </template>")
                current_line = template_range[1] + 1
                continue

        # Target method range: expand in full with line numbers
        if current_line == t_start:
            output_lines.append(f"       // >>> TARGET METHOD: {target_method['name']} (Lines {t_start}-{t_end}) >>>")
            for l in range(t_start, t_end + 1):
                if l <= total_lines:
                    output_lines.append(f"{l:>5}: {lines[l-1].rstrip()}")
            output_lines.append(f"       // <<< END TARGET METHOD ({target_method['name']}) <<<")
            current_line = t_end + 1
            continue

        # Non-target method: collapse to 1 line stub
        if current_line in method_by_start:
            m = method_by_start[current_line]
            m_len = m["end"] - m["start"] + 1
            first_line = lines[m["start"] - 1].strip()
            sig = first_line.split('{')[0].strip()
            indent = " " * (len(lines[m["start"] - 1]) - len(lines[m["start"] - 1].lstrip()))
            if ext == ".py":
                output_lines.append(f"{m['start']:>5}: {indent}def {m['name']}(...): # ... {m_len} lines pruned ...")
            else:
                output_lines.append(f"{m['start']:>5}: {indent}{sig} {{ /* ... {m_len} lines pruned ... */ }}")
            current_line = m["end"] + 1
            continue

        # If inside a skipped range (due to overlapping block), skip
        if current_line in skipped_ranges:
            current_line += 1
            continue

        # Normal line (imports, properties, refs, class definition)
        output_lines.append(f"{current_line:>5}: {lines[current_line - 1].rstrip()}")
        current_line += 1

    skeleton_text = "\n".join(output_lines)
    sliced_line_count = len(output_lines)
    saving_pct = round((1.0 - (sliced_line_count / max(1, total_lines))) * 100, 1)

    return {
        "status": "ok",
        "filepath": os.path.relpath(full_path, cwd),
        "symbol": target_method["name"],
        "target_start": t_start,
        "target_end": t_end,
        "original_lines": total_lines,
        "sliced_lines": sliced_line_count,
        "saving_pct": f"{saving_pct}%",
        "skeleton": skeleton_text
    }
