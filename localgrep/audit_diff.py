import os
import re
import subprocess
from typing import Dict, Any, List, Optional, Set, Tuple

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
    (re.compile(r'\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b'), "AWS Access Key ID", "critical"),
    (re.compile(r'(?i)(aws_secret_access_key|aws_access_key_id|aws_session_token)\s*[:=]\s*[\'"][a-zA-Z0-9/+=]{16,}[\'"]'), "AWS Secret/Session credential", "critical"),
    (re.compile(r'(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|private[_-]?key)\s*[:=]\s*[\'"][a-zA-Z0-9_\-\.]{16,}[\'"]'), "Potential hardcoded API/Secret key", "critical"),
    (re.compile(r'-----BEGIN\s+(?:RSA\s+|EC\s+)?PRIVATE\s+KEY-----'), "Private encryption key in diff", "critical"),
    (re.compile(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{24,}'), "Bearer authorization token", "critical"),
]

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".avif",
    ".mp4", ".webm", ".mp3", ".wav", ".ogg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".lock"
}

def scan_lines_for_issues(lines: List[Tuple[int, str]], file_path: str) -> List[Dict[str, Any]]:
    """Scan a list of (line_no, line_content) for issues."""
    issues = []
    is_doc = file_path.endswith(".md") or file_path.endswith(".txt")

    for line_no, content in lines:
        stripped = content.strip()
        if not stripped:
            continue

        if not is_doc:
            # Check Debug Patterns
            for pat, desc, severity in DEBUG_PATTERNS:
                if pat.search(stripped):
                    issues.append({
                        "file": file_path,
                        "line": line_no,
                        "type": "debug_artifact",
                        "severity": severity,
                        "description": desc,
                        "snippet": stripped[:120]
                    })
                    break

            # Check Temp Markers
            for pat, desc, severity in TEMP_MARKERS:
                if pat.search(stripped):
                    issues.append({
                        "file": file_path,
                        "line": line_no,
                        "type": "temporary_marker",
                        "severity": severity,
                        "description": desc,
                        "snippet": stripped[:120]
                    })
                    break

        # Check Secret Patterns (even in docs)
        for pat, desc, severity in SECRET_PATTERNS:
            if pat.search(stripped):
                issues.append({
                    "file": file_path,
                    "line": line_no,
                    "type": "secret_leak",
                    "severity": severity,
                    "description": desc,
                    "snippet": stripped[:120]
                })
                break

    return issues

