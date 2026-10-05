import os
import re
import subprocess
from typing import Dict, Any, List, Optional

def resolve_target_info(target: str, cwd: str) -> Dict[str, Any]:
    """Determine whether target is a file or a symbol, and extract relevant names."""
    clean = target.strip()
    full_path = os.path.join(cwd, clean) if not os.path.isabs(clean) else clean

    if os.path.isfile(full_path):
        rel_path = os.path.relpath(full_path, cwd)
        base_name = os.path.basename(rel_path)
        sym_name = os.path.splitext(base_name)[0]
        return {
            "type": "file",
            "file": rel_path,
            "symbol": sym_name,
            "raw_target": clean
        }

    # Check for Class::method or Class->method
    if "::" in clean:
        parts = clean.split("::", 1)
        return {
            "type": "class_method",
            "class": parts[0].strip(),
            "symbol": parts[1].strip(),
            "raw_target": clean
        }
    if "->" in clean:
        parts = clean.split("->", 1)
        return {
            "type": "class_method",
            "class": parts[0].strip(),
            "symbol": parts[1].strip(),
            "raw_target": clean
        }

    # Assume symbol (function, method, prop, or class)
    return {
        "type": "symbol",
        "symbol": clean,
        "raw_target": clean
    }

def find_affected_tests(target_file: Optional[str], symbol: str, cwd: str) -> List[str]:
    """Find tests related to the file or symbol."""
    tests = set()
    if target_file:
        try:
            from localgrep.test_map import map_test_for_file
        except ImportError:
            try:
                from .test_map import map_test_for_file
            except ImportError:
                from test_map import map_test_for_file
        try:
            res = map_test_for_file(target_file, cwd)
            for m in res.get("matched_tests", [])[:5]:
                tests.add(m["test_file"])
        except Exception:
            pass

    # Grep test directories for the symbol
    test_dirs = [d for d in ["tests", "vendor/bina"] if os.path.isdir(os.path.join(cwd, d))]
    if test_dirs and len(symbol) >= 3:
        cmd = [
            "rg", "-l",
            "-g", "*Test.php",
            "-g", "*.spec.ts",
            "-g", "*.test.ts",
            "-F", symbol
        ] + test_dirs
        try:
            p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode == 0:
                for line in p.stdout.strip().split("\n"):
                    line = line.strip()
                    if line:
                        tests.add(os.path.relpath(os.path.join(cwd, line), cwd) if not line.startswith("tests") else line)
        except Exception:
            pass

    return sorted(list(tests))[:8]

def find_associated_routes(symbol: str, target_file: Optional[str], cwd: str) -> List[Dict[str, Any]]:
    """Find routes pointing to this controller, action, or resource."""
    routes = []
    try:
        try:
            from localgrep.router import lookup_route
        except ImportError:
            try:
                from .router import lookup_route
            except ImportError:
                from router import lookup_route
        query = symbol
        if target_file and "Controller" in target_file:
            query = os.path.basename(target_file).replace(".php", "")
        res = lookup_route(query, cwd, top_k=6)
        if res.get("status") == "ok":
            for r in res.get("routes", []):
                routes.append({
                    "method": r.get("method", "GET"),
                    "uri": r.get("uri", ""),
                    "name": r.get("name", ""),
                    "action": r.get("action", ""),
                    "page": r.get("page", "")
                })
    except Exception:
        pass
    return routes

