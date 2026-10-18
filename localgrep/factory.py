import os
import re
import glob
from typing import Dict, Any, List, Optional

def inspect_model_factory(model_name: str, cwd: str = ".") -> Dict[str, Any]:
    """Find and inspect Laravel model factory definition and custom state modifiers."""
    clean_model = model_name.strip().split("\\")[-1]
    factory_name = f"{clean_model}Factory.php"

    candidate_patterns = [
        os.path.join(cwd, "database", "factories", f"{clean_model}Factory.php"),
        os.path.join(cwd, "database", "factories", "**", f"{clean_model}Factory.php"),
        os.path.join(cwd, "vendor", "bina", "*", "database", "factories", f"{clean_model}Factory.php"),
        os.path.join(cwd, "vendor", "bina", "*", "database", "factories", "**", f"{clean_model}Factory.php")
    ]

    target_file = None
    for pat in candidate_patterns:
        matches = glob.glob(pat, recursive=True)
        if matches:
            target_file = matches[0]
            break

    if not target_file:
        # Search for any factory containing model name
        all_factories = glob.glob(os.path.join(cwd, "database", "factories", "**", "*Factory.php"), recursive=True) + \
                        glob.glob(os.path.join(cwd, "vendor", "bina", "*", "database", "factories", "**", "*Factory.php"), recursive=True)
        all_bases = [os.path.basename(f).replace("Factory.php", "") for f in all_factories]
        suggestions = [b for b in all_bases if clean_model.lower() in b.lower()]
        import difflib
        fuzzy_matches = difflib.get_close_matches(clean_model, all_bases, n=5, cutoff=0.4)
        for fm in fuzzy_matches:
            if fm not in suggestions:
                suggestions.append(fm)

        return {
            "status": "error",
            "message": f"Factory for model '{clean_model}' not found.",
            "suggestions": suggestions[:5],
            "available_suggestions": suggestions[:5]
        }

    try:
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return {"status": "error", "message": f"Could not read factory file: {str(e)}"}

    rel_path = os.path.relpath(target_file, cwd)

    # 1. Target model detection
    target_model = f"App\\Models\\{clean_model}"
    m_model = re.search(r'protected\s+\$model\s*=\s*([^;]+);', content)
    if m_model:
        target_model = m_model.group(1).strip().replace("::class", "")

    # 2. Extract definition() array keys & snippets
    definition_attributes = {}
    m_def = re.search(r'public\s+function\s+definition\s*\(\)\s*(?::\s*array)?\s*\{(.*?)\n\t*\}', content, re.DOTALL)
    if m_def:
        body = m_def.group(1)
        # Match array entries: 'key' => value or "key" => value
        attr_matches = re.finditer(r"['\"]([a-zA-Z0-9_\-]+)['\"]\s*=>\s*([^,\n]+(?:,\s*(?!\s*['\"][a-zA-Z0-9_\-]+['\"]\s*=>)[^,\n]+)*)", body)
        for am in attr_matches:
            k = am.group(1).strip()
            v = am.group(2).strip().rstrip(",")
            definition_attributes[k] = v

    # 3. Extract custom state modifier methods
    states = []
    # Match methods returning $this->state or standard state methods
    m_methods = re.finditer(r'public\s+function\s+([a-zA-Z0-9_]+)\s*\(([^\)]*)\)\s*(?::\s*static)?\s*\{(.*?)\n\t*\}', content, re.DOTALL)
    for mm in m_methods:
        fn_name = mm.group(1)
        fn_args = mm.group(2).strip()
        fn_body = mm.group(3)
        if fn_name == "definition":
            continue

        if "$this->state" in fn_body or "state(" in fn_body:
            # Extract state attributes if simple array
            state_keys = []
            m_sk = re.finditer(r"['\"]([a-zA-Z0-9_\-]+)['\"]\s*=>", fn_body)
            for sk in m_sk:
                state_keys.append(sk.group(1))

            states.append({
                "method": fn_name,
                "parameters": fn_args,
                "overrides": list(dict.fromkeys(state_keys))
            })

    return {
        "status": "ok",
        "model": target_model,
        "factory_file": rel_path,
        "definition_attributes": definition_attributes,
        "states": states
    }

def format_factory_text(res: Dict[str, Any]) -> str:
    """Format factory details into terminal card."""
    if res.get("status") != "ok":
        msg = res.get("message", "Factory not found.")
        sugg = res.get("available_suggestions", [])
        if sugg:
            msg += f"\n  Suggestions: {', '.join(sugg)}"
        return f"Error: {msg}"

    model = res.get("model", "Unknown")
    f_file = res.get("factory_file", "")
    lines = [
        f"=== Model Factory: {model} ===",
        f"File: {f_file}",
        ""
    ]

    defs = res.get("definition_attributes", {})
    if defs:
        lines.append(f"Default Attributes ({len(defs)}):")
        for k, v in defs.items():
            lines.append(f"  - {k.ljust(22)} => {v}")
    else:
        lines.append("Default Attributes: None or dynamic return")

    states = res.get("states", [])
    lines.append("")
    if states:
        lines.append(f"Custom States ({len(states)}):")
        for s in states:
            sig = f"{s['method']}({s['parameters']})"
            ovr = f" (sets {', '.join(s['overrides'])})" if s.get("overrides") else ""
            lines.append(f"  -> {sig}{ovr}")
    else:
        lines.append("Custom States: None detected in factory")

    return "\n".join(lines)
