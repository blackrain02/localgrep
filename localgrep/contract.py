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

def extract_balanced(text: str, start_pos: int) -> str:
    """Extract a balanced parenthesis or bracket expression starting at start_pos."""
    idx = start_pos
    while idx < len(text) and text[idx] not in "({[":
        idx += 1
    if idx >= len(text):
        return ""

    stack = [text[idx]]
    pairs = {"(": ")", "{": "}", "[": "]"}
    idx += 1
    in_string = None
    while idx < len(text) and stack:
        char = text[idx]
        if in_string:
            if char == in_string and (idx == 0 or text[idx - 1] != "\\"):
                in_string = None
        else:
            if char in ("'", '"', "`"):
                in_string = char
            elif char in "({[":
                stack.append(char)
            elif char in ")}]":
                if stack and pairs.get(stack[-1]) == char:
                    stack.pop()
        idx += 1

    # Include any trailing semicolon or whitespace
    while idx < len(text) and text[idx] in "; \t":
        idx += 1
    return text[start_pos:idx].strip()

def extract_vue_contract(content: str, full: bool = False) -> str:
    out = []
    # 1. Script block
    script_m = re.search(r"<script(\s+[^>]*)?>(.*?)</script>", content, re.DOTALL)
    if script_m:
        script = script_m.group(2)

        # Extract interfaces & types related to props/emits/models
        for match in re.finditer(r"(?:export\s+)?(?:interface|type)\s+([A-Za-z0-9_]+)[^{;]*\{", script):
            name = match.group(1)
            is_exported = match.group(0).startswith("export")
            if is_exported or any(k in name.lower() for k in ("prop", "emit", "model", "slot")) or full:
                block = extract_balanced(script, match.start())
                if block and block not in out:
                    out.append(block)

        # Extract defineProps (including withDefaults), defineEmits, defineModel, defineSlots
        patterns = [
            r"(?:const\s+\w+\s*=\s*)?(?:withDefaults\s*\(\s*)?defineProps",
            r"(?:const\s+\w+\s*=\s*)?defineEmits",
            r"(?:const\s+\w+\s*=\s*)?defineModel",
            r"(?:const\s+\w+\s*=\s*)?defineSlots",
        ]
        if full:
            patterns.append(r"(?:const\s+\w+\s*=\s*)?defineExpose")

        for pat in patterns:
            for match in re.finditer(pat, script):
                block = extract_balanced(script, match.start())
                if block and block not in out:
                    out.append(block)

        if full:
            # 2. Extract reactive state variables (ref, reactive, computed)
            state_items = []
            for m in re.finditer(r"(?:const|let)\s+([a-zA-Z0-9_]+)\s*=\s*(ref|reactive|computed)\s*(?:<[^>]+>)?\s*\(", script):
                var_name = m.group(1)
                state_type = m.group(2)
                state_items.append(f"{var_name} ({state_type})")
            if state_items:
                unique_state = list(dict.fromkeys(state_items))[:20]
                out.append(f"// Reactive State: {', '.join(unique_state)}")

            # 3. Lifecycle hooks
            hook_names = [
                "onMounted", "onUnmounted", "onBeforeMount", "onBeforeUnmount",
                "onUpdated", "onBeforeUpdate", "onActivated", "onDeactivated"
            ]
            hook_summaries = []
            for h in hook_names:
                for match in re.finditer(rf"\b{h}\s*\(", script):
                    block = extract_balanced(script, match.start())
                    if block:
                        invocations = re.findall(r"\b([a-zA-Z0-9_]+)\s*\(", block)
                        called = [fn for fn in invocations if fn not in (h, "async", "function", "if", "for", "while", "console", "log", "error", "catch", "then", "setTimeout", "setInterval", "addEventListener", "removeEventListener") and len(fn) > 2]
                        unique_called = list(dict.fromkeys(called))[:5]
                        if unique_called:
                            hook_summaries.append(f"  - {h}: calls [{', '.join(unique_called)}]")
                        else:
                            hook_summaries.append(f"  - {h}")
            if hook_summaries:
                out.append("// Lifecycle Hooks:\n" + "\n".join(hook_summaries))

            # 4. Watchers
            watch_items = []
            for m in re.finditer(r"\bwatch\s*\(", script):
                call_text = extract_balanced(script, m.start())
                if call_text:
                    inner = call_text[call_text.find("(") + 1:].strip()
                    arg = ""
                    dp = db = dc = 0
                    for ch in inner:
                        if ch == '(':
                            dp += 1
                        elif ch == ')':
                            if dp == 0 and db == 0 and dc == 0:
                                break
                            dp -= 1
                        elif ch == '[':
                            db += 1
                        elif ch == ']':
                            db -= 1
                        elif ch == '{':
                            dc += 1
                        elif ch == '}':
                            dc -= 1
                        elif ch == ',' and dp == 0 and db == 0 and dc == 0:
                            break
                        arg += ch
                    arg = arg.strip().replace("\n", " ").replace("\t", " ")
                    if arg:
                        watch_items.append(arg)
            for m in re.finditer(r"\bwatchEffect\s*\(", script):
                watch_items.append("watchEffect")
            if watch_items:
                unique_watch = list(dict.fromkeys(watch_items))[:10]
                out.append(f"// Watchers: {', '.join(unique_watch)}")

    # Template slots
    template_m = re.search(r"<template(\s+[^>]*)?>(.*?)</template>", content, re.DOTALL)
    if template_m:
        slots = re.findall(r'<slot\s*(?:name=["\']([^"\']+)["\'])?', template_m.group(2))
        slot_names = [s if s else "default" for s in slots]
        if slot_names:
            unique_slots = list(dict.fromkeys(slot_names))
            out.append(f"// Slots: {', '.join(unique_slots)}")

    return "\n\n".join(out) if out else "// No public props/emits found in component."

