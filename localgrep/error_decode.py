import os
import re
import json
from typing import Dict, Any, List, Optional, Tuple

FRAMEWORK_VENDOR_PATTERNS = [
    r"vendor/laravel/",
    r"vendor/symfony/",
    r"vendor/livewire/",
    r"vendor/fakerphp/",
    r"vendor/composer/",
    r"vendor/monolog/",
    r"vendor/league/",
    r"vendor/doctrine/",
    r"vendor/phpunit/",
    r"vendor/pestphp/",
    r"vendor/nesbot/",
    r"vendor/carbon/",
    r"vendor/guzzlehttp/",
    r"vendor/ramsey/",
    r"vendor/filp/",
    r"vendor/psr/",
    r"vendor/vlucas/",
    r"vendor/nikic/",
    r"vendor/tightenco/"
]

def is_application_frame(path: str) -> bool:
    """Determine if a file path belongs to application/module code rather than framework vendor plumbing."""
    norm = path.replace("\\", "/")
    # Bina platform modules are application domain code
    if "vendor/bina/" in norm:
        return True

    # Check if inside framework vendor
    for pat in FRAMEWORK_VENDOR_PATTERNS:
        if re.search(pat, norm):
            return False

    # Root app code or modules
    if "Modules/" in norm or "/app/" in norm or norm.startswith("app/"):
        return True
    if "/routes/" in norm or norm.startswith("routes/"):
        return True
    if "/resources/" in norm or norm.startswith("resources/"):
        return True

    return True

