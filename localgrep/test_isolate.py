import os
import re
import subprocess
from typing import Dict, Any, List, Optional

ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

VENDOR_IGNORE = (
    "/vendor/laravel/framework/",
    "/vendor/phpunit/",
    "/vendor/pestphp/",
    "/vendor/mockery/",
    "/vendor/symfony/",
    "/vendor/orchestra/",
    "/vendor/composer/",
    "bin/pest",
    "artisan"
)

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)

def parse_test_output(raw_output: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    clean_text = strip_ansi(raw_output)
    lines = clean_text.splitlines()

    total_tests = 0
    passed_count = 0
    failed_count = 0
    time_str = ""

    # Check overall summary lines
    for line in lines:
        # Pest format: Tests:  1 failed, 14 passed (15 assertions)
        # PHPUnit format: Tests: 15, Assertions: 15, Failures: 1.
        m_pest = re.search(r'Tests:\s+(?:(\d+)\s+failed,?\s*)?(?:(\d+)\s+passed)?.*?(?:\((\d+[\.\d]*\s*s)\))?', line)
        if m_pest and ("passed" in line or "failed" in line):
            failed_count = int(m_pest.group(1)) if m_pest.group(1) else 0
            passed_count = int(m_pest.group(2)) if m_pest.group(2) else 0
            if m_pest.group(3):
                time_str = m_pest.group(3)

        m_phpunit = re.search(r'FAILURES!\s*Tests:\s*(\d+),\s*Assertions:\s*\d+,\s*Failures:\s*(\d+)', line)
        if m_phpunit:
            total_tests = int(m_phpunit.group(1))
            failed_count = int(m_phpunit.group(2))

        m_ok = re.search(r'OK\s*\((\d+)\s+tests?.*?\)', line)
        if m_ok:
            passed_count = int(m_ok.group(1))
            failed_count = 0

        # Python unittest format: Ran 9 tests in 0.002s
        m_py = re.search(r'Ran\s+(\d+)\s+tests?\s+in\s+([\d\.]+s)', line)
        if m_py:
            total_tests = int(m_py.group(1))
            time_str = m_py.group(2)

        if line.strip() == "OK" and total_tests > 0 and failed_count == 0:
            passed_count = total_tests

        m_py_fail = re.search(r'FAILED\s*\((?:failures=(\d+))?(?:,?\s*errors=(\d+))?\)', line)
        if m_py_fail:
            f_num = int(m_py_fail.group(1) or 0) + int(m_py_fail.group(2) or 0)
            failed_count = f_num
            passed_count = max(0, total_tests - failed_count)

    failures: List[Dict[str, Any]] = []
    current_failure: Optional[Dict[str, Any]] = None

    # Parse failure details
    i = 0
    while i < len(lines):
        line = lines[i]

        # Pest test failure pattern:   FAILED  Tests\Feature\SomeTest > test description
        # or PHPUnit: 1) Tests\Unit\SomeTest::test_something
        # or Python unittest: FAIL: test_name (module.TestClass)
        m_pest_fail = re.search(r'FAILED\s+([A-Za-z0-9_\\\:]+\s*>\s*.+)', line)
        m_phpunit_fail = re.search(r'^\d+\)\s+([A-Za-z0-9_\\\:]+::[A-Za-z0-9_]+)', line)
        m_py_fail_hdr = re.search(r'^(?:FAIL|ERROR):\s+([a-zA-Z0-9_]+)\s+\((.+)\)', line)

        if m_pest_fail or m_phpunit_fail or m_py_fail_hdr:
            if m_pest_fail:
                test_name = m_pest_fail.group(1).strip()
            elif m_phpunit_fail:
                test_name = m_phpunit_fail.group(1).strip()
            else:
                test_name = f"{m_py_fail_hdr.group(2)} > {m_py_fail_hdr.group(1)}"
            current_failure = {
                "test": test_name,
                "file": None,
                "line": None,
                "reason": "",
                "app_origin": None,
                "snippet": ""
            }
            failures.append(current_failure)

            # Advance to extract failure reason and file
            i += 1
            reason_lines = []
            while i < len(lines):
                cur = lines[i]
                m_path = re.search(r'(?:at\s+)?([a-zA-Z0-9_\-\./]+\.php):(\d+)', cur)
                if m_path:
                    p_file = m_path.group(1).strip()
                    p_line = int(m_path.group(2))
                    if not any(v in p_file for v in VENDOR_IGNORE):
                        current_failure["file"] = p_file
                        current_failure["line"] = p_line
                        break
                    elif not current_failure.get("file"):
                        current_failure["file"] = p_file
                        current_failure["line"] = p_line

                if "Failed asserting that" in cur or "Expected" in cur or "Exception:" in cur or "Error:" in cur:
                    reason_lines.append(cur.strip())
                elif reason_lines and not cur.startswith("  ---") and not m_path:
                    # Multi-line reason
                    if len(reason_lines) < 3 and cur.strip():
                        reason_lines.append(cur.strip())

                if "FAILED" in cur or re.match(r'^\d+\)', cur):
                    # Next failure started
                    i -= 1
                    break
                i += 1

            if reason_lines:
                current_failure["reason"] = " ".join(reason_lines)

        # Look for application code stack frames
        if current_failure and (line.strip().startswith("#") or line.strip().startswith("at ")):
            if not any(v in line for v in VENDOR_IGNORE):
                # Candidate app frame
                frame_m = re.search(r'(?:#\d+\s+)?([a-zA-Z0-9_\-\./]+\.php)(?:\((\d+)\)|:(\d+))', line)
                if frame_m:
                    f_path = frame_m.group(1)
                    f_line = frame_m.group(2) or frame_m.group(3)
                    if not current_failure.get("app_origin") and not any(v in f_path for v in VENDOR_IGNORE):
                        current_failure["app_origin"] = f"{f_path}:{f_line}"

        i += 1

    # Extract code snippets for each failure
    for f in failures:
        target_file = f.get("file")
        target_line = f.get("line")
        if target_file and target_line:
            full_path = target_file
            if cwd and not os.path.isabs(target_file):
                full_path = os.path.normpath(os.path.join(cwd, target_file))
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        flines = fp.readlines()
                    idx = target_line - 1
                    start_idx = max(0, idx - 2)
                    end_idx = min(len(flines), idx + 3)
                    snip_lines = []
                    for l_idx in range(start_idx, end_idx):
                        prefix = " >" if l_idx == idx else "  "
                        snip_lines.append(f"{prefix} {l_idx + 1:3d}| {flines[l_idx].rstrip()}")
                    f["snippet"] = "\n".join(snip_lines)
                except Exception:
                    pass

    # Build Output Card
    if not failures and passed_count > 0:
        status = "passed"
        card = f"=== Test Isolation: ALL PASSED ===\nStatus: PASS ({passed_count} tests passed{f' in {time_str}' if time_str else ''})"
    elif failures:
        status = "failed"
        card_lines = [
            f"=== Test Isolation: {len(failures)} Failure(s) Distilled ===",
            f"Summary: {len(failures)} failed, {passed_count} passed",
            "-" * 70
        ]
        for idx, f in enumerate(failures, 1):
            card_lines.append(f"[{idx}] {f['test']}")
            if f['file']:
                card_lines.append(f"    Location: {f['file']}:{f['line']}")
            if f['reason']:
                card_lines.append(f"    Reason:   {f['reason']}")
            if f['app_origin'] and f['app_origin'] != f"{f['file']}:{f['line']}":
                card_lines.append(f"    App Origin: {f['app_origin']}")
            if f['snippet']:
                card_lines.append("    Snippet:")
                for sline in f['snippet'].splitlines():
                    card_lines.append(f"      {sline}")
            card_lines.append("-" * 70)
        card = "\n".join(card_lines)
    else:
        status = "unknown"
        # Return first 15 lines of raw output stripped of ANSI
        card = "=== Test Output (Raw Filtered) ===\n" + "\n".join(lines[:20])

    return {
        "status": status,
        "failed_count": len(failures),
        "passed_count": passed_count,
        "failures": failures,
        "card": card
    }

def run_test_isolate(cmd: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes the given test command and isolates failure diagnostics.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=120
        )
        return parse_test_output(proc.stdout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "failed_count": 1,
            "passed_count": 0,
            "failures": [],
            "card": f"Error: Test command timed out after 120s: {' '.join(cmd)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "failed_count": 1,
            "passed_count": 0,
            "failures": [],
            "card": f"Error executing test command: {e}"
        }
