import os
import re
import sys
import time
import subprocess
from typing import Dict, Any, List

PHP_BUILTINS = {
    "Exception", "Throwable", "Error", "TypeError", "ValueError", "InvalidArgumentException",
    "RuntimeException", "LogicException", "OutOfBoundsException", "OverflowException",
    "UnderflowException", "BadMethodCallException", "Closure", "Generator", "stdClass",
    "DateTime", "DateTimeImmutable", "DateTimeInterface", "DateInterval", "DatePeriod",
    "Carbon", "Collection", "Model", "Builder", "Request", "Response", "Route", "DB", "Log",
    "Cache", "Storage", "Auth", "Event", "Queue", "Schema", "Validator", "Str", "Arr", "File",
    "self", "static", "parent", "void", "string", "int", "float", "bool", "array", "object",
    "callable", "iterable", "mixed", "null", "false", "true", "never"
}

VOID_HTML_TAGS = {"img", "input", "br", "hr", "meta", "link", "source", "track", "wbr", "col", "area", "base"}

def lint_php(filepath: str, lines: List[str]) -> List[Dict[str, Any]]:
    issues = []
    # 1. php -l syntax check (<5ms)
    try:
        proc = subprocess.run(
            ["php", "-l", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            line_match = re.search(r'on line (\d+)', err)
            line_no = int(line_match.group(1)) if line_match else 1
            # Clean message
            clean_msg = err.replace(filepath, os.path.basename(filepath)).split("Errors parsing")[0].strip()
            issues.append({
                "line": line_no,
                "message": clean_msg,
                "severity": "error"
            })
            return issues # Don't bother with unimported if syntax error exists
    except Exception as e:
        issues.append({
            "line": 1,
            "message": f"Failed running php -l: {str(e)}",
            "severity": "warning"
        })

    # 2. Check unimported classes
    full_text = "".join(lines)
    # Extract declared use imports
    imported_classes = set()
    for m in re.finditer(r'^\s*use\s+([A-Za-z0-9_\\]+)(?:\s+as\s+([A-Za-z0-9_]+))?\s*;', full_text, re.MULTILINE):
        alias = m.group(2)
        fqcn = m.group(1)
        name = alias if alias else fqcn.split("\\")[-1]
        imported_classes.add(name)

    # Check namespace
    ns_match = re.search(r'^\s*namespace\s+([^;]+);', full_text, re.MULTILINE)
    current_ns = ns_match.group(1).strip() if ns_match else ""

    # Check class name declared in file
    decl_match = re.search(r'^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+([A-Za-z0-9_]+)', full_text, re.MULTILINE)
    current_class = decl_match.group(1) if decl_match else ""

    # Find referenced classes: new ClassName, ClassName::, or catch (ClassName $e)
    # Exclude strings, comments, and fully-qualified names (\App\Models\...)
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*") or stripped.startswith("#"):
            continue

        # Strip string literals so translation keys like "customers::admin.user" are not treated as code
        code_only = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', line)

        # new SomeClass
        for m in re.finditer(r'\bnew\s+([A-Za-z0-9_]+)\b', code_only):
            cls_name = m.group(1)
            if cls_name not in PHP_BUILTINS and cls_name not in imported_classes and cls_name != current_class:
                issues.append({
                    "line": idx,
                    "message": f"Referenced class '{cls_name}' (via 'new {cls_name}') is not imported in 'use' statements.",
                    "severity": "warning"
                })

        # SomeClass::something
        for m in re.finditer(r'(?<![\\A-Za-z0-9_])([A-Za-z0-9_]+)::[A-Za-z0-9_\$]', code_only):
            cls_name = m.group(1)
            if cls_name not in PHP_BUILTINS and cls_name not in imported_classes and cls_name != current_class:
                issues.append({
                    "line": idx,
                    "message": f"Static access on class '{cls_name}::' but class is not imported in 'use' statements.",
                    "severity": "warning"
                })

    return issues

def lint_vue(filepath: str, lines: List[str]) -> List[Dict[str, Any]]:
    issues = []
    full_text = "".join(lines)

    # 1. Check primary block closures
    for tag in ("template", "script", "style"):
        open_tags = len(re.findall(rf'<{tag}(\s+[^>]*)?>', full_text, re.IGNORECASE))
        close_tags = len(re.findall(rf'</{tag}>', full_text, re.IGNORECASE))
        if open_tags != close_tags:
            issues.append({
                "line": 1,
                "message": f"Mismatched <{tag}> tags: found {open_tags} opening vs {close_tags} closing tags.",
                "severity": "error"
            })

    # 2. Template tag balancing
    root_start = re.search(r'<template(\s+[^>]*)?>', full_text, re.IGNORECASE)
    if root_start:
        script_start = re.search(r'<script', full_text, re.IGNORECASE)
        limit = script_start.start() if script_start else len(full_text)
        t_closings = [m for m in re.finditer(r'</template>', full_text, re.IGNORECASE) if m.start() < limit]
        if t_closings:
            root_end = t_closings[-1]
            raw_content = full_text[root_start.end():root_end.start()]
            t_start_line = full_text[:root_start.end()].count('\n') + 1

            # Strip HTML comments so commented tags don't affect stack
            t_content = re.sub(r'<!--[\s\S]*?-->', lambda m: '\n' * m.group(0).count('\n'), raw_content)

            stack = []
            tag_regex = re.compile(r'<(/)?([A-Za-z0-9_:-]+)(?:[^>]*?(?:(\/)>|>))')
            for match in tag_regex.finditer(t_content):
                is_closing = bool(match.group(1))
                tag_name = match.group(2)
                is_self_closing = match.group(3) == "/"
                line_in_t = t_start_line + t_content[:match.start()].count('\n')

                if is_self_closing or tag_name.lower() in VOID_HTML_TAGS:
                    continue

                if not is_closing:
                    stack.append((tag_name, line_in_t))
                else:
                    if stack and stack[-1][0].lower() == tag_name.lower():
                        stack.pop()
                    elif stack:
                        prev_tag, prev_line = stack.pop()
                        issues.append({
                            "line": line_in_t,
                            "message": f"Mismatched closing tag </{tag_name}> (expected </{prev_tag}> from line {prev_line}).",
                            "severity": "error"
                        })
                        break

            if stack:
                unclosed, unclosed_line = stack[-1]
                issues.append({
                    "line": unclosed_line,
                    "message": f"Unclosed Vue template tag <{unclosed}> at line {unclosed_line}.",
                    "severity": "error"
                })

    return issues

def lint_python(filepath: str, lines: List[str]) -> List[Dict[str, Any]]:
    issues = []
    try:
        import py_compile
        py_compile.compile(filepath, doraise=True)
    except py_compile.PyCompileError as e:
        msg = str(e)
        line_match = re.search(r', line (\d+)', msg)
        line_no = int(line_match.group(1)) if line_match else 1
        issues.append({
            "line": line_no,
            "message": f"Python SyntaxError: {msg.splitlines()[-1]}",
            "severity": "error"
        })
    except Exception as e:
        issues.append({
            "line": 1,
            "message": str(e),
            "severity": "error"
        })
    return issues

def lint_fast_file(filepath: str, cwd: str = ".") -> Dict[str, Any]:
    start_t = time.perf_counter()
    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.isfile(full_path):
        return {
            "status": "error",
            "message": f"File not found: {filepath}",
            "issues": []
        }

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        return {"status": "error", "message": str(e), "issues": []}

    ext = os.path.splitext(full_path)[1].lower()
    issues: List[Dict[str, Any]] = []

    if ext == ".php":
        issues = lint_php(full_path, lines)
    elif ext == ".vue":
        issues = lint_vue(full_path, lines)
    elif ext == ".py":
        issues = lint_python(full_path, lines)

    elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
    has_error = any(i["severity"] == "error" for i in issues)

    return {
        "status": "clean" if not issues else ("error" if has_error else "warning"),
        "filepath": os.path.relpath(full_path, cwd),
        "issues_count": len(issues),
        "issues": issues,
        "elapsed_ms": f"{elapsed_ms}ms"
    }
