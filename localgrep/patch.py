import os
import re
import sys
import tempfile
import difflib
import subprocess
from typing import Dict, Any, List, Optional, Tuple

def detect_indentation(lines: List[str]) -> Tuple[str, int]:
    """
    Detects indentation style (tabs vs spaces) and common width.
    Returns (indent_char, indent_size).
    """
    tab_count = 0
    space_counts = {}

    for line in lines:
        if not line.strip():
            continue
        leading = line[:len(line) - len(line.lstrip())]
        if '\t' in leading:
            tab_count += 1
        elif len(leading) > 0 and len(leading) % 2 == 0:
            space_counts[len(leading)] = space_counts.get(len(leading), 0) + 1

    if tab_count > sum(space_counts.values()):
        return ("\t", 1)

    if space_counts:
        # Common space indentation (usually 2 or 4)
        for cand in (4, 2):
            if any(cnt for size, cnt in space_counts.items() if size % cand == 0):
                return (" ", cand)

    return (" ", 4)

def align_indentation(
    replace_block: str,
    original_matched_lines: List[str],
    search_block: str
) -> str:
    """
    Aligns the indentation of replace_block to match the context of original_matched_lines.
    """
    if not original_matched_lines or not replace_block.strip():
        return replace_block

    first_orig_line = original_matched_lines[0]
    orig_leading = first_orig_line[:len(first_orig_line) - len(first_orig_line.lstrip())]

    search_lines = [l for l in search_block.splitlines() if l.strip()]
    first_search_leading = ""
    if search_lines:
        first_s = search_lines[0]
        first_search_leading = first_s[:len(first_s) - len(first_s.lstrip())]

    replace_lines = replace_block.splitlines()
    if not replace_lines:
        return replace_block

    # If replacement already has the exact same leading indent on line 0, keep it
    if replace_lines[0].startswith(orig_leading) and orig_leading != "":
        return replace_block

    # Determine base indent delta
    first_r = next((l for l in replace_lines if l.strip()), "")
    first_r_leading = first_r[:len(first_r) - len(first_r.lstrip())] if first_r else ""

    # Re-indent relative to first line
    aligned = []
    for line in replace_lines:
        if not line.strip():
            aligned.append("")
            continue

        line_leading = line[:len(line) - len(line.lstrip())]
        content = line.lstrip()

        # Relative indent to replacement base
        if line_leading.startswith(first_r_leading):
            rel_indent = line_leading[len(first_r_leading):]
        else:
            rel_indent = ""

        aligned.append(orig_leading + rel_indent + content)

    return "\n".join(aligned)