def extract_code_snippet(filepath: str, target_line: int, radius: int = 2) -> List[str]:
    """Read around target line in local file and format with a cursor indicator."""
    if not os.path.isfile(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total = len(lines)
        start = max(1, target_line - radius)
        end = min(total, target_line + radius)

        snippet = []
        for i in range(start, end + 1):
            line_str = lines[i - 1].rstrip("\r\n")
            prefix = " >> " if i == target_line else "    "
            snippet.append(f"{prefix}{i:4d}: {line_str}")
        return snippet
    except Exception:
        return []

def bind_sql_parameters(sql: str, bindings_str: str) -> str:
    """Inline bindings into SQL '?' placeholders."""
    try:
        bindings = json.loads(bindings_str)
    except Exception:
        try:
            # Try parsing Python-style or PHP-style array representation
            clean = bindings_str.strip()
            if clean.startswith("[") and clean.endswith("]"):
                items = [x.strip().strip("'\"") for x in clean[1:-1].split(",") if x.strip()]
                bindings = items
            else:
                bindings = []
        except Exception:
            bindings = []

    if not isinstance(bindings, list) or not bindings:
        return sql.strip()

    bound_sql = sql
    for b in bindings:
        if b is None or str(b).lower() == "null":
            rep = "NULL"
        elif isinstance(b, (int, float)):
            rep = str(b)
        else:
            b_escaped = str(b).replace("'", "''")
            rep = f"'{b_escaped}'"

        # Replace first occurrence of ?
        bound_sql = bound_sql.replace("?", rep, 1)

    return bound_sql.strip()

def extract_last_error_block(text: str) -> str:
    """Find the most recent error/exception entry from log text."""
    lines = text.strip().split("\n")
    start_indices = []
    for idx, l in enumerate(lines):
        if re.search(r"\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\].*?\.(ERROR|EMERGENCY|CRITICAL|ALERT):", l):
            start_indices.append(idx)
        elif "Stack trace:" in l or "[stacktrace]" in l or "Fatal error:" in l or "Uncaught exception" in l:
            start_indices.append(max(0, idx - 1))

    if start_indices:
        last_start = start_indices[-1]
        return "\n".join(lines[last_start:])

    # Fallback to last 150 lines
    return "\n".join(lines[-150:])

def decode_error(raw_input: str, cwd: str = ".") -> Dict[str, Any]:
    """Parse log text or exception trace into structured, high-density summary."""
    clean_input = raw_input.strip()

    # Check if input is a file path
    target_file = os.path.join(cwd, clean_input) if not os.path.isabs(clean_input) else clean_input
    if os.path.isfile(target_file):
        try:
            # Read last 32KB
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 32768))
                content = f.read()
            text_to_parse = extract_last_error_block(content)
        except Exception as e:
            return {"status": "error", "message": f"Could not read log file: {str(e)}"}
    else:
        text_to_parse = clean_input

    # 1. Extract Exception Type & Message
    error_type = "Exception"
    error_message = ""

    # Match: {"exception":"[object] (ClassName(code: 0): Message at /path:line)
    m_json = re.search(r'\[object\]\s*\(([a-zA-Z0-9_\\]+)\(code:\s*\d+\):\s*(.*?)\s+at\s+([^\)]+):(\d+)\)', text_to_parse)
    if m_json:
        error_type = m_json.group(1)
        error_message = m_json.group(2)
    else:
        # Match standard: ClassName: Message
        m_std = re.search(r'([A-Za-z0-9_\\]+(?:Exception|Error)):\s*(.*)', text_to_parse)
        if m_std:
            error_type = m_std.group(1)
            error_message = m_std.group(2)
        else:
            # Match: local.ERROR: Message
            m_log = re.search(r'\.(?:ERROR|EMERGENCY|CRITICAL):\s*([^{]+)', text_to_parse)
            if m_log:
                error_message = m_log.group(1).strip()
            else:
                first_line = text_to_parse.split("\n")[0]
                error_message = first_line[:120]

    # 2. Extract SQL & Bindings
    sql_query = None
    m_sql = re.search(r'SQL:\s*(select|insert|update|delete|create|alter|drop)\s+(.*?)(?=\)\s*(?:\[bindings|\{|$)|\n|$)', text_to_parse, re.IGNORECASE)
    if not m_sql:
        m_sql = re.search(r'(select|insert|update|delete|create|alter|drop)\s+([^\n;]+)', text_to_parse, re.IGNORECASE)

    if m_sql:
        raw_sql = f"{m_sql.group(1)} {m_sql.group(2)}".strip()
        m_bind = re.search(r'\[bindings:\s*(\[[^\]]*\])\]', text_to_parse)
        if m_bind:
            sql_query = bind_sql_parameters(raw_sql, m_bind.group(1))
        else:
            sql_query = raw_sql

    # 3. Parse Stack Frames
    frames = []
    # Match: #0 /path/to/file.php(123): Class->method()
    frame_matches = re.finditer(r'#(\d+)\s+([^\(\n]+)\((\d+)\):?\s*(.*)', text_to_parse)
    for fm in frame_matches:
        f_idx = int(fm.group(1))
        f_path = fm.group(2).strip()
        f_line = int(fm.group(3))
        f_call = fm.group(4).strip()
        frames.append({
            "index": f_idx,
            "path": f_path,
            "line": f_line,
            "call": f_call,
            "is_app": is_application_frame(f_path)
        })

    # Find innermost application frame
    app_frames = [f for f in frames if f["is_app"]]
    innermost_app_frame = None

    if app_frames:
        innermost_app_frame = app_frames[0]
    elif m_json and is_application_frame(m_json.group(3)):
        innermost_app_frame = {
            "index": 0,
            "path": m_json.group(3),
            "line": int(m_json.group(4)),
            "call": "",
            "is_app": True
        }
    elif frames:
        # Fallback to frame 0 if no app frame
        innermost_app_frame = frames[0]

    if not innermost_app_frame:
        m_inline = re.search(r'(?:in|at)\s+([^\s:]+\.(?:php|vue|ts|js|py)):?(\d+)?(?:\s+on\s+line\s+(\d+))?', text_to_parse)
        if m_inline:
            f_path = m_inline.group(1).strip()
            f_line = int(m_inline.group(2) or m_inline.group(3) or 1)
            innermost_app_frame = {
                "index": 0,
                "path": f_path,
                "line": f_line,
                "call": "",
                "is_app": is_application_frame(f_path)
            }

    # Format paths relative to cwd
    if innermost_app_frame:
        full_f_path = innermost_app_frame["path"]
        if os.path.isabs(full_f_path):
            innermost_app_frame["rel_path"] = os.path.relpath(full_f_path, cwd)
        else:
            innermost_app_frame["rel_path"] = full_f_path

        # Extract code snippet
        snippet_path = os.path.join(cwd, innermost_app_frame["rel_path"])
        innermost_app_frame["snippet"] = extract_code_snippet(snippet_path, innermost_app_frame["line"])

    return {
        "status": "ok",
        "error_type": error_type,
        "message": error_message,
        "innermost_frame": innermost_app_frame,
        "app_frames_count": len(app_frames),
        "total_frames_count": len(frames),
        "sql_query": sql_query
    }

def format_error_decode_text(res: Dict[str, Any]) -> str:
    """Format decoded error into compact, high-density terminal card."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to decode error.')}"

    err_type = res.get("error_type", "Exception")
    msg = res.get("message", "Unknown error")
    lines = [
        "=== Decoded Application Error ===",
        f"Type: {err_type}",
        f"Message: {msg}"
    ]

    sql = res.get("sql_query")
    if sql:
        lines.append("")
        lines.append("Decoded SQL Query:")
        lines.append(f"  {sql};")

    frame = res.get("innermost_frame")
    lines.append("")
    if frame:
        rel = frame.get("rel_path", frame.get("path"))
        call_str = f" (in {frame['call']})" if frame.get("call") else ""
        lines.append(f"Innermost App Frame:")
        lines.append(f"  -> {rel}:{frame['line']}{call_str}")

        snippet = frame.get("snippet", [])
        if snippet:
            lines.append("")
            lines.append("Code Context:")
            for s in snippet:
                lines.append(f"  {s}")
    else:
        lines.append("Innermost App Frame: None (All frames vendor / framework)")

    tot = res.get("total_frames_count", 0)
    app_cnt = res.get("app_frames_count", 0)
    lines.append("")
    lines.append(f"Stack Trace Distillation: Pruned {tot - app_cnt} framework vendor frames ({app_cnt} app frames preserved).")

    return "\n".join(lines)
