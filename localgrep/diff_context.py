import os
import re
import subprocess
from typing import Dict, Any, List, Optional

def get_enclosing_symbol(filepath: str, target_line: int, cwd: str) -> Optional[str]:
    """Scan upwards from target line to find enclosing function, method, or class."""
    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.isfile(full_path):
        return None

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # Scan backwards up to 50 lines
        start_idx = min(len(lines) - 1, target_line - 1)
        for i in range(start_idx, max(-1, start_idx - 60), -1):
            line = lines[i].strip()
            # PHP / JS / TS method or function
            m_fn = re.search(r'(?:public|protected|private|static|async|function|\bconst|\blet|\bvar)?\s*(?:function\s+)?([a-zA-Z0-9_\-]+)\s*\([^)]*\)', line)
            if m_fn and not line.startswith("//") and not line.startswith("*"):
                fn_name = m_fn.group(1)
                if fn_name not in ("if", "for", "foreach", "while", "switch", "catch"):
                    return f"{fn_name}()"

            # Class definition
            m_cls = re.search(r'(?:class|interface|trait|enum)\s+([a-zA-Z0-9_]+)', line)
            if m_cls:
                return f"class {m_cls.group(1)}"
    except Exception:
        pass

    return None

def extract_diff_context(cwd: str, staged: bool = False, target_file: Optional[str] = None) -> Dict[str, Any]:
    """Convert raw git diff into structured context hunks with enclosing function signatures."""
    cmd = ["git", "diff", "--unified=3"]
    if staged:
        cmd.append("--staged")
    if target_file:
        cmd.extend(["--", target_file])

    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=5)
        raw_diff = proc.stdout
    except Exception as e:
        return {"status": "error", "message": f"Failed to run git diff: {str(e)}"}

    if not raw_diff.strip():
        return {
            "status": "ok",
            "message": "No changes detected in git diff.",
            "files": []
        }

    files = []
    current_file = None
    current_hunks = []

    diff_lines = raw_diff.splitlines()
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith("diff --git "):
            if current_file and current_hunks:
                files.append({
                    "file": current_file,
                    "hunks": current_hunks
                })
            # Extract new file path
            m_f = re.search(r'b/(.*)$', line)
            current_file = m_f.group(1) if m_f else "unknown"
            current_hunks = []
            i += 1
            continue

        if line.startswith("@@ "):
            m_hunk = re.search(r'@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@\s*(.*)', line)
            if m_hunk:
                new_start = int(m_hunk.group(2))
                raw_func_header = m_hunk.group(4).strip()

                # Collect hunk lines
                hunk_lines = []
                i += 1
                while i < len(diff_lines) and not diff_lines[i].startswith("diff --git ") and not diff_lines[i].startswith("@@ "):
                    hunk_lines.append(diff_lines[i])
                    i += 1

                # Resolve enclosing symbol
                enclosing = raw_func_header if raw_func_header else get_enclosing_symbol(current_file, new_start, cwd)

                current_hunks.append({
                    "line": new_start,
                    "enclosing": enclosing or "file scope",
                    "diff_lines": hunk_lines
                })
                continue
        i += 1

    if current_file and current_hunks:
        files.append({
            "file": current_file,
            "hunks": current_hunks
        })

    return {
        "status": "ok",
        "staged": staged,
        "files_count": len(files),
        "files": files
    }

def format_diff_context_text(res: Dict[str, Any]) -> str:
    """Format structured contextual diff for terminal review."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to generate diff context.')}"

    files = res.get("files", [])
    if not files:
        return res.get("message", "No changes detected in git diff.")

    staged_str = " (Staged)" if res.get("staged") else ""
    lines = [
        f"=== Contextual Git Diff{staged_str} ({len(files)} files) ===",
        ""
    ]

    for f in files:
        lines.append(f"File: {f['file']}")
        for h in f.get("hunks", []):
            enc = h.get("enclosing", "file scope")
            lines.append(f"  @@ Line {h['line']} in {enc} @@")
            for dl in h.get("diff_lines", []):
                lines.append(f"    {dl}")
            lines.append("")

    return "\n".join(lines)
