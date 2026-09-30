import os
import re
import difflib
from typing import Dict, Any, List, Optional, Tuple

def verify_patch(file_path: str, target_content: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Pre-validates an edit/patch block before applying via replace_file_content or diff tools.
    Finds exact 1-indexed StartLine and EndLine, detects whitespace mismatches,
    and returns ready-to-use tool arguments.
    """
    if cwd and not os.path.isabs(file_path):
        abs_path = os.path.normpath(os.path.join(cwd, file_path))
    else:
        abs_path = os.path.abspath(file_path)

    rel_path = os.path.relpath(abs_path, cwd) if cwd else file_path

    if not os.path.isfile(abs_path):
        return {
            "status": "error",
            "message": f"File not found: {rel_path}",
            "file": rel_path,
            "found": False,
            "card": f"Error: File not found: {rel_path}"
        }

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            file_text = f.read()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Cannot read file: {e}",
            "file": rel_path,
            "found": False,
            "card": f"Error reading file: {e}"
        }

    # Normalize CRLF to LF for consistent line counting
    norm_file = file_text.replace("\r\n", "\n")
    norm_target = target_content.replace("\r\n", "\n")

    # If target has trailing newline but file target doesn't, strip if needed or keep
    lines = norm_file.split("\n")

    # 1. Exact Substring Search
    occurrences: List[Tuple[int, int]] = [] # list of (start_line, end_line)
    start_pos = 0
    while True:
        idx = norm_file.find(norm_target, start_pos)
        if idx == -1:
            break
        # Calculate line numbers
        start_line = norm_file[:idx].count("\n") + 1
        end_idx = idx + len(norm_target)
        end_line = norm_file[:end_idx].count("\n") + 1
        occurrences.append((start_line, end_line))
        start_pos = idx + max(1, len(norm_target))

    if len(occurrences) == 1:
        start_line, end_line = occurrences[0]
        # Build tool args
        tool_args = {
            "TargetFile": abs_path,
            "StartLine": start_line,
            "EndLine": end_line,
            "TargetContent": norm_target,
            "AllowMultiple": False
        }
        card = (
            f"=== Patch Verified: {rel_path} ===\n"
            f"Status: EXACT MATCH (Unique, lines {start_line}-{end_line})\n"
            f"Tool Arguments for replace_file_content:\n"
            f"  StartLine: {start_line}\n"
            f"  EndLine:   {end_line}\n"
            f"  TargetContent matches exactly ({len(norm_target.splitlines())} lines)"
        )
        return {
            "status": "ok",
            "match_type": "exact",
            "file": rel_path,
            "absolute_path": abs_path,
            "found": True,
            "matches_count": 1,
            "start_line": start_line,
            "end_line": end_line,
            "target_content": norm_target,
            "tool_args": tool_args,
            "card": card
        }

    if len(occurrences) > 1:
        match_str = ", ".join([f"lines {s}-{e}" for s, e in occurrences])
        card = (
            f"=== Patch Ambiguous: {rel_path} ===\n"
            f"Status: AMBIGUOUS ({len(occurrences)} matches found: {match_str})\n"
            f"Recommendation: Include 1-2 more surrounding lines in TargetContent to ensure uniqueness."
        )
        return {
            "status": "ambiguous",
            "match_type": "multiple_exact",
            "file": rel_path,
            "absolute_path": abs_path,
            "found": True,
            "matches_count": len(occurrences),
            "matches": [{"start_line": s, "end_line": e} for s, e in occurrences],
            "card": card
        }

    # 2. Whitespace-Tolerant Search
    # Compare line by line with stripped whitespace
    target_lines = [l.strip() for l in norm_target.split("\n") if l.strip()]
    if target_lines:
        file_stripped_lines = [l.strip() for l in lines]
        num_target = len(target_lines)

        fuzzy_matches = []
        for i in range(len(file_stripped_lines) - num_target + 1):
            window = [file_stripped_lines[i + k] for k in range(num_target)]
            if window == target_lines:
                # Find the actual exact slice from file
                s_line = i + 1
                e_line = i + num_target
                # Extract actual lines from original file
                actual_content = "\n".join(lines[i : i + num_target])
                fuzzy_matches.append((s_line, e_line, actual_content))

        if len(fuzzy_matches) == 1:
            s_line, e_line, actual_content = fuzzy_matches[0]
            tool_args = {
                "TargetFile": abs_path,
                "StartLine": s_line,
                "EndLine": e_line,
                "TargetContent": actual_content,
                "AllowMultiple": False
            }
            card = (
                f"=== Patch Verified (Whitespace Corrected): {rel_path} ===\n"
                f"Status: WHITESPACE MISMATCH DETECTED & RESOLVED\n"
                f"Lines:  {s_line}-{e_line}\n"
                f"Correct TargetContent with file's exact indentation:\n"
                f"----------------------------------------\n"
                f"{actual_content}\n"
                f"----------------------------------------\n"
                f"Tool Arguments for replace_file_content:\n"
                f"  StartLine: {s_line}\n"
                f"  EndLine:   {e_line}"
            )
            return {
                "status": "ok",
                "match_type": "whitespace_corrected",
                "file": rel_path,
                "absolute_path": abs_path,
                "found": True,
                "matches_count": 1,
                "start_line": s_line,
                "end_line": e_line,
                "target_content": actual_content,
                "tool_args": tool_args,
                "card": card
            }

    # 3. Not Found - Locate Closest Match using difflib
    first_target_line = target_lines[0] if target_lines else ""
    best_ratio = 0.0
    best_line = 1
    for idx, line in enumerate(lines):
        r = difflib.SequenceMatcher(None, first_target_line, line.strip()).ratio()
        if r > best_ratio:
            best_ratio = r
            best_line = idx + 1

    card = (
        f"=== Patch Verification Failed: {rel_path} ===\n"
        f"Status: TARGET NOT FOUND\n"
        f"Target content ({len(norm_target.splitlines())} lines) does not exist in {rel_path}.\n"
    )
    if best_ratio > 0.6:
        card += f"Closest matching line located around line {best_line} (similarity: {int(best_ratio * 100)}%):\n"
        card += f"  Line {best_line}: {lines[best_line - 1].strip()[:80]}"

    return {
        "status": "not_found",
        "match_type": "none",
        "file": rel_path,
        "absolute_path": abs_path,
        "found": False,
        "matches_count": 0,
        "closest_line": best_line if best_ratio > 0.6 else None,
        "similarity": best_ratio,
        "card": card
    }
