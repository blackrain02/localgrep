import os
import re
import subprocess
from typing import Dict, Any, List, Optional

DEBUG_PATTERNS = [
    (re.compile(r'\b(dd|dump|ray|var_dump|print_r)\s*\('), "PHP debug statement", "warning"),
    (re.compile(r'\b(die|exit)\s*[\(;]'), "PHP termination statement", "warning"),
    (re.compile(r'\bconsole\.(log|debug|info|trace|table)\s*\('), "JavaScript console logging", "warning"),
    (re.compile(r'\bdebugger\b;?'), "JavaScript debugger statement", "error"),
    (re.compile(r'\b(breakpoint\(\)|pdb\.set_trace\(\)|import\s+pdb)'), "Python breakpoint/pdb", "error"),
]

TEMP_MARKERS = [
    (re.compile(r'(?i)\b(TODO|FIXME|HACK|TEMP|DEBUG)\b.*(remove|delete|temp|cleanup|test|mock)'), "Temporary marker left in code", "notice"),
]

SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token)\s*[:=]\s*[\'"][a-zA-Z0-9_\-\.]{16,}[\'"]'), "Potential hardcoded API/Secret key", "critical"),
    (re.compile(r'-----BEGIN\s+(?:RSA\s+|EC\s+)?PRIVATE\s+KEY-----'), "Private encryption key in diff", "critical"),
]

def audit_diff(cwd: str, staged_only: bool = False, file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Audits git diff for lingering debug artifacts, temporary markers, hardcoded secrets, and syntax errors.
    """
    git_cmd = ["git", "diff", "HEAD"]
    if staged_only:
        git_cmd = ["git", "diff", "--staged"]
    if file_path:
        git_cmd.append("--")
        git_cmd.append(file_path)

    try:
        proc = subprocess.run(
            git_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10
        )
        diff_text = proc.stdout
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to execute git diff: {e}",
            "issues": [],
            "card": f"Error: Git diff failed: {e}"
        }

    if not diff_text.strip():
        return {
            "status": "ok",
            "clean": True,
            "issues_count": 0,
            "issues": [],
            "checked_files": [],
            "card": "=== Git Diff Audit: CLEAN ===\nNo changes detected in git diff."
        }

    issues: List[Dict[str, Any]] = []
    checked_files = set()
    current_file = None
    current_line = 0

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" ")
            if len(parts) >= 4:
                b_path = parts[3].lstrip("b/")
                current_file = b_path
                checked_files.add(b_path)
            continue

        if line.startswith("@@ "):
            # Format: @@ -old,len +new,len @@
            m = re.search(r'\+(\d+)(?:,(\d+))?', line)
            if m:
                current_line = int(m.group(1))
            continue

        if line.startswith("+++ ") or line.startswith("--- "):
            continue

        if line.startswith("+"):
            added_content = line[1:].strip()
            line_no = current_line
            current_line += 1

            if not added_content:
                continue

            # Don't check comments or markdown lines for debug calls if they are clearly documentation
            if current_file and (current_file.endswith(".md") or current_file.endswith(".txt")):
                continue

            # Check Debug Patterns
            for pat, desc, severity in DEBUG_PATTERNS:
                if pat.search(added_content):
                    issues.append({
                        "file": current_file,
                        "line": line_no,
                        "type": "debug_artifact",
                        "severity": severity,
                        "description": desc,
                        "snippet": added_content[:100]
                    })
                    break

            # Check Temp Markers
            for pat, desc, severity in TEMP_MARKERS:
                if pat.search(added_content):
                    issues.append({
                        "file": current_file,
                        "line": line_no,
                        "type": "temporary_marker",
                        "severity": severity,
                        "description": desc,
                        "snippet": added_content[:100]
                    })
                    break

            # Check Secret Patterns
            for pat, desc, severity in SECRET_PATTERNS:
                if pat.search(added_content):
                    issues.append({
                        "file": current_file,
                        "line": line_no,
                        "type": "secret_leak",
                        "severity": severity,
                        "description": desc,
                        "snippet": added_content[:100]
                    })
                    break

        elif not line.startswith("-"):
            current_line += 1

    # Optional PHP Syntax check on modified PHP files
    php_errors = []
    for f in checked_files:
        if f.endswith(".php"):
            full_p = os.path.join(cwd, f)
            if os.path.isfile(full_p):
                try:
                    c = subprocess.run(
                        ["php", "-l", full_p],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5
                    )
                    if c.returncode != 0:
                        err_msg = c.stdout.strip() or c.stderr.strip()
                        php_errors.append({"file": f, "error": err_msg})
                        issues.append({
                            "file": f,
                            "line": 1,
                            "type": "syntax_error",
                            "severity": "critical",
                            "description": "PHP syntax check failed",
                            "snippet": err_msg
                        })
                except Exception:
                    pass

    # Build Output Card
    card_lines = [
        f"=== Git Diff Audit: {len(issues)} issue(s) in {len(checked_files)} changed file(s) ==="
    ]
    if not issues:
        card_lines.append("Status: PASS (No debug artifacts, leaked secrets, or syntax errors detected)")
    else:
        card_lines.append("Status: ISSUES DETECTED")
        card_lines.append("-" * 70)
        for issue in issues:
            sev = issue["severity"].upper()
            card_lines.append(f"[{sev}] {issue['file']}:{issue['line']} - {issue['description']}")
            card_lines.append(f"    Line: {issue['snippet']}")
        card_lines.append("-" * 70)
        card_lines.append("Recommendation: Remove debug statements and secrets before committing.")

    return {
        "status": "ok" if not issues else "issues_found",
        "clean": len(issues) == 0,
        "issues_count": len(issues),
        "issues": issues,
        "checked_files": sorted(list(checked_files)),
        "card": "\n".join(card_lines)
    }
