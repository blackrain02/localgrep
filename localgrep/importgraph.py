import os
import re
import glob
from typing import Dict, Any, List

def analyze_import_graph(target_file: str, cwd: str = ".") -> Dict[str, Any]:
    """Build bidirectional AST import/export graph for a file across the workspace."""
    # Resolve target file
    norm = target_file.strip().replace("\\", "/")
    full_path = os.path.join(cwd, norm) if not os.path.isabs(norm) else norm

    if not os.path.isfile(full_path):
        # Search by basename
        target_base = os.path.basename(norm)
        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "storage", "dist", "public")]
            if target_base in files:
                full_path = os.path.join(root, target_base)
                break

    if not os.path.isfile(full_path):
        return {"status": "error", "message": f"Target file '{target_file}' not found."}

    rel_path = os.path.relpath(full_path, cwd).replace("\\", "/")
    is_frontend = rel_path.endswith((".ts", ".js", ".vue"))
    is_php = rel_path.endswith(".php")

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return {"status": "error", "message": f"Could not read file: {str(e)}"}

    exports = []
    imports = []

    if is_frontend:
        # Extract named exports
        for m in re.finditer(r'export\s+(?:async\s+)?(?:function|const|let|var|class|type|interface)\s+([a-zA-Z0-9_\-]+)', content):
            exports.append(m.group(1))
        # Export default
        if re.search(r'export\s+default\b', content):
            exports.append("default")
        # Export list: export { a, b, c }
        for m in re.finditer(r'export\s*\{([^}]+)\}', content):
            for item in m.group(1).split(","):
                clean = item.strip().split(" as ")[-1].strip()
                if clean:
                    exports.append(clean)

        # Extract imported dependencies
        for m in re.finditer(r'import\s+(?:\{([^}]+)\}|([a-zA-Z0-9_\*\s,]+))?\s*from\s*[\'"]([^\'"]+)[\'"]', content):
            symbols = (m.group(1) or m.group(2) or "").strip()
            source = m.group(3).strip()
            imports.append({
                "source": source,
                "symbols": [s.strip().split(" as ")[0].strip() for s in symbols.split(",") if s.strip()] if symbols else []
            })
    elif is_php:
        # Extract class name
        m_class = re.search(r'(?:class|interface|trait|enum)\s+([a-zA-Z0-9_]+)', content)
        if m_class:
            exports.append(m_class.group(1))

        # Extract use statements
        for m in re.finditer(r'use\s+([A-Za-z0-9_\\]+)(?:\s+as\s+([a-zA-Z0-9_]+))?;', content):
            full_use = m.group(1).strip()
            alias = m.group(2) or full_use.split("\\")[-1]
            imports.append({
                "source": full_use,
                "symbols": [alias]
            })

    # Find consumers (who imports or references this file)
    consumers = []
    target_stem = os.path.splitext(os.path.basename(rel_path))[0]
    subpaths_to_match = [
        target_stem,
        rel_path.replace("resources/js/", "@/"),
        rel_path
    ]

    # Fast search via ripgrep if available
    import subprocess
    query_pattern = f"\\b{re.escape(target_stem)}\\b"
    try:
        rg_cmd = [
            "rg", "--files-with-matches",
            "--glob", "!*.min.js",
            "--glob", "!dist/**",
            "--glob", "!public/**",
            "--glob", "!storage/**",
            "--glob", "!node_modules/**",
            "--glob", "!resources/js/ziggy*.js",
            query_pattern, cwd
        ]
        res = subprocess.run(rg_cmd, capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                c_rel = os.path.relpath(line.strip(), cwd).replace("\\", "/")
                if c_rel != rel_path:
                    consumers.append(c_rel)
    except Exception:
        pass

    return {
        "status": "ok",
        "file": rel_path,
        "is_frontend": is_frontend,
        "is_php": is_php,
        "exports": list(dict.fromkeys(exports)),
        "dependencies": imports,
        "consumers": consumers[:25],
        "total_consumers": len(consumers)
    }

def format_importgraph_text(res: Dict[str, Any]) -> str:
    """Format import graph card."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to trace imports.')}"

    f_path = res.get("file", "")
    exports = res.get("exports", [])
    deps = res.get("dependencies", [])
    consumers = res.get("consumers", [])
    tot_consumers = res.get("total_consumers", len(consumers))

    lines = [
        f"=== Bidirectional Import Graph: {f_path} ===",
        ""
    ]

    if exports:
        lines.append(f"Exported Symbols ({len(exports)}):")
        lines.append(f"  -> {', '.join(exports)}")
    else:
        lines.append("Exported Symbols: None detected")

    lines.append("")
    if deps:
        lines.append(f"Direct Dependencies ({len(deps)}):")
        for d in deps[:15]:
            syms = f" ({', '.join(d['symbols'][:3])})" if d.get("symbols") else ""
            lines.append(f"  -> {d['source']}{syms}")
        if len(deps) > 15:
            lines.append(f"  ... and {len(deps) - 15} more dependencies")
    else:
        lines.append("Direct Dependencies: None")

    lines.append("")
    if consumers:
        lines.append(f"Consumers / Inbound Importers ({tot_consumers} files):")
        for c in consumers[:15]:
            lines.append(f"  <- {c}")
        if tot_consumers > 15:
            lines.append(f"  ... and {tot_consumers - 15} more consumers")
    else:
        lines.append("Consumers: 0 direct inbound importers detected")

    return "\n".join(lines)