def get_untracked_files(cwd: str) -> List[str]:
    """Retrieve list of untracked files excluding standard gitignore."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5
        )
        if proc.returncode == 0 and proc.stdout:
            files = []
            for f in proc.stdout.strip().split("\n"):
                f = f.strip()
                if f and not any(f.endswith(ext) for ext in IGNORED_EXTENSIONS):
                    files.append(f)
            return files
    except Exception:
        pass
    return []

def audit_file_direct(full_path: str, rel_path: str) -> List[Dict[str, Any]]:
    """Audit an entire file directly (used for untracked files or direct --file targets)."""
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [(i + 1, line) for i, line in enumerate(f.readlines())]
        return scan_lines_for_issues(lines, rel_path)
    except Exception:
        return []

def audit_diff(cwd: str, staged_only: bool = False, file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Audits git diff and untracked files for lingering debug artifacts, temporary markers,
    hardcoded secrets, and syntax errors.
    """
    issues: List[Dict[str, Any]] = []
    checked_files: Set[str] = set()
    untracked_checked: Set[str] = set()

    # If a specific file is requested
    if file_path:
        full_path = os.path.join(cwd, file_path) if not os.path.isabs(file_path) else file_path
        rel_path = os.path.relpath(full_path, cwd)
        if not os.path.isfile(full_path):
            return {
                "status": "error",
                "message": f"Target file not found: {file_path}",
                "issues": [],
                "card": f"Error: Target file not found: {file_path}"
            }

        checked_files.add(rel_path)
        # Check git diff for this file
        git_cmd = ["git", "diff", "--staged" if staged_only else "HEAD", "--", rel_path]
        diff_text = ""
        try:
            p = subprocess.run(git_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
            diff_text = p.stdout
        except Exception:
            pass

        if diff_text.strip():
            # Parse diff
            current_line = 0
            for line in diff_text.splitlines():
                if line.startswith("@@ "):
                    m = re.search(r'\+(\d+)(?:,(\d+))?', line)
                    if m:
                        current_line = int(m.group(1))
                    continue
                if line.startswith("+++ ") or line.startswith("--- "):
                    continue
                if line.startswith("+"):
                    added_content = line[1:]
                    line_no = current_line
                    current_line += 1
                    issues.extend(scan_lines_for_issues([(line_no, added_content)], rel_path))
                elif not line.startswith("-"):
                    current_line += 1
        else:
            # File has no tracked diff (e.g. untracked or completely new file) -> audit entire content
            untracked_checked.add(rel_path)
            issues.extend(audit_file_direct(full_path, rel_path))

        # Check PHP syntax if PHP
        if rel_path.endswith(".php"):
            try:
                c = subprocess.run(["php", "-l", full_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                if c.returncode != 0:
                    err_msg = c.stdout.strip() or c.stderr.strip()
                    issues.append({
                        "file": rel_path,
                        "line": 1,
                        "type": "syntax_error",
                        "severity": "critical",
                        "description": "PHP syntax check failed",
                        "snippet": err_msg
                    })
            except Exception:
                pass

    else:
        # 1. Audit tracked git diff
        git_cmd = ["git", "diff", "--staged"] if staged_only else ["git", "diff", "HEAD"]
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
                m = re.search(r'\+(\d+)(?:,(\d+))?', line)
                if m:
                    current_line = int(m.group(1))
                continue

            if line.startswith("+++ ") or line.startswith("--- "):
                continue

            if line.startswith("+"):
                added_content = line[1:]
                line_no = current_line
                current_line += 1
                if current_file:
                    issues.extend(scan_lines_for_issues([(line_no, added_content)], current_file))
            elif not line.startswith("-"):
                current_line += 1

        # 2. Audit untracked files if not staged_only
        if not staged_only:
            untracked_files = get_untracked_files(cwd)
            for uf in untracked_files:
                full_uf = os.path.join(cwd, uf)
                if os.path.isfile(full_uf):
                    checked_files.add(uf)
                    untracked_checked.add(uf)
                    issues.extend(audit_file_direct(full_uf, uf))

        # 3. Check PHP syntax on all checked PHP files
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
    tracked_count = len(checked_files) - len(untracked_checked)
    card_lines = [
        f"=== Git Diff & Pre-Commit Audit: {len(issues)} issue(s) across {len(checked_files)} file(s) ==="
    ]
    scope_desc = f"{tracked_count} diffed file(s)"
    if untracked_checked:
        scope_desc += f", {len(untracked_checked)} untracked file(s)"
    card_lines.append(f"Scope: {scope_desc}")
    card_lines.append("Checks: Debug statements (dd/dump/console.log), Leaked secrets (AWS/API/tokens), Temp markers, PHP syntax.")

    if not issues:
        card_lines.append("")
        card_lines.append("Status: PASS (No debug artifacts, leaked secrets, or syntax errors detected)")
    else:
        card_lines.append("")
        card_lines.append("Status: ISSUES DETECTED")
        card_lines.append("-" * 75)
        for issue in issues:
            sev = issue["severity"].upper()
            card_lines.append(f"[{sev}] {issue['file']}:{issue['line']} - {issue['description']}")
            card_lines.append(f"    Line: {issue['snippet']}")
        card_lines.append("-" * 75)
        card_lines.append("Recommendation: Remove debug statements and secrets before committing.")

    return {
        "status": "ok" if not issues else "issues_found",
        "clean": len(issues) == 0,
        "issues_count": len(issues),
        "issues": issues,
        "checked_files": sorted(list(checked_files)),
        "untracked_files": sorted(list(untracked_checked)),
        "card": "\n".join(card_lines)
    }
