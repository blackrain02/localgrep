import os
import re
import subprocess
from typing import Dict, Any, List, Optional

def find_target_file(name: str, cwd: str) -> Optional[str]:
    """Find source file matching the target name or basename with common extensions."""
    clean = name.strip()
    direct = os.path.join(cwd, clean) if not os.path.isabs(clean) else clean
    if os.path.isfile(direct):
        return os.path.relpath(direct, cwd)

    base = os.path.basename(clean)
    candidates = [base]
    for ext in (".ts", ".js", ".vue", ".php"):
        if not base.endswith(ext):
            candidates.append(base + ext)

    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "storage", "dist", "public")]
        for c in candidates:
            if c in files:
                full = os.path.join(root, c)
                return os.path.relpath(full, cwd)
    return None

def extract_exported_symbols(file_path: str, cwd: str) -> List[str]:
    """Extract exported functions, constants, classes and public methods from a source file."""
    full_path = os.path.join(cwd, file_path) if not os.path.isabs(file_path) else file_path
    if not os.path.isfile(full_path):
        return []

    exports = []
    base_no_ext = os.path.splitext(os.path.basename(file_path))[0]
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        ts_matches = re.findall(r'export\s+(?:async\s+)?(?:function|const|let|var|class|type|interface)\s+([A-Za-z0-9_]+)', content)
        for tm in ts_matches:
            if tm not in exports:
                exports.append(tm)

        def_match = re.search(r'export\s+default\s+([A-Za-z0-9_]+)', content)
        if def_match:
            dm = def_match.group(1)
            if dm not in exports and dm not in ("function", "class"):
                exports.append(dm)

        php_matches = re.findall(r'public\s+function\s+([A-Za-z0-9_]+)', content)
        for pm in php_matches:
            if pm not in exports and not pm.startswith("__"):
                exports.append(pm)
    except Exception:
        pass

    if base_no_ext not in exports:
        exports.append(base_no_ext)

    return exports

def find_module_importers(file_path: str, cwd: str) -> List[Dict[str, Any]]:
    """Find files that import this module by name or path."""
    importers = []
    base_no_ext = os.path.splitext(os.path.basename(file_path))[0]
    import_regex = rf"""from\s+['"][^'"]*[/]{re.escape(base_no_ext)}(?:\.[a-zA-Z]+)?['"]"""
    search_dirs = [d for d in ("resources", "app", "vendor/bina") if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]
    try:
        cmd = ["rg", "-n", "-e", import_regex] + search_dirs
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if p.returncode == 0 and p.stdout:
            for line in p.stdout.strip().split("\n"):
                m = re.match(r"^([^:]+):(\d+):(.*)$", line.strip())
                if m:
                    f_rel = os.path.relpath(os.path.join(cwd, m.group(1)), cwd)
                    ln = int(m.group(2))
                    code = m.group(3).strip()
                    importers.append({
                        "file": f_rel,
                        "line": ln,
                        "code": code,
                        "context": f"import from {base_no_ext}"
                    })
    except Exception:
        pass
    return importers

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

def check_target_exists(target: str, symbol: str, target_file: Optional[str], cwd: str) -> bool:
    if target_file and os.path.isfile(os.path.join(cwd, target_file)):
        return True

    for ext in (".php", ".vue", ".ts", ".js"):
        if os.path.isfile(os.path.join(cwd, f"{symbol}{ext}")):
            return True
        for d in ("app/Models", "app/Services", "app/Http/Controllers", "resources/js/Pages", "resources/js/Components"):
            if os.path.isfile(os.path.join(cwd, d, f"{symbol}{ext}")):
                return True

    decl_regex = rf"\b(class|interface|trait|function|enum)\s+{re.escape(symbol)}\b"
    search_dirs = [d for d in ("app", "resources", "vendor/bina", "routes", "config") if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]
    try:
        p = subprocess.run(
            ["rg", "-m", "1", "-e", decl_regex] + search_dirs,
            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
        if p.returncode == 0:
            return True
    except Exception:
        pass

    try:
        p = subprocess.run(
            ["rg", "-m", "1", "-w", symbol] + search_dirs,
            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
        if p.returncode == 0:
            return True
    except Exception:
        pass

    return False

def calculate_impact(target: str, cwd: str = ".") -> Dict[str, Any]:
    """Calculate blast radius and downstream dependencies across PHP and Vue/TS."""
    target_info = resolve_target_info(target, cwd)
    symbol = target_info.get("symbol", target)
    target_file = target_info.get("file")

    if not target_file:
        resolved_f = find_target_file(symbol, cwd)
        if resolved_f:
            target_file = resolved_f

    if not check_target_exists(target, symbol, target_file, cwd):
        return {
            "status": "not_found",
            "target": target,
            "message": f"Symbol or file '{target}' not found in codebase (no definition or references detected)."
        }

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

    # Gather callers across symbols & module imports
    all_callers = []
    seen_call_keys = set()

    def add_callers(callers_list):
        for c in callers_list:
            key = (c.get("file"), c.get("line"))
            if key not in seen_call_keys:
                seen_call_keys.add(key)
                all_callers.append(c)

    # 1. If target_file is identified, extract exported symbols and find their callers + direct importers
    if target_file and any(target_file.endswith(ext) for ext in (".ts", ".js", ".vue", ".php")):
        mod_importers = find_module_importers(target_file, cwd)
        add_callers(mod_importers)

        exported_syms = extract_exported_symbols(target_file, cwd)
        try:
            from localgrep.callers import find_callers
        except ImportError:
            try:
                from .callers import find_callers
            except ImportError:
                from callers import find_callers

        for exp in exported_syms:
            if len(exp) >= 3 and exp != symbol:
                try:
                    c_res = find_callers(exp, cwd, top_k=30)
                    add_callers(c_res.get("results", []))
                except Exception:
                    pass

    # Direct symbol callers
    try:
        from localgrep.callers import find_callers
    except ImportError:
        try:
            from .callers import find_callers
        except ImportError:
            from callers import find_callers

    try:
        c_res = find_callers(symbol, cwd, top_k=60)
        add_callers(c_res.get("results", []))
    except Exception:
        pass

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