def extract_php_contract(content: str, full: bool = False) -> str:
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
        traits = []
        body_items = []

        def walk(node):
            nonlocal ns, type_header
            if node.type == "namespace_definition":
                for c in node.children:
                    if c.type == "namespace_name":
                        ns = f"namespace {c.text.decode('utf-8')};"
            elif node.type in ("class_declaration", "interface_declaration", "trait_declaration"):
                type_header = node.text.decode("utf-8", errors="ignore").split("{")[0].strip()
            elif node.type in ("use_declaration", "trait_use_clause"):
                if node.parent and node.parent.type == "declaration_list":
                    t_text = node.text.decode("utf-8", errors="ignore").strip()
                    traits.append(f"    {t_text}")
            elif node.type == "property_declaration":
                p_text = node.text.decode("utf-8", errors="ignore").strip()
                if "public" in p_text and not p_text.startswith("private") and not p_text.startswith("protected"):
                    body_items.append(f"    {p_text}")
                elif full and ("protected" in p_text or any(k in p_text for k in ("$casts", "$fillable", "$guarded", "$hidden", "$table", "$with"))):
                    body_items.append(f"    {p_text}")
            elif node.type == "method_declaration":
                m_text = node.text.decode("utf-8", errors="ignore").strip()
                sig = m_text.split("{")[0].strip()
                if "public function" in sig or (not sig.startswith("private") and not sig.startswith("protected") and "function" in sig):
                    body_items.append(f"    {sig};")
                elif full and ("protected function" in sig or "protected static function" in sig):
                    body_items.append(f"    {sig};")

            for child in node.children:
                walk(child)

        walk(tree.root_node)

        if ns:
            out.append(ns)
        if type_header:
            out.append(f"{type_header} {{")
            if full and traits:
                out.extend(traits)
            out.extend(body_items)
            out.append("}")
        return "\n".join(out) if out else "// No public class or interface definitions found."

    # Regex Fallback
    out = []
    ns = re.search(r"namespace\s+([^;]+);", content)
    cls = re.search(r"((?:abstract\s+|final\s+)?(?:class|interface|trait)\s+\w+[^{]*)\{", content)
    body = content[cls.end():] if cls else content
    traits = re.findall(r"^\s*use\s+([A-Za-z0-9_,\s\\]+)\s*;", body, re.MULTILINE)
    props = re.findall(r"^\s*public\s+(?:readonly\s+)?(?:[\w\\?|]+\s+)?\$\w+[^;]*;", body, re.MULTILINE)
    methods = re.findall(r"^\s*public\s+(?:static\s+)?function\s+\w+\s*\([^)]*\)\s*(?::\s*[\w\\?|]+)?", body, re.MULTILINE)

    if ns:
        out.append(f"namespace {ns.group(1).strip()};")
    if cls:
        out.append(f"{cls.group(1).strip()} {{")
    if full and traits:
        for t in traits:
            out.append(f"    use {t.strip()};")
    for p in props:
        out.append(f"    {p.strip()}")
    if full:
        prot_props = re.findall(r"^\s*protected\s+(?:[\w\\?|]+\s+)?\$(?:casts|fillable|guarded|hidden|table)\b[^;]*;", content, re.MULTILINE)
        for pp in prot_props:
            out.append(f"    {pp.strip()}")
    for m in methods:
        out.append(f"    {m.strip()};")
    if full:
        prot_methods = re.findall(r"^\s*protected\s+(?:static\s+)?function\s+\w+\s*\([^)]*\)\s*(?::\s*[\w\\?|]+)?", content, re.MULTILINE)
        for pm in prot_methods:
            out.append(f"    {pm.strip()};")
    if cls:
        out.append("}")
    return "\n".join(out) if out else "// No public PHP contract found."

