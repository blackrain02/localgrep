import os
import re
import subprocess
from typing import Dict, Any, List, Optional, Tuple

def discover_route_files(cwd: str) -> List[str]:
    """Find all route files across Laravel core and modular packages."""
    search_dirs = [d for d in ["routes", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    try:
        res = subprocess.run(
            ["rg", "--files", "-g", "**/routes/*.php", "-g", "routes/*.php", "-g", "**/Routes/*.php"] + search_dirs,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        if res.stdout:
            return [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
    except Exception:
        pass
    return []

def parse_use_statements(content: str) -> Dict[str, str]:
    """Extract use statements into alias -> full namespace mapping."""
    uses = {}
    for m in re.finditer(r"use\s+([A-Za-z0-9_\\]+)(?:\s+as\s+([A-Za-z0-9_]+))?\s*;", content):
        full = m.group(1).strip("\\")
        alias = m.group(2) if m.group(2) else full.split("\\")[-1]
        uses[alias] = full
    return uses

def resolve_controller_action(
    controller_raw: str,
    method_name: str,
    cwd: str,
    route_file: str = "",
    use_map: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Find the controller PHP file and line number of the action method with module and namespace disambiguation."""
    if not controller_raw or controller_raw.lower() in ("closure", "null"):
        return {}

    use_map = use_map or {}
    full_class = ""
    if "\\" in controller_raw:
        parts = controller_raw.lstrip("\\").split("\\")
        prefix = parts[0]
        if prefix in use_map:
            full_class = use_map[prefix] + "\\" + "\\".join(parts[1:])
        else:
            full_class = controller_raw.lstrip("\\")
    else:
        full_class = use_map.get(controller_raw, controller_raw)

    clean_cls = full_class.split("\\")[-1] if full_class else controller_raw.split("\\")[-1]
    if not clean_cls:
        return {}

    try:
        search_dirs = [d for d in ["app", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
        if not search_dirs:
            search_dirs = ["."]

        res = subprocess.run(
            ["rg", "--files", "-g", f"{clean_cls}.php"] + search_dirs,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        if not res.stdout:
            return {}

        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        if not files:
            return {}

        route_mod = None
        r_parts = route_file.replace("\\", "/").split("/")
        if "vendor/bina" in route_file:
            try:
                bina_idx = r_parts.index("bina")
                if bina_idx + 1 < len(r_parts):
                    route_mod = r_parts[bina_idx + 1].lower()
            except ValueError:
                pass
        elif "Modules" in route_file:
            try:
                mod_idx = r_parts.index("Modules")
                if mod_idx + 1 < len(r_parts):
                    route_mod = r_parts[mod_idx + 1].lower()
            except ValueError:
                pass

        best_file = files[0]
        best_score = -1
        best_line = 1

        for cand in files:
            score = 0
            full_cand = os.path.join(cwd, cand)
            cand_norm = cand.lower().replace("\\", "/")

            if route_mod and f"/{route_mod}/" in f"/{cand_norm}/":
                score += 100
            elif route_file.startswith("routes/") and cand.startswith("app/"):
                score += 50

            if full_class:
                ns_parts = [p.lower() for p in full_class.split("\\") if len(p) > 2]
                for p in ns_parts:
                    if p in cand_norm:
                        score += 20

            line_no = 1
            if method_name and os.path.isfile(full_cand):
                try:
                    with open(full_cand, "r", encoding="utf-8", errors="ignore") as f:
                        for idx, line in enumerate(f):
                            if f"function {method_name}(" in line or f"function {method_name} (" in line:
                                line_no = idx + 1
                                score += 40
                                break
                except Exception:
                    pass

            if score > best_score:
                best_score = score
                best_file = cand
                best_line = line_no

        return {
            "target_file": best_file,
            "target_line": best_line
        }
    except Exception:
        return {}

def parse_route_block(
    block: str,
    filepath: str,
    lineno: int,
    uri_prefix: str = "",
    name_prefix: str = ""
) -> List[Dict[str, Any]]:
    """Parse a route block into one or more structured route definitions."""
    results = []

    m_match = re.search(
        r"Route::match\s*\(\s*(\[[^\]]+\]|['\"][^'\"]+['\"])\s*,\s*['\"]([^'\"]+)['\"](?:\s*,\s*(.+))?",
        block,
        re.DOTALL | re.IGNORECASE
    )
    if m_match:
        raw_methods = m_match.group(1)
        uri = m_match.group(2).strip("/")
        raw_action = m_match.group(3) if m_match.group(3) else ""
        methods = [m.strip("'\" []").upper() for m in re.findall(r"['\"]([a-zA-Z]+)[\'\"]", raw_methods)]
        http_method = "|".join(methods) if methods else "ANY"
    else:
        m_route = re.search(
            r"Route::(get|post|put|patch|delete|any|options|resource|apiResource|inertia)\s*\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*(.+))?",
            block,
            re.DOTALL | re.IGNORECASE
        )
        if not m_route:
            return []
        http_method = m_route.group(1).upper()
        uri = m_route.group(2).strip("/")
        raw_action = m_route.group(3) if m_route.group(3) else ""

    clean_uri_prefix = uri_prefix.strip("/")
    if clean_uri_prefix and uri:
        full_uri = f"/{clean_uri_prefix}/{uri}"
    elif clean_uri_prefix:
        full_uri = f"/{clean_uri_prefix}"
    elif uri:
        full_uri = f"/{uri}"
    else:
        full_uri = "/"

    controller = ""
    action_name = ""

    m_arr = re.search(r"\[\s*([A-Za-z0-9_\\]+)::class\s*,\s*['\"]([A-Za-z0-9_]+)['\"]", raw_action)
    if m_arr:
        controller = m_arr.group(1)
        action_name = m_arr.group(2)
    else:
        m_str = re.search(r"['\"]([A-Za-z0-9_\\]+)@([A-Za-z0-9_]+)['\"]", raw_action)
        if m_str:
            controller = m_str.group(1)
            action_name = m_str.group(2)
        else:
            m_single = re.search(r"([A-Za-z0-9_\\]+)::class", raw_action)
            if m_single:
                controller = m_single.group(1)
                action_name = "index" if "RESOURCE" in http_method else "__invoke"
            elif "function" in raw_action or "fn" in raw_action:
                controller = "Closure"
                action_name = "Closure"

    name = ""
    m_name = re.search(r"->name\s*\(\s*['\"]([^'\"]+)['\"]", block)
    if m_name:
        name = name_prefix + m_name.group(1)

    if http_method in ("RESOURCE", "APIRESOURCE"):
        res_name = uri.split("/")[-1]
        param = res_name.rstrip("s")
        actions = [
            ("GET", full_uri, f"{name_prefix}{res_name}.index", "index"),
            ("POST", full_uri, f"{name_prefix}{res_name}.store", "store"),
            ("GET", f"{full_uri}/{{{param}}}", f"{name_prefix}{res_name}.show", "show"),
            ("PUT|PATCH", f"{full_uri}/{{{param}}}", f"{name_prefix}{res_name}.update", "update"),
            ("DELETE", f"{full_uri}/{{{param}}}", f"{name_prefix}{res_name}.destroy", "destroy"),
        ]
        if http_method == "RESOURCE":
            actions.insert(1, ("GET", f"{full_uri}/create", f"{name_prefix}{res_name}.create", "create"))
            actions.insert(4, ("GET", f"{full_uri}/{{{param}}}/edit", f"{name_prefix}{res_name}.edit", "edit"))

        m_only = re.search(r"->only\s*\(\s*\[([^\]]+)\]", block)
        if m_only:
            allowed = set(re.findall(r"['\"]([a-zA-Z_]+)['\"]", m_only.group(1)))
            actions = [a for a in actions if a[3] in allowed]

        m_except = re.search(r"->except\s*\(\s*\[([^\]]+)\]", block)
        if m_except:
            forbidden = set(re.findall(r"['\"]([a-zA-Z_]+)['\"]", m_except.group(1)))
            actions = [a for a in actions if a[3] not in forbidden]

        for m, u, n, act in actions:
            results.append({
                "method": m,
                "uri": u,
                "name": n,
                "controller": controller,
                "action": act,
                "route_file": filepath,
                "route_line": lineno,
                "is_resource": True
            })
    else:
        results.append({
            "method": http_method,
            "uri": full_uri,
            "name": name,
            "controller": controller,
            "action": action_name,
            "route_file": filepath,
            "route_line": lineno,
            "is_resource": False
        })

    return results

def parse_route_line(line: str, filepath: str, lineno: int, cwd: str) -> Optional[Dict[str, Any]]:
    """Backward-compatible helper for single-line parsing."""
    items = parse_route_block(line, filepath, lineno)
    return items[0] if items else None

def extract_file_routes(filepath: str, cwd: str) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Extract all routes from a route file, handling groups, prefixes, and multi-line definitions."""
    full_path = os.path.join(cwd, filepath)
    if not os.path.isfile(full_path):
        return [], {}

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            lines = content.splitlines()

        use_map = parse_use_statements(content)
        routes = []
        group_stack = []
        current_brace_depth = 0

        for idx, line in enumerate(lines):
            line_str = line.strip()

            if "->group(" in line or "group(function" in line or "group([" in line:
                p_match = re.search(r"prefix\s*\(\s*['\"]([^'\"]+)['\"]", line)
                if not p_match:
                    p_match = re.search(r"['\"]prefix['\"]\s*=>\s*['\"]([^'\"]+)['\"]", line)
                uri_p = p_match.group(1).strip("/") if p_match else ""

                n_match = re.search(r"name\s*\(\s*['\"]([^'\"]+)['\"]", line)
                if not n_match:
                    n_match = re.search(r"['\"]as['\"]\s*=>\s*['\"]([^'\"]+)['\"]", line)
                name_p = n_match.group(1) if n_match else ""

                open_braces = line.count("{") - line.count("}")
                group_stack.append((current_brace_depth + open_braces, uri_p, name_p))
                current_brace_depth += open_braces
                continue

            current_brace_depth += line.count("{") - line.count("}")
            while group_stack and current_brace_depth < group_stack[-1][0]:
                group_stack.pop()

            if "Route::" in line and not ("->group(" in line or "group(function" in line):
                block = line_str
                offset = 1
                while ";" not in block and idx + offset < len(lines) and offset < 15:
                    next_l = lines[idx + offset].strip()
                    block += " " + next_l
                    offset += 1
                    if "{" in block and "Route::resource" not in block and "Route::apiResource" not in block:
                        if "function" in block or "fn" in block:
                            for lookahead in range(offset, min(offset + 30, len(lines) - idx)):
                                la_line = lines[idx + lookahead].strip()
                                if "->name(" in la_line:
                                    block += " " + la_line
                                if "});" in la_line or (la_line.endswith(";") and "}" in la_line):
                                    break
                        break

                active_uri_prefix = "/".join(g[1] for g in group_stack if g[1])
                active_name_prefix = "".join(g[2] for g in group_stack if g[2])

                parsed_items = parse_route_block(
                    block,
                    filepath,
                    idx + 1,
                    uri_prefix=active_uri_prefix,
                    name_prefix=active_name_prefix
                )
                routes.extend(parsed_items)

        return routes, use_map
    except Exception:
        return [], {}

def lookup_route(query: str, cwd: str, top_k: int = 5) -> Dict[str, Any]:
    """Search for routes matching a query across Laravel core and modular packages."""
    route_files = discover_route_files(cwd)
    if not route_files:
        return {"status": "error", "message": "No route files found."}

    q_clean = query.strip()
    target_method = None
    m_query_method = re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+(.+)$", q_clean, re.IGNORECASE)
    if m_query_method:
        target_method = m_query_method.group(1).upper()
        q_clean = m_query_method.group(2).strip()

    q_lower = q_clean.lower().strip("/").replace(" ", "")

    candidates = []

    for r_file in route_files:
        routes, use_map = extract_file_routes(r_file, cwd)
        for parsed in routes:
            score = 0.0
            uri_lower = parsed["uri"].lower().strip("/").replace(" ", "")
            name_lower = parsed["name"].lower().replace(" ", "")
            ctrl_lower = parsed["controller"].lower().replace(" ", "")
            action_lower = parsed["action"].lower().replace(" ", "")

            if target_method:
                methods = parsed["method"].split("|")
                if target_method in methods:
                    score += 8.0
                elif "ANY" in methods:
                    score += 3.0
                else:
                    continue

            if q_lower == uri_lower:
                score += 40.0
            elif q_lower == name_lower:
                score += 38.0
            elif q_lower in uri_lower:
                score += 20.0
            elif q_lower in name_lower:
                score += 18.0
            elif q_lower in ctrl_lower:
                score += 14.0
            elif q_lower in action_lower:
                score += 10.0

            q_words = re.findall(r"[a-zA-Z0-9]+", q_clean.lower())
            for w in q_words:
                if w in uri_lower:
                    score += 5.0
                if w in name_lower:
                    score += 4.0
                if w in ctrl_lower:
                    score += 2.0

            if score > 0.0:
                candidates.append((score, parsed, use_map))

    if not candidates:
        return {"status": "ok", "query": query, "results": []}

    candidates.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    unique_results = []

    for score, r, u_map in candidates:
        key = (r["method"], r["uri"], r["name"], r["controller"], r["action"])
        if key not in seen:
            seen.add(key)
            ctrl_info = resolve_controller_action(
                r["controller"],
                r["action"],
                cwd,
                route_file=r["route_file"],
                use_map=u_map
            )
            r["target_file"] = ctrl_info.get("target_file", "")
            r["target_line"] = ctrl_info.get("target_line", 1)
            r["score"] = round(score, 1)
            unique_results.append(r)

        if len(unique_results) >= top_k:
            break

    return {"status": "ok", "query": query, "results": unique_results}
