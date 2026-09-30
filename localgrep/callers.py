import os
import re
import subprocess
from typing import Dict, Any, List

def get_enclosing_context(filepath: str, target_line: int, max_lookup: int = 35) -> str:
    """Scan upwards from target_line to find the enclosing function or class."""
    if not os.path.isfile(filepath):
        return ""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        start = max(0, target_line - max_lookup)
        candidate_lines = lines[start:target_line]

        for l in reversed(candidate_lines):
            l_strip = l.strip()
            fn_m = re.search(r"function\s+([a-zA-Z0-9_]+)\s*\(", l_strip)
            if fn_m:
                return f"{fn_m.group(1)}()"
            cls_m = re.search(r"class\s+([a-zA-Z0-9_]+)", l_strip)
            if cls_m:
                return f"class {cls_m.group(1)}"
            if "<template>" in l_strip:
                return "<template>"
    except Exception:
        pass
    return ""

def find_callers(
    symbol: str,
    cwd: str,
    include_imports: bool = False,
    top_k: int = 50
) -> Dict[str, Any]:
    """Find actual call sites and references for a function, method, or class, filtering definitions and comments."""
    clean_sym = symbol.strip()
    if not clean_sym:
        return {"status": "error", "message": "Symbol query cannot be empty."}

    search_dirs = [d for d in ["app", "resources", "vendor/bina", "Modules", "routes"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = [
        "rg", "-n", "--no-heading",
        "-g", "!**/*.md",
        "-g", "!**/node_modules/**",
        "-g", "!**/storage/**",
        "-g", "!**/vendor/laravel/**",
        "-F", clean_sym
    ] + search_dirs

    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        raw_output = res.stdout.strip()
    except Exception as e:
        return {"status": "error", "message": str(e)}

    if not raw_output:
        return {
            "status": "ok",
            "symbol": clean_sym,
            "total": 0,
            "files_count": 0,
            "results": [],
            "card": f"No callers found for '{clean_sym}'."
        }

    is_class_or_component = clean_sym[0].isupper()

    def_regexes = [
        re.compile(rf"(?:public|protected|private|static|\s|^)?\s*function\s+&?\s*{re.escape(clean_sym)}\s*\("),
        re.compile(rf"(?:public|protected|private|\s|^)?\s*fn\s+{re.escape(clean_sym)}\s*\("),
        re.compile(rf"def\s+{re.escape(clean_sym)}\s*\("),
        re.compile(rf"(?:abstract\s+|final\s+|readonly\s+)?class\s+{re.escape(clean_sym)}\b"),
        re.compile(rf"interface\s+{re.escape(clean_sym)}\b"),
        re.compile(rf"trait\s+{re.escape(clean_sym)}\b"),
        re.compile(rf"enum\s+{re.escape(clean_sym)}\b"),
    ]

    matches = []
    for line in raw_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        filepath, lineno_str, content = parts[0], parts[1], parts[2]
        try:
            lineno = int(lineno_str)
        except ValueError:
            continue

        stripped = content.strip()

        # 1. Skip comments
        if stripped.startswith(("//", "*", "/*", "#", "<!--")):
            continue

        # 2. Skip definitions
        if any(rgx.search(stripped) for rgx in def_regexes):
            continue

        # 3. Skip pure imports unless explicitly requested
        if not include_imports:
            if stripped.startswith("use ") and stripped.endswith(";"):
                continue
            if stripped.startswith("import ") and ("from" in stripped or stripped.endswith(";")):
                continue

        # 4. Invocations / references validation
        if not is_class_or_component:
            inv_patterns = [
                rf"->{re.escape(clean_sym)}\b",
                rf"\?->{re.escape(clean_sym)}\b",
                rf"::{re.escape(clean_sym)}\b",
                rf"\b{re.escape(clean_sym)}\s*\(",
                rf"['\"]{re.escape(clean_sym)}['\"]",
            ]
            if not any(re.search(pat, stripped) for pat in inv_patterns):
                continue
        else:
            class_patterns = [
                rf"\bnew\s+{re.escape(clean_sym)}\b",
                rf"\b{re.escape(clean_sym)}::",
                rf"<{re.escape(clean_sym)}\b",
                rf"</{re.escape(clean_sym)}>",
                rf":\s*{re.escape(clean_sym)}\b",
                rf"\?\s*{re.escape(clean_sym)}\b",
                rf"instanceof\s+{re.escape(clean_sym)}\b",
                rf"implements\s+[^\n]*\b{re.escape(clean_sym)}\b",
                rf"extends\s+[^\n]*\b{re.escape(clean_sym)}\b",
            ]
            if not any(re.search(pat, stripped) for pat in class_patterns):
                continue

        context = get_enclosing_context(os.path.join(cwd, filepath), lineno)

        matches.append({
            "file": filepath,
            "line": lineno,
            "context": context,
            "snippet": stripped
        })

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for m in matches:
        grouped.setdefault(m["file"], []).append(m)

    card_lines = [
        f"=== Callers for: '{clean_sym}' ({len(matches)} invocations across {len(grouped)} files) ==="
    ]
    for file, items in list(grouped.items())[:top_k]:
        card_lines.append(f"\n{file}:")
        for it in items:
            ctx_str = f" (in {it['context']})" if it.get("context") else ""
            card_lines.append(f"  Line {it['line']}{ctx_str}:")
            card_lines.append(f"    {it['snippet']}")

    return {
        "status": "ok",
        "symbol": clean_sym,
        "total": len(matches),
        "files_count": len(grouped),
        "results": matches,
        "card": "\n".join(card_lines)
    }