def extract_ts_js_contract(content: str, full: bool = False) -> str:
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
                if text.startswith("export") or full:
                    out.append(text)
            elif n_type in ("function_declaration", "lexical_declaration"):
                text = node.text.decode("utf-8", errors="ignore").strip()
                if text.startswith("export "):
                    sig = text.split("{")[0].strip()
                    out.append(f"{sig};")
                elif full:
                    sig = text.split("{")[0].strip()
                    if sig:
                        out.append(f"{sig};")
        return "\n\n".join(out) if out else "// No exported types or signatures found."

    # Regex fallback
    funcs = re.findall(r"^\s*export\s+(?:async\s+)?function\s+\w+\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^;{\n]+)?", content, re.MULTILINE)
    interfaces = re.findall(r"^\s*(?:export\s+)?(?:interface|type)\s+\w+[^;{\n]*\{[^}]*\}", content, re.MULTILINE | re.DOTALL)
    consts = re.findall(r"^\s*export\s+const\s+\w+\s*(?::\s*[^=]+)?", content, re.MULTILINE)
    out = []
    for i in interfaces:
        if i.strip().startswith("export") or full:
            out.append(i.strip())
    for c in consts:
        out.append(c.strip() + ";")
    for f in funcs:
        out.append(f.strip() + ";")
    return "\n\n".join(out) if out else "// No exported signatures found."

def extract_contract(target: str, cwd: str, full: bool = False) -> Dict[str, Any]:
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
            contract = extract_vue_contract(content, full=full)
            lang = "Vue 3 Component" + (" (Full Contract & Lifecycle)" if full else "")
        elif ext == ".php":
            contract = extract_php_contract(content, full=full)
            lang = "PHP Class / Interface" + (" (Full Contract & Internals)" if full else "")
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            contract = extract_ts_js_contract(content, full=full)
            lang = "TypeScript / JavaScript Module" + (" (Full Contract)" if full else "")
        else:
            contract = "// File type not supported for contract extraction."
            lang = "Unknown"

        return {
            "status": "ok",
            "target": target,
            "filepath": rel_path,
            "language": lang,
            "full": full,
            "contract": contract
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed extracting contract from {rel_path}: {str(e)}"
        }
