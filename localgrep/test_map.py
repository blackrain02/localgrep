import os
import re
import sys
import subprocess
from typing import Dict, Any, List, Optional, Tuple

def find_candidate_test_files(cwd: str, module_dir: Optional[str] = None) -> List[str]:
    test_files = []
    # 1. Module-specific tests
    if module_dir and os.path.isdir(os.path.join(cwd, module_dir, "tests")):
        for root, _, files in os.walk(os.path.join(cwd, module_dir, "tests")):
            for f in files:
                if f.endswith("Test.php") or f.endswith(".test.ts") or f.endswith(".spec.ts"):
                    test_files.append(os.path.relpath(os.path.join(root, f), cwd))

    # 2. Global app tests
    global_tests_dir = os.path.join(cwd, "tests")
    if os.path.isdir(global_tests_dir):
        for root, _, files in os.walk(global_tests_dir):
            for f in files:
                if f.endswith("Test.php") or f.endswith(".test.ts") or f.endswith(".spec.ts"):
                    rel = os.path.relpath(os.path.join(root, f), cwd)
                    if rel not in test_files:
                        test_files.append(rel)

    # 3. All vendor/bina module tests if not already scoped
    if not module_dir and os.path.isdir(os.path.join(cwd, "vendor", "bina")):
        for root, _, files in os.walk(os.path.join(cwd, "vendor", "bina")):
            if "/tests" in root:
                for f in files:
                    if f.endswith("Test.php"):
                        rel = os.path.relpath(os.path.join(root, f), cwd)
                        if rel not in test_files:
                            test_files.append(rel)

    return test_files

def extract_file_symbols(filepath: str, cwd: str) -> Tuple[str, str, List[str]]:
    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    # Clean base name (e.g. UserController -> User, ProductService -> Product)
    stripped_name = re.sub(r'(Controller|Service|Repository|Request|Resource|Job|Listener|Event|Model)$', '', base_name)
    if not stripped_name:
        stripped_name = base_name

    classes = [base_name, stripped_name]
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            decl_matches = re.findall(r'(?:class|interface|trait|enum)\s+([A-Za-z0-9_]+)', content)
            for dm in decl_matches:
                if dm not in classes:
                    classes.append(dm)
    except Exception:
        pass

    return base_name, stripped_name, classes

def map_test_for_file(filepath: str, cwd: str = ".") -> Dict[str, Any]:
    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath
    rel_path = os.path.relpath(full_path, cwd)
    if not os.path.isfile(full_path):
        return {
            "status": "error",
            "message": f"Target file not found: {filepath}",
            "tests": []
        }

    # Detect if file belongs to vendor/bina module
    module_dir = None
    if "vendor/bina/" in rel_path:
        parts = rel_path.split("/")
        idx = parts.index("bina")
        if len(parts) > idx + 1:
            module_dir = "/".join(parts[:idx+2])

    base_name, stripped_name, classes = extract_file_symbols(rel_path, cwd)
    all_tests = find_candidate_test_files(cwd, module_dir)

    ranked_tests = []
    for tf in all_tests:
        tf_base = os.path.splitext(os.path.basename(tf))[0]
        score = 0
        reasons = []

        # 1. Exact Name Match: User.php -> UserTest.php
        if tf_base == f"{base_name}Test" or tf_base == f"{stripped_name}Test":
            score += 100
            reasons.append(f"Exact match on {tf_base}")
        # 2. Prefix Match: UserCrudTest.php for User
        elif tf_base.startswith(f"{base_name}") or tf_base.startswith(f"{stripped_name}"):
            score += 70
            reasons.append(f"Prefix match on {tf_base}")
        # 3. Substring Match: HolidayTest.php for Holiday.php
        elif stripped_name.lower() in tf_base.lower():
            score += 50
            reasons.append(f"Keyword '{stripped_name}' in test name")

        # 4. Same module priority
        if module_dir and tf.startswith(module_dir):
            score += 30
            reasons.append("Same module")

        # 5. Content reference check for top candidates
        if score >= 30:
            try:
                tf_full = os.path.join(cwd, tf)
                with open(tf_full, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(5000)
                    for c in classes:
                        if c in content:
                            score += 20
                            reasons.append(f"References {c}")
                            break
            except Exception:
                pass

        if score > 0:
            ranked_tests.append({
                "test_file": tf,
                "score": score,
                "reasons": reasons
            })

    ranked_tests.sort(key=lambda t: t["score"], reverse=True)

    return {
        "status": "ok",
        "filepath": rel_path,
        "base_name": base_name,
        "matched_tests": ranked_tests[:5]
    }

def run_mapped_test(test_file: str, cwd: str = ".") -> Dict[str, Any]:
    cmd = ["php", "artisan", "test", test_file, "--compact"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )
        raw_output = proc.stdout + "\n" + proc.stderr
        passed = proc.returncode == 0

        # Run through test-isolate distillation
        try:
            from localgrep.test_isolate import distill_test_failure
            distilled = distill_test_failure(raw_output)
        except Exception:
            distilled = raw_output.strip()

        return {
            "status": "ok",
            "test_file": test_file,
            "passed": passed,
            "returncode": proc.returncode,
            "distilled_output": distilled
        }
    except Exception as e:
        return {
            "status": "error",
            "test_file": test_file,
            "message": str(e)
        }