def validate_content_syntax(filepath: str, content: str) -> Tuple[bool, Optional[str]]:
    """
    Performs fast in-memory / temporary syntax check.
    Returns (is_valid, error_message).
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".php":
        with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False, encoding="utf-8") as tf:
            tf.write(content)
            temp_path = tf.name
        try:
            res = subprocess.run(
                ["php", "-l", temp_path],
                capture_output=True,
                text=True,
                timeout=3
            )
            if res.returncode != 0:
                err = res.stderr.strip() or res.stdout.strip()
                clean_err = err.replace(temp_path, os.path.basename(filepath)).split("Errors parsing")[0].strip()
                return (False, clean_err)
        except Exception as e:
            pass
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    elif ext == ".py":
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
            tf.write(content)
            temp_path = tf.name
        try:
            import py_compile
            py_compile.compile(temp_path, doraise=True)
        except py_compile.PyCompileError as e:
            return (False, f"Python SyntaxError: {str(e).splitlines()[-1]}")
        except Exception as e:
            return (False, f"Syntax error: {str(e)}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    elif ext == ".vue":
        try:
            try:
                from localgrep.lint_fast import lint_vue
            except ImportError:
                try:
                    from .lint_fast import lint_vue
                except ImportError:
                    from lint_fast import lint_vue

            issues = lint_vue(filepath, content.splitlines(keepends=True))
            errors = [i for i in issues if i.get("severity") == "error"]
            if errors:
                return (False, f"Vue Syntax Issue at line {errors[0]['line']}: {errors[0]['message']}")
        except Exception:
            pass

    return (True, None)

def apply_patch(
    file_path: str,
    search_block: str,
    replace_block: str,
    cwd: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False
) -> Dict[str, Any]:
    """
    Applies search-and-replace block to file_path with:
    - Exact and whitespace-tolerant matching
    - Automatic indentation alignment
    - Pre-flight syntax validation with rollback
    - Atomic file write
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
            "file": rel_path
        }

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            file_text = f.read()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Cannot read file: {e}",
            "file": rel_path
        }

    # Normalize line endings
    norm_file = file_text.replace("\r\n", "\n")
    norm_search = search_block.replace("\r\n", "\n")
    norm_replace = replace_block.replace("\r\n", "\n")

    lines = norm_file.split("\n")

    start_line = None
    end_line = None
    match_type = None
    matched_file_lines = []

    # 1. Exact Substring Search
    start_pos = 0
    exact_matches = []
    while True:
        idx = norm_file.find(norm_search, start_pos)
        if idx == -1:
            break
        s_line = norm_file[:idx].count("\n") + 1
        e_idx = idx + len(norm_search)
        e_line = norm_file[:e_idx].count("\n") + 1
        exact_matches.append((s_line, e_line, idx, e_idx))
        start_pos = idx + max(1, len(norm_search))

    if len(exact_matches) == 1:
        start_line, end_line, char_start, char_end = exact_matches[0]
        match_type = "exact"
        matched_file_lines = lines[start_line - 1 : end_line]
    elif len(exact_matches) > 1:
        match_str = ", ".join([f"lines {s}-{e}" for s, e, _, _ in exact_matches])
        return {
            "status": "ambiguous",
            "message": f"Ambiguous match: search block matched {len(exact_matches)} locations ({match_str}). Provide more context lines.",
            "file": rel_path,
            "matches_count": len(exact_matches),
            "matches": [{"start_line": s, "end_line": e} for s, e, _, _ in exact_matches]
        }

    # 2. Whitespace-Tolerant Search Fallback
    if match_type is None:
        target_lines = [l.strip() for l in norm_search.split("\n") if l.strip()]
        if not target_lines:
            return {
                "status": "error",
                "message": "Search block is empty or contains only whitespace.",
                "file": rel_path
            }

        file_stripped = [l.strip() for l in lines]
        num_target = len(target_lines)

        fuzzy_matches = []
        for i in range(len(file_stripped) - num_target + 1):
            window = [file_stripped[i + k] for k in range(num_target)]
            if window == target_lines:
                s_line = i + 1
                e_line = i + num_target
                actual_slice = lines[i : i + num_target]
                fuzzy_matches.append((s_line, e_line, actual_slice))

        if len(fuzzy_matches) == 1:
            start_line, end_line, matched_file_lines = fuzzy_matches[0]
            match_type = "fuzzy_whitespace"
        elif len(fuzzy_matches) > 1:
            match_str = ", ".join([f"lines {s}-{e}" for s, e, _ in fuzzy_matches])
            return {
                "status": "ambiguous",
                "message": f"Ambiguous match: whitespace-tolerant search matched {len(fuzzy_matches)} locations ({match_str}). Provide more context lines.",
                "file": rel_path,
                "matches_count": len(fuzzy_matches),
                "matches": [{"start_line": s, "end_line": e} for s, e, _ in fuzzy_matches]
            }

    if match_type is None:
        return {
            "status": "not_found",
            "message": f"Search block not found in {rel_path}.",
            "file": rel_path
        }

    # Align indentation of replacement
    aligned_replacement = align_indentation(norm_replace, matched_file_lines, norm_search)

    # Perform replacement in memory
    prefix_lines = lines[:start_line - 1]
    suffix_lines = lines[end_line:]
    replacement_lines = aligned_replacement.split("\n")

    new_file_lines = prefix_lines + replacement_lines + suffix_lines
    new_content = "\n".join(new_file_lines)

    # Pre-Flight Syntax Validation
    syntax_valid, syntax_err = validate_content_syntax(abs_path, new_content)
    if not syntax_valid and not force:
        return {
            "status": "syntax_error",
            "message": f"Patch aborted: syntax validation failed. Error: {syntax_err}",
            "file": rel_path,
            "error_detail": syntax_err,
            "start_line": start_line,
            "end_line": end_line,
            "rolled_back": True
        }

    # Generate Unified Diff for verification
    orig_slice = lines[max(0, start_line - 3) : min(len(lines), end_line + 2)]
    diff_gen = list(difflib.unified_diff(
        matched_file_lines,
        replacement_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm=""
    ))
    diff_text = "\n".join(diff_gen)

    # Apply to disk atomically if not dry_run
    if not dry_run:
        tmp_path = abs_path + ".lg_tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, abs_path)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return {
                "status": "error",
                "message": f"Failed to write file atomically: {e}",
                "file": rel_path
            }

    card = (
        f"=== Patch Applied: {rel_path} ===\n"
        f"Status: SUCCESS ({match_type.upper()})\n"
        f"Lines:  {start_line}-{end_line} ({len(matched_file_lines)} lines replaced with {len(replacement_lines)} lines)\n"
        f"Syntax: {'CLEAN' if syntax_valid else 'IGNORED (FORCE)'}\n"
        f"Mode:   {'DRY RUN (No changes saved)' if dry_run else 'APPLIED'}\n"
        f"----------------------------------------\n"
        f"{diff_text if diff_text else '[No line differences]'}\n"
        f"----------------------------------------"
    )

    return {
        "status": "ok",
        "file": rel_path,
        "match_type": match_type,
        "start_line": start_line,
        "end_line": end_line,
        "lines_replaced": len(matched_file_lines),
        "lines_added": len(replacement_lines),
        "dry_run": dry_run,
        "syntax_clean": syntax_valid,
        "diff": diff_text,
        "card": card
    }
