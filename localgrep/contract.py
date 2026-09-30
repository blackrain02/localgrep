import os
import re
from typing import Dict, Any, List

def resolve_target_file(target: str, cwd: str) -> str:
    """Resolve a target string (relative path, absolute path, or symbol/component name) to an existing file."""
    # 1. Exact path
    if os.path.isabs(target) and os.path.isfile(target):
        return target
    rel_path = os.path.join(cwd, target)
    if os.path.isfile(rel_path):
        return rel_path

    # 2. Heuristic resolution by filename
    base_name = os.path.splitext(os.path.basename(target))[0].lower()
    target_exts = (".vue", ".php", ".ts", ".js", ".py")

    import subprocess
    try:
        search_dirs = [d for d in ["resources", "app", "routes", "config", "src", "packages", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
        if not search_dirs:
            search_dirs = ["."]

        globs = [
            "--glob", "!node_modules/**",
            "--glob", "!.git/**",
            "--glob", "!storage/**",
            "--glob", "!dist/**"
        ]
        res = subprocess.run(
            ["rg", "--files"] + globs + search_dirs,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        if res.stdout:
            lines = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
            candidates = []
            for f in lines:
                f_base = os.path.splitext(os.path.basename(f))[0].lower()
                if f_base == base_name or base_name in f_base:
                    # Score match
                    score = 10 if f_base == base_name else 5
                    if any(f.endswith(ext) for ext in target_exts):
                        score += 2
                    candidates.append((score, os.path.join(cwd, f)))
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]
    except Exception:
        pass

    return ""

def extract_vue_contract(content: str) -> str:
    out = []
    # 1. Script block
    script_m = re.search(r"<script(\s+[^>]*)?>(.*?)</script>", content, re.DOTALL)
    if script_m:
        script = script_m.group(2)
        patterns = [
            r"(?:const\s+\w+\s*=\s*)?defineProps\s*(?:<[^>]+>)?\s*\([^;]*\)",
            r"(?:const\s+\w+\s*=\s*)?defineEmits\s*(?:<[^>]+>)?\s*\([^;]*\)",
            r"(?:const\s+\w+\s*=\s*)?defineModel\s*(?:<[^>]+>)?\s*\([^;]*\)",
            r"(?:const\s+\w+\s*=\s*)?defineSlots\s*(?:<[^>]+>)?\s*\([^;]*\)",
            r"export\s+interface\s+\w+[^{]*\{[^}]*\}",
            r"export\s+type\s+\w+\s*=[^;]+;"
        ]
        for pat in patterns:
            for match in re.finditer(pat, script, re.DOTALL):
                block = match.group(0).strip()
                if block:
                    out.append(block)

    # 2. Template slots
    template_m = re.search(r"<template(\s+[^>]*)?>(.*?)</template>", content, re.DOTALL)
    if template_m:
        slots = re.findall(r'<slot\s*(?:name=["\']([^"\']+)["\'])?', template_m.group(2))
        slot_names = [s if s else "default" for s in slots]
        if slot_names:
            unique_slots = list(dict.fromkeys(slot_names))
            out.append(f"// Slots: {', '.join(unique_slots)}")

    return "\n\n".join(out) if out else "// No public props/emits found in component."

def extract_php_contract(content: str) -> str:
    try:
        from tree_sitter_languages import get_parser
        parser = get_parser("php")
        tree = parser.parse(content.encode("utf-8", errors="ignore"))
    except Exception:
        parser = None

    if parser:
        out = []
        ns = ""
        type_header = ""
        body_items = []

        def walk(node):
            nonlocal ns, type_header
            if node.type == "namespace_definition":
                for c in node.children:
                    if c.type == "namespace_name":
                        ns = f"namespace {c.text.decode('utf-8')};"
            elif node.type in ("class_declaration", "interface_declaration", "trait_declaration"):
                type_header = node.text.decode("utf-8", errors="ignore").split("{")[0].strip()
            elif node.type == "property_declaration":
                p_text = node.text.decode("utf-8", errors="ignore").strip()
                if "public" in p_text and not p_text.startswith("private") and not p_text.startswith("protected"):
                    body_items.append(f"    {p_text}")
            elif node.type == "method_declaration":
                m_text = node.text.decode("utf-8", errors="ignore").strip()
                sig = m_text.split("{")[0].strip()
                if "public function" in sig or (not sig.startswith("private") and not sig.startswith("protected") and "function" in sig):
                    body_items.append(f"    {sig};")

            for child in node.children:
                walk(child)

        walk(tree.root_node)

        if ns:
            out.append(ns)
        if type_header:
            out.append(f"{type_header} {{")
            out.extend(body_items)
            out.append("}")
        return "\n".join(out) if out else "// No public class or interface definitions found."

    # Regex Fallback
    out = []
    ns = re.search(r"namespace\s+([^;]+);", content)
    cls = re.search(r"((?:abstract\s+|final\s+)?(?:class|interface|trait)\s+\w+[^{]*)\{", content)
    props = re.findall(r"^\s*public\s+(?:readonly\s+)?(?:[\w\\?|]+\s+)?\$\w+[^;]*;", content, re.MULTILINE)
    methods = re.findall(r"^\s*public\s+(?:static\s+)?function\s+\w+\s*\([^)]*\)\s*(?::\s*[\w\\?|]+)?", content, re.MULTILINE)

    if ns:
        out.append(f"namespace {ns.group(1).strip()};")
    if cls:
        out.append(f"{cls.group(1).strip()} {{")
    for p in props:
        out.append(f"    {p.strip()}")
    for m in methods:
        out.append(f"    {m.strip()};")
    if cls:
        out.append("}")
    return "\n".join(out) if out else "// No public PHP contract found."

def extract_ts_js_contract(content: str) -> str:
    try:
        from tree_sitter_languages import get_parser
        parser = get_parser("typescript")
        tree = parser.parse(content.encode("utf-8", errors="ignore"))
    except Exception:
        parser = None

    if parser:
        out = []
        for node in tree.root_node.children:
            n_type = node.type
            if n_type in ("export_statement", "interface_declaration", "type_alias_declaration"):
                text = node.text.decode("utf-8", errors="ignore").strip()
                out.append(text)
            elif n_type in ("function_declaration", "lexical_declaration"):
                text = node.text.decode("utf-8", errors="ignore").strip()
                # If exported
                if text.startswith("export "):
                    sig = text.split("{")[0].strip()
                    out.append(f"{sig};")
                elif "export" in content:
                    # Check if exported at bottom
                    sig = text.split("{")[0].strip()
                    if sig:
                        out.append(f"{sig};")
        return "\n\n".join(out) if out else "// No exported types or signatures found."

    # Regex fallback
    funcs = re.findall(r"^\s*export\s+(?:async\s+)?function\s+\w+\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^;{\n]+)?", content, re.MULTILINE)
    interfaces = re.findall(r"^\s*export\s+(?:interface|type)\s+\w+[^;{\n]*\{[^}]*\}", content, re.MULTILINE | re.DOTALL)
    consts = re.findall(r"^\s*export\s+const\s+\w+\s*(?::\s*[^=]+)?", content, re.MULTILINE)
    out = []
    for i in interfaces:
        out.append(i.strip())
    for c in consts:
        out.append(c.strip() + ";")
    for f in funcs:
        out.append(f.strip() + ";")
    return "\n\n".join(out) if out else "// No exported signatures found."

def extract_contract(target: str, cwd: str) -> Dict[str, Any]:
    full_path = resolve_target_file(target, cwd)
    if not full_path or not os.path.isfile(full_path):
        return {
            "status": "error",
            "message": f"Target '{target}' could not be resolved to an existing file in project."
        }

    rel_path = os.path.relpath(full_path, cwd)
    ext = os.path.splitext(full_path)[1].lower()

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if ext == ".vue":
            contract = extract_vue_contract(content)
            lang = "Vue 3 Component"
        elif ext == ".php":
            contract = extract_php_contract(content)
            lang = "PHP Class / Interface"
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            contract = extract_ts_js_contract(content)
            lang = "TypeScript / JavaScript Module"
        else:
            contract = "// File type not supported for contract extraction."
            lang = "Unknown"

        return {
            "status": "ok",
            "target": target,
            "filepath": rel_path,
            "language": lang,
            "contract": contract
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed extracting contract from {rel_path}: {str(e)}"
        }
