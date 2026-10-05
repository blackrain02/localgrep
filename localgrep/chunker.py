import os
import re
from typing import List, Dict, Any

EXT_TO_LANG = {
    ".py": "python",
    ".php": "php",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".vue": "vue",
}

AST_BLOCK_TYPES = {
    # Python
    "function_definition", "async_function_definition", "class_definition", "decorated_definition",
    # JS / TS / PHP
    "function_declaration", "method_declaration", "class_declaration",
    "interface_declaration", "arrow_function", "enum_declaration",
    "lexical_declaration", "variable_declaration",
    # PHP specific
    "trait_declaration", "property_declaration", "const_declaration",
    # Go
    "type_declaration", "function_declaration", "method_declaration",
    # Rust
    "function_item", "impl_item", "trait_item", "struct_item", "enum_item", "const_item", "static_item",
}

def extract_symbol_name(node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf-8", errors="ignore")

    if node.type in ("lexical_declaration", "variable_declaration"):
        for child in node.children:
            if child.type == "variable_declarator":
                vd_name = child.child_by_field_name("name")
                if vd_name:
                    return vd_name.text.decode("utf-8", errors="ignore")
    elif node.type == "property_declaration":
        for child in node.children:
            if child.type == "property_element":
                for sub in child.children:
                    if sub.type == "variable_name":
                        return sub.text.decode("utf-8", errors="ignore").lstrip("$")
    elif node.type == "const_declaration":
        for child in node.children:
            if child.type == "const_element":
                c_name = child.child_by_field_name("name")
                if c_name:
                    return c_name.text.decode("utf-8", errors="ignore")
    return ""

def extract_declaration_block(lines: List[str], start_idx: int, max_lines: int = 50) -> tuple:
    """
    Extracts a balanced syntactic block starting from start_idx up to semicolon or balanced braces.
    Returns (1-indexed start_line, 1-indexed end_line, text).
    """
    n = len(lines)
    end_idx = start_idx
    brace_depth = 0
    paren_depth = 0
    saw_bracket = False

    for i in range(start_idx, min(n, start_idx + max_lines)):
        line = lines[i]
        for ch in line:
            if ch == '{':
                brace_depth += 1
                saw_bracket = True
            elif ch == '}':
                brace_depth -= 1
            elif ch == '(':
                paren_depth += 1
                saw_bracket = True
            elif ch == ')':
                paren_depth -= 1

        end_idx = i
        if saw_bracket and brace_depth <= 0 and paren_depth <= 0:
            break
        if not saw_bracket and ';' in line:
            break

    block = "".join(lines[start_idx:end_idx + 1])
    return start_idx + 1, end_idx + 1, block.strip()

_PARSERS = {}

def get_ast_parser(lang: str):
    if lang not in _PARSERS:
        try:
            from tree_sitter_languages import get_parser
            _PARSERS[lang] = get_parser(lang)
        except Exception:
            _PARSERS[lang] = None
    return _PARSERS[lang]

def chunk_sliding_window(lines: List[str], window_size: int = 25, step_size: int = 15) -> List[Dict[str, Any]]:
    chunks = []
    if len(lines) <= window_size:
        return [{
            "start": 1,
            "end": len(lines),
            "text": "".join(lines),
            "kind": "full_file"
        }]

    for i in range(0, len(lines), step_size):
        chunk_lines = lines[i:i + window_size]
        if not chunk_lines:
            break
        chunks.append({
            "start": i + 1,
            "end": i + len(chunk_lines),
            "text": "".join(chunk_lines),
            "kind": "window"
        })
        if i + window_size >= len(lines):
            break
    return chunks

def chunk_vue_file(lines: List[str]) -> List[Dict[str, Any]]:
    full_text = "".join(lines)
    chunks = []
    parser = get_ast_parser("typescript") or get_ast_parser("javascript")

    # 1. Parse script blocks with TypeScript / JavaScript AST
    script_pattern = re.compile(r'<script(\s+[^>]*)?>', re.IGNORECASE)
    for match in script_pattern.finditer(full_text):
        start_char = match.end()
        end_match = re.search(r'</script>', full_text[start_char:], re.IGNORECASE)
        if not end_match:
            continue
        end_char = start_char + end_match.start()
        script_code = full_text[start_char:end_char]
        start_line = full_text[:start_char].count('\n') + 1
        script_lines = script_code.splitlines(keepends=True)

        if parser and script_code.strip():
            try:
                tree = parser.parse(script_code.encode('utf-8', errors='ignore'))
                for node in tree.root_node.children:
                    if node.type in AST_BLOCK_TYPES:
                        s_row = node.start_point[0]
                        e_row = node.end_point[0]
                        c_lines = script_lines[s_row:e_row + 1]
                        if len(c_lines) > 75:
                            c_lines = c_lines[:75]
                            e_row = s_row + 74
                        symbol_name = extract_symbol_name(node)
                        chunks.append({
                            "start": start_line + s_row,
                            "end": start_line + e_row,
                            "name": symbol_name,
                            "text": "".join(c_lines),
                            "kind": f"vue_{node.type}"
                        })
            except Exception:
                pass

    # 2. Parse template block
    template_match = re.search(r'<template(\s+[^>]*)?>\n?(.*?)</template>', full_text, re.DOTALL | re.IGNORECASE)
    if template_match:
        t_start_char = template_match.start(2)
        t_start_line = full_text[:t_start_char].count('\n') + 1
        t_content = template_match.group(2)
        t_lines = t_content.splitlines(keepends=True)
        if len(t_lines) <= 40:
            chunks.append({
                "start": t_start_line,
                "end": t_start_line + max(1, len(t_lines)) - 1,
                "text": t_content,
                "kind": "vue_template"
            })
        else:
            t_windows = chunk_sliding_window(t_lines, window_size=30, step_size=20)
            for tw in t_windows:
                tw["start"] += t_start_line - 1
                tw["end"] += t_start_line - 1
                tw["kind"] = "vue_template_window"
                chunks.append(tw)

    if not chunks:
        return chunk_sliding_window(lines)

    chunks.sort(key=lambda c: (c["start"], -c["end"]))
    return chunks

def chunk_file(filepath: str, lines: List[str]) -> List[Dict[str, Any]]:
    if not lines:
        return []

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".vue":
        return chunk_vue_file(lines)

    lang = EXT_TO_LANG.get(ext)
    if not lang:
        return chunk_sliding_window(lines)

    parser = get_ast_parser(lang)
    if not parser:
        return chunk_sliding_window(lines)

    content_bytes = "".join(lines).encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(content_bytes)
    except Exception:
        return chunk_sliding_window(lines)

    ast_chunks = []

    def visit(node):
        if node.type in AST_BLOCK_TYPES:
            start_row = node.start_point[0]
            end_row = node.end_point[0]
            if end_row >= start_row:
                chunk_lines = lines[start_row:end_row + 1]
                # If a function is extremely huge (> 75 lines), slice the header/start
                if len(chunk_lines) > 75:
                    chunk_lines = chunk_lines[:75]
                    end_row = start_row + 74
                symbol_name = extract_symbol_name(node)
                ast_chunks.append({
                    "start": start_row + 1,
                    "end": end_row + 1,
                    "name": symbol_name,
                    "text": "".join(chunk_lines),
                    "kind": f"ast_{node.type}"
                })
        for child in node.children:
            visit(child)

    visit(tree.root_node)

    # If AST found no blocks or very few, combine with sliding window for full coverage
    if not ast_chunks:
        return chunk_sliding_window(lines)

    # Sort and deduplicate chunks by start line
    ast_chunks.sort(key=lambda c: (c["start"], -c["end"]))
    unique_chunks = []
    seen = set()
    for c in ast_chunks:
        key = (c["start"], c["end"])
        if key not in seen:
            seen.add(key)
            unique_chunks.append(c)

    return unique_chunks