def calculate_impact(target: str, cwd: str = ".") -> Dict[str, Any]:
    """Calculate blast radius and downstream dependencies across PHP and Vue/TS."""
    target_info = resolve_target_info(target, cwd)
    symbol = target_info.get("symbol", target)
    target_file = target_info.get("file")

    # If target is Class::method or Class, locate the file defining the class
    class_name = target_info.get("class") or (symbol if symbol[:1].isupper() else "")
    if class_name and not target_file:
        try:
            try:
                from localgrep.schema import resolve_model_file
            except ImportError:
                try:
                    from .schema import resolve_model_file
                except ImportError:
                    from schema import resolve_model_file
            m_file = resolve_model_file(class_name, cwd)
            if m_file:
                target_file = m_file
        except Exception:
            pass

    # 1. Direct callers via callers.py
    callers_res = {}
    try:
        try:
            from localgrep.callers import find_callers
        except ImportError:
            try:
                from .callers import find_callers
            except ImportError:
                from callers import find_callers
        search_sym = symbol
        callers_res = find_callers(search_sym, cwd, top_k=60)
    except Exception as e:
        callers_res = {"status": "error", "message": str(e), "results": []}

    all_callers = callers_res.get("results", [])
    total_callers = callers_res.get("total", len(all_callers))
    files_count = callers_res.get("files_count", len(set(c.get("file", "") for c in all_callers)))

    # Categorize callers
    vue_callers = []
    php_controller_callers = []
    backend_callers = []

    for c in all_callers:
        fp = c.get("file", "")
        if fp.endswith(".vue") or fp.endswith(".ts") or fp.endswith(".js"):
            vue_callers.append(c)
        elif "Controller" in fp:
            php_controller_callers.append(c)
        else:
            backend_callers.append(c)

    # 2. Associated Routes
    routes = find_associated_routes(symbol, target_file, cwd)

    # 3. Affected Tests
    tests = find_affected_tests(target_file, symbol, cwd)

    # 4. Blast Radius Assessment
    total_callers = len(all_callers)
    total_routes = len(routes)
    total_tests = len(tests)

    risk_score = total_callers * 2 + total_routes * 3 + total_tests
    if risk_score >= 25 or total_callers >= 15:
        risk_level = "HIGH"
    elif risk_score >= 8 or total_callers >= 4 or total_routes >= 2:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "status": "ok",
        "target": target,
        "target_file": target_file,
        "symbol": symbol,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "total_callers": total_callers,
        "vue_callers": vue_callers,
        "controller_callers": php_controller_callers,
        "backend_callers": backend_callers,
        "routes": routes,
        "affected_tests": tests
    }

def format_impact_text(res: Dict[str, Any]) -> str:
    """Format impact results into an executive CLI blast radius card."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to calculate impact.')}"

    target = res.get("target")
    risk = res.get("risk_level", "LOW")
    lines = [
        f"=== Blast Radius Analysis for: {target} [Risk: {risk}] ==="
    ]
    if res.get("target_file"):
        lines.append(f"Source File: {res['target_file']}")
    lines.append("")

    total_callers = res.get("total_callers", 0)
    lines.append(f"Direct Callers / References ({total_callers}):")

    vue_callers = res.get("vue_callers", [])
    if vue_callers:
        lines.append("  Frontend (Vue / TS):")
        for c in vue_callers[:8]:
            ctx = f" ({c['context']})" if c.get("context") else ""
            lines.append(f"    - {c['file']}:{c['line']}{ctx}")

    ctrl_callers = res.get("controller_callers", [])
    if ctrl_callers:
        lines.append("  HTTP / Controllers:")
        for c in ctrl_callers[:8]:
            ctx = f" ({c['context']})" if c.get("context") else ""
            lines.append(f"    - {c['file']}:{c['line']}{ctx}")

    backend_callers = res.get("backend_callers", [])
    if backend_callers:
        lines.append("  Backend (Models / Services / Jobs):")
        for c in backend_callers[:8]:
            ctx = f" ({c['context']})" if c.get("context") else ""
            lines.append(f"    - {c['file']}:{c['line']}{ctx}")

    if total_callers == 0:
        lines.append("    (No direct call sites found in application code)")

    routes = res.get("routes", [])
    lines.append("")
    if routes:
        lines.append(f"Associated Routes ({len(routes)}):")
        for r in routes[:5]:
            name_str = f" [name: {r['name']}]" if r.get("name") else ""
            action_str = f" -> {r['action']}" if r.get("action") else ""
            page_str = f" -> {r['page']}" if r.get("page") else ""
            lines.append(f"  - {r['method']} {r['uri']}{name_str}{action_str}{page_str}")
    else:
        lines.append("Associated Routes: None directly mapped")

    tests = res.get("affected_tests", [])
    lines.append("")
    if tests:
        lines.append(f"Affected Tests ({len(tests)}):")
        for t in tests[:6]:
            lines.append(f"  - {t}")
    else:
        lines.append("Affected Tests: None found")

    return "\n".join(lines)
