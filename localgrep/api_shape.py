import os
import re
import subprocess
from typing import Dict, Any, List, Optional, Tuple

def resolve_controller_file(controller_name: str, cwd: str) -> str:
    """Find path to a controller PHP file."""
    clean = controller_name.replace(".php", "").split("\\")[-1]
    search_dirs = [d for d in ["app/Http/Controllers", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"*{clean}.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if res.stdout:
        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        for f in files:
            if os.path.basename(f) == f"{clean}.php":
                return os.path.join(cwd, f)
        if files:
            return os.path.join(cwd, files[0])
    return ""

def resolve_request_file(request_class: str, cwd: str) -> str:
    """Find path to a FormRequest PHP file."""
    clean = request_class.replace(".php", "").split("\\")[-1]
    search_dirs = [d for d in ["app/Http/Requests", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"*{clean}.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if res.stdout:
        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        for f in files:
            if os.path.basename(f) == f"{clean}.php":
                return os.path.join(cwd, f)
        if files:
            return os.path.join(cwd, files[0])
    return ""

def resolve_resource_file(resource_class: str, cwd: str) -> str:
    """Find path to an Eloquent Resource PHP file."""
    clean = resource_class.replace(".php", "").split("\\")[-1]
    search_dirs = [d for d in ["app/Http/Resources", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"*{clean}.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if res.stdout:
        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        for f in files:
            if os.path.basename(f) == f"{clean}.php":
                return os.path.join(cwd, f)
        if files:
            return os.path.join(cwd, files[0])
    return ""

def parse_rules_array(content: str) -> List[Dict[str, Any]]:
    """Parse validation rules into field names, types, and constraints."""
    rules = []
    # Find rules return block: return [ ... ];
    m_block = re.search(r"function\s+rules\s*\([^\)]*\)\s*(?::\s*array\s*)?\{.*?return\s*\[(.*?)\];", content, re.DOTALL)
    if not m_block:
        # Check $request->validate([ ... ])
        m_block = re.search(r"(?:->validate|\$this->validate)\s*\(\s*(?:\$request,\s*)?\[(.*?)\]\s*\)", content, re.DOTALL)

    if not m_block:
        return rules

    raw_rules = m_block.group(1)
    # Match: 'field' => ['rule1', 'rule2'] or 'field' => 'rule1|rule2'
    for rm in re.finditer(r"['\"]([a-zA-Z0-9_\.\*]+)['\"]\s*=>\s*(\[[^\]]+\]|[^\n,;]+)", raw_rules):
        field = rm.group(1)
        val_expr = rm.group(2).strip().rstrip(",").strip()

        rule_items = []
        if val_expr.startswith("[") and val_expr.endswith("]"):
            # Array of rules
            for item in re.findall(r"['\"]([^'\"]+)['\"]", val_expr):
                rule_items.append(item)
            # Check for Rule::enum(...) or Rule::exists(...)
            m_enum = re.search(r"Rule::enum\s*\(\s*([A-Za-z0-9_]+)::class\s*\)", val_expr)
            if m_enum:
                rule_items.append(f"enum:{m_enum.group(1)}")
            m_exists = re.search(r"Rule::exists\s*\(\s*['\"]([^'\"]+)['\"]", val_expr)
            if m_exists:
                rule_items.append(f"exists:{m_exists.group(1)}")
        else:
            # String separated by |
            clean_str = val_expr.strip("'\"")
            rule_items = [r.strip() for r in clean_str.split("|") if r.strip()]

        # Deduce primary type
        type_str = "string"
        constraints = []
        for r in rule_items:
            r_low = r.lower()
            if r_low in ("int", "integer"): type_str = "integer"
            elif r_low in ("numeric", "number"): type_str = "numeric"
            elif r_low in ("boolean", "bool"): type_str = "boolean"
            elif r_low in ("array",): type_str = "array"
            elif r_low in ("date", "datetime"): type_str = "date"
            elif r_low in ("file", "image"): type_str = "file"
            elif r_low in ("email",): type_str = "email"
            elif r_low.startswith("enum:"): type_str = f"enum({r.split(':', 1)[1]})"
            elif r_low in ("required", "nullable"): pass
            else:
                constraints.append(r)

        rules.append({
            "field": field,
            "type": type_str,
            "constraints": constraints,
            "required": "required" in rule_items,
            "nullable": "nullable" in rule_items
        })

    return rules

def parse_resource_schema(resource_file: str) -> List[Dict[str, str]]:
    """Parse toArray of Eloquent Resource into output schema fields."""
    if not os.path.isfile(resource_file):
        return []
    try:
        with open(resource_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        m_arr = re.search(r"function\s+toArray\s*\([^\)]*\)\s*(?::\s*array\s*)?\{.*?return\s*\[(.*?)\];", content, re.DOTALL)
        if not m_arr:
            return []

        fields = []
        for rm in re.finditer(r"['\"]([a-zA-Z0-9_]+)['\"]\s*=>\s*([^,\n;]+)", m_arr.group(1)):
            k = rm.group(1)
            v = rm.group(2).strip()
            # deduce type from expression
            if "::collection" in v:
                m_sub = re.search(r"([A-Za-z0-9_]+)::collection", v)
                t_str = f"{m_sub.group(1)}[]" if m_sub else "array"
            elif "new " in v:
                m_sub = re.search(r"new\s+([A-Za-z0-9_]+)", v)
                t_str = m_sub.group(1) if m_sub else "object"
            elif "->id" in v or "int" in v.lower():
                t_str = "int"
            elif "->is_" in v or "->has_" in v or "bool" in v.lower():
                t_str = "bool"
            elif "float" in v.lower() or "price" in k:
                t_str = "float"
            else:
                t_str = "mixed"

            fields.append({"name": k, "type": t_str})
        return fields
    except Exception:
        return []

def extract_controller_method_contract(
    controller_file: str,
    method_name: str,
    cwd: str
) -> Dict[str, Any]:
    """Parse controller method parameter types, FormRequest rules, and return resource."""
    if not os.path.isfile(controller_file):
        return {"status": "error", "message": f"Controller file '{controller_file}' not found."}

    with open(controller_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Find method definition: public function store(...)
    pattern = rf"public\s+function\s+{re.escape(method_name)}\s*\((.*?)\)"
    m_fn = re.search(pattern, content)
    if not m_fn:
        return {"status": "error", "message": f"Method '{method_name}' not found in controller."}

    params_str = m_fn.group(1)
    body_start = m_fn.end()
    # rough method body (up to next public function or 2000 chars)
    next_fn = re.search(r"\n\s*public\s+function\s+", content[body_start:])
    body = content[body_start:body_start + next_fn.start()] if next_fn else content[body_start:body_start + 2000]

    # Check for FormRequest parameter
    request_class = None
    for p in params_str.split(","):
        p_clean = p.strip()
        parts = p_clean.split()
        if len(parts) >= 2 and parts[1].startswith("$"):
            typehint = parts[0]
            if "Request" in typehint and typehint != "Request":
                request_class = typehint

    # Check for rules
    rules = []
    request_file = None
    if request_class:
        req_path = resolve_request_file(request_class, cwd)
        if req_path and os.path.isfile(req_path):
            request_file = os.path.relpath(req_path, cwd)
            with open(req_path, "r", encoding="utf-8", errors="ignore") as rf:
                rules = parse_rules_array(rf.read())
    else:
        # Check inline validation in controller method body
        rules = parse_rules_array(body)

    # Check for return Resource or Inertia::render
    inertia_page = None
    m_inertia = re.search(r"Inertia::render\(\s*['\"]([^'\"]+)['\"]", body)
    if m_inertia:
        inertia_page = m_inertia.group(1)

    resource_name = None
    resource_schema = []
    m_res = re.search(r"return\s+(?:new\s+)?([A-Za-z0-9_]+Resource)(?:::collection)?\s*\(", body)
    if m_res:
        resource_name = m_res.group(1)
        res_file = resolve_resource_file(resource_name, cwd)
        if res_file:
            resource_schema = parse_resource_schema(res_file)

    return {
        "status": "ok",
        "controller_file": os.path.relpath(controller_file, cwd),
        "method": method_name,
        "request_class": request_class,
        "request_file": request_file,
        "payload_rules": rules,
        "inertia_page": inertia_page,
        "resource_name": resource_name,
        "resource_schema": resource_schema
    }

def synthesize_api_shape(target: str, cwd: str = ".") -> Dict[str, Any]:
    """Synthesize full-stack API and Inertia contract shape in <25ms."""
    clean = target.strip()

    # Case 1: Controller@method provided
    if "@" in clean:
        parts = clean.split("@", 1)
        ctrl_name = parts[0].strip()
        method_name = parts[1].strip()
        ctrl_path = resolve_controller_file(ctrl_name, cwd)
        if not ctrl_path:
            return {"status": "error", "message": f"Controller '{ctrl_name}' not found."}

        # Look up matching route
        route_info = {}
        try:
            try:
                from localgrep.router import lookup_route
            except ImportError:
                try:
                    from .router import lookup_route
                except ImportError:
                    from router import lookup_route
            r_res = lookup_route(ctrl_name, cwd, top_k=15)
            results = r_res.get("results", []) or r_res.get("routes", [])
            for r in results:
                if r.get("action") == method_name or r.get("action") == f"{ctrl_name}@{method_name}":
                    route_info = r
                    break
            if not route_info and results:
                route_info = results[0]
        except Exception:
            pass

        contract = extract_controller_method_contract(ctrl_path, method_name, cwd)
        if contract.get("status") != "ok":
            return contract

        return {
            "status": "ok",
            "target": target,
            "route": route_info,
            "contract": contract
        }

    # Case 2: Route URI or route name provided
    route_info = None
    try:
        try:
            from localgrep.router import lookup_route
        except ImportError:
            try:
                from .router import lookup_route
            except ImportError:
                from router import lookup_route
        r_res = lookup_route(clean, cwd, top_k=1)
        results = r_res.get("results", []) or r_res.get("routes", [])
        if results:
            route_info = results[0]
    except Exception:
        pass

    if not route_info:
        return {"status": "error", "message": f"Could not map route or controller for '{target}'."}

    action = route_info.get("action", "")
    target_file = route_info.get("target_file", "")
    ctrl_file = ""

    if target_file:
        raw_f = target_file.split(":")[0]
        full_f = os.path.join(cwd, raw_f) if not os.path.isabs(raw_f) else raw_f
        if os.path.isfile(full_f):
            ctrl_file = full_f

    method_name = "index"
    if "@" in action:
        method_name = action.split("@", 1)[1]
    elif action:
        method_name = action

    if not ctrl_file and "@" in action:
        ctrl_file = resolve_controller_file(action.split("@")[0], cwd)

    if not ctrl_file or not os.path.isfile(ctrl_file):
        return {
            "status": "ok",
            "target": target,
            "route": route_info,
            "contract": {"status": "ok", "message": "Pure route closure or controller file not resolved."}
        }

    contract = extract_controller_method_contract(ctrl_file, method_name, cwd)
    return {
        "status": "ok",
        "target": target,
        "route": route_info,
        "contract": contract
    }

def format_api_shape_text(res: Dict[str, Any]) -> str:
    """Format full-stack contract card for terminal."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to synthesize API shape.')}"

    r = res.get("route", {})
    c = res.get("contract", {})

    method = r.get("method", "ANY")
    uri = r.get("uri", res.get("target"))
    name = f" [name: {r['name']}]" if r.get("name") else ""
    ctrl = f" ({c.get('controller_file')})" if c.get("controller_file") else ""
    act = r.get("action") or c.get("method") or "closure"

    lines = [
        "=== Full-Stack API / Inertia Contract Shape ===",
        f"Route: {method} {uri}{name}",
        f"Action: {act}{ctrl}"
    ]

    # Inertia Page
    page = c.get("inertia_page") or r.get("inertia_file") or r.get("inertia_component") or r.get("page")
    if page:
        lines.append(f"Inertia Page: {page}")

    # Payload Rules
    rules = c.get("payload_rules", [])
    req_class = c.get("request_class") or "FormRequest / Validation"
    lines.append("")
    if rules:
        lines.append(f"Payload ({req_class}):")
        for r_item in rules:
            constraints_str = f" ({'|'.join(r_item['constraints'])})" if r_item['constraints'] else ""
            req_str = " [required]" if r_item.get("required") else " [optional]"
            lines.append(f"  - {r_item['field']}: {r_item['type']}{constraints_str}{req_str}")
    else:
        lines.append(f"Payload ({req_class}): None (No body validation rules detected)")

    # Returns
    lines.append("")
    res_name = c.get("resource_name")
    res_schema = c.get("resource_schema", [])
    if res_name:
        lines.append(f"Returns Resource: {res_name}")
        for s in res_schema:
            lines.append(f"  - {s['name']}: {s['type']}")
    elif page:
        lines.append(f"Returns: Inertia Component -> {page}")
    else:
        lines.append("Returns: JSON Response / Redirect")

    return "\n".join(lines)
