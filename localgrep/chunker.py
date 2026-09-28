import os
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
}

AST_BLOCK_TYPES = {
    # Python
    "function_definition", "async_function_definition", "class_definition",
    # JS / TS / PHP
    "function_declaration", "method_declaration", "class_declaration",
    "interface_declaration", "arrow_function",
    # PHP specific
    "method_declaration", "trait_declaration",
    # Go
    "function_declaration", "method_declaration",
    # Rust
    "function_item", "impl_item", "trait_item"
}

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

def chunk_file(filepath: str, lines: List[str]) -> List[Dict[str, Any]]:
    if not lines:
        return []

    ext = os.path.splitext(filepath)[1].lower()
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
            # Ensure meaningful size (at least 2 lines)
            if end_row > start_row:
                chunk_lines = lines[start_row:end_row + 1]
                # If a function is extremely huge (> 75 lines), slice the header/start
                if len(chunk_lines) > 75:
                    chunk_lines = chunk_lines[:75]
                    end_row = start_row + 74
                ast_chunks.append({
                    "start": start_row + 1,
                    "end": end_row + 1,
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
