import os
import re
import subprocess
from typing import Dict, Any, List

def discover_route_files(cwd: str) -> List[str]:
    """Find all route files across Laravel core and modular packages."""
    search_dirs = [d for d in ["routes", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    try:
        res = subprocess.run(
            ["rg", "--files", "-g", "**/routes/*.php", "-g", "routes/*.php"] + search_dirs,
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

def resolve_controller_action(controller_class: str, method_name: str, cwd: str) -> Dict[str, Any]:
    """Find the controller PHP file and the line number of the action method."""
    clean_cls = controller_class.split("\\")[-1]
    if not clean_cls:
        return {}

    try:
        search_dirs = [d for d in ["app", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
        res = subprocess.run(
            ["rg", "--files", "-g", f"*{clean_cls}.php"] + search_dirs,
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

        target_file = files[0]
        full_path = os.path.join(cwd, target_file)

        action_line = 1
        if method_name and os.path.isfile(full_path):
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    if f"function {method_name}(" in line or f"function {method_name} (" in line:
                        action_line = idx + 1
                        break

        return {
            "target_file": target_file,
            "target_line": action_line
        }
    except Exception:
        return {}

def parse_route_line(line: str, filepath: str, lineno: int, cwd: str) -> Dict[str, Any]:
    """Parse a single Laravel Route definition line into a structured route dict."""
    m_route = re.search(r"Route::(get|post|put|patch|delete|any|options|resource|apiResource|inertia)\s*\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*(.+))?", line, re.IGNORECASE)
    if not m_route:
        return None

    http_method = m_route.group(1).upper()
    uri = m_route.group(2).strip("/")
    raw_action = m_route.group(3) if m_route.group(3) else ""

    controller = ""
    action_name = ""

    # 1. Array syntax: [OrderController::class, 'index']
    m_arr = re.search(r"\[\s*([A-Za-z0-9_\\]+)::class\s*,\s*['\"]([A-Za-z0-9_]+)['\"]", raw_action)
    if m_arr:
        controller = m_arr.group(1)
        action_name = m_arr.group(2)
    else:
        # 2. String syntax: 'OrderController@index'
        m_str = re.search(r"['\"]([A-Za-z0-9_\\]+)@([A-Za-z0-9_]+)['\"]", raw_action)
        if m_str:
            controller = m_str.group(1)
            action_name = m_str.group(2)
        else:
            # 3. Single controller syntax: OrderController::class
            m_single = re.search(r"([A-Za-z0-9_\\]+)::class", raw_action)
            if m_single:
                controller = m_single.group(1)
                action_name = "index" if "Resource" in http_method else "__invoke"

    # Route Name: ->name('orders.index')
    name = ""
    m_name = re.search(r"->name\s*\(\s*['\"]([^'\"]+)['\"]", line)
    if m_name:
        name = m_name.group(1)

    return {
        "method": http_method,
        "uri": "/" + uri if uri else "/",
        "name": name,
        "controller": controller,
        "action": action_name,
        "route_file": filepath,
        "route_line": lineno
    }

def lookup_route(query: str, cwd: str, top_k: int = 5) -> Dict[str, Any]:
    route_files = discover_route_files(cwd)
    if not route_files:
        return {
            "status": "error",
            "message": "No route files found in project."
        }

    q_clean = query.strip()
    target_method = None
    m_query_method = re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+(.+)$", q_clean, re.IGNORECASE)
    if m_query_method:
        target_method = m_query_method.group(1).upper()
        q_clean = m_query_method.group(2).strip()

    q_lower = q_clean.lower().strip("/").replace(" ", "")

    candidates = []

    for r_file in route_files:
        full_path = os.path.join(cwd, r_file)
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    if "Route::" in line:
                        parsed = parse_route_line(line, r_file, idx + 1, cwd)
                        if not parsed:
                            continue

                        score = 0.0
                        uri_lower = parsed["uri"].lower().strip("/").replace(" ", "")
                        name_lower = parsed["name"].lower().replace(" ", "")
                        ctrl_lower = parsed["controller"].lower().replace(" ", "")
                        action_lower = parsed["action"].lower().replace(" ", "")

                        # Method boost
                        if target_method and parsed["method"] == target_method:
                            score += 5.0
                        elif target_method and parsed["method"] not in (target_method, "ANY"):
                            continue

                        # Match scoring
                        if q_lower == uri_lower:
                            score += 35.0
                        elif q_lower == name_lower:
                            score += 30.0
                        elif q_lower in uri_lower:
                            score += 18.0
                        elif q_lower in name_lower:
                            score += 15.0
                        elif q_lower in ctrl_lower:
                            score += 12.0
                        elif q_lower in action_lower:
                            score += 8.0

                        # Multi-word query tokens
                        q_words = re.findall(r"[a-zA-Z0-9]+", q_clean.lower())
                        for w in q_words:
                            if w in uri_lower:
                                score += 4.0
                            if w in name_lower:
                                score += 3.0
                            if w in ctrl_lower:
                                score += 2.0

                        if score > 0.0:
                            candidates.append((score, parsed))
        except Exception:
            continue

    if not candidates:
        return {
            "status": "ok",
            "query": query,
            "results": []
        }

    candidates.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    unique_results = []

    for score, r in candidates:
        key = (r["method"], r["uri"], r["name"], r["controller"])
        if key not in seen:
            seen.add(key)

            # Resolve controller action location
            ctrl_info = resolve_controller_action(r["controller"], r["action"], cwd)
            r["target_file"] = ctrl_info.get("target_file", "")
            r["target_line"] = ctrl_info.get("target_line", 1)
            r["score"] = round(score, 1)
            unique_results.append(r)

        if len(unique_results) >= top_k:
            break

    return {
        "status": "ok",
        "query": query,
        "results": unique_results
    }
