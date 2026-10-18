import os
import re
import sys
import subprocess
import glob
from typing import Dict, Any, List, Optional, Tuple

def get_all_test_directories(cwd: str, module_dir: Optional[str] = None) -> List[str]:
    dirs = []
    if module_dir and os.path.isdir(os.path.join(cwd, module_dir, "tests")):
        dirs.append(os.path.join(module_dir, "tests"))
    if os.path.isdir(os.path.join(cwd, "tests")):
        dirs.append("tests")
    for p in glob.glob(os.path.join(cwd, "vendor", "bina", "*", "tests")):
        if os.path.isdir(p):
            rel = os.path.relpath(p, cwd)
            if rel not in dirs:
                dirs.append(rel)
    for p in glob.glob(os.path.join(cwd, "Modules", "*", "tests")):
        if os.path.isdir(p):
            rel = os.path.relpath(p, cwd)
            if rel not in dirs:
                dirs.append(rel)
    return dirs

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

    # 3. All vendor/bina module tests
    if os.path.isdir(os.path.join(cwd, "vendor", "bina")):
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

    classes = [base_name]
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            decl_matches = re.findall(
                r'^\s*(?:final\s+|abstract\s+|readonly\s+)*(?:class|interface|trait|enum)\s+([A-Za-z0-9_]+)',
                content,
                re.MULTILINE
            )
            for dm in decl_matches:
                if dm not in classes and len(dm) >= 3 and dm.lower() not in {"class", "trait", "interface", "enum", "error", "test", "of"}:
                    classes.append(dm)
    except Exception:
        pass

    return base_name, stripped_name, classes

def find_referencing_test_files(symbols: List[str], test_dirs: List[str], cwd: str) -> Dict[str, List[str]]:
    refs = {}
    valid_dirs = [d for d in test_dirs if os.path.isdir(os.path.join(cwd, d))]
    if not valid_dirs or not symbols:
        return refs

    for sym in symbols:
        if len(sym) < 3 or sym.lower() in {"class", "function", "test", "enum", "trait", "interface", "null", "true", "false", "this", "of"}:
            continue
        try:
            cmd = ["rg", "-l", "-w", sym, "-g", "*Test.php", "-g", "*.test.ts", "-g", "*.spec.ts", "--max-count", "1"] + valid_dirs
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            if proc.stdout:
                for line in proc.stdout.strip().split("\n"):
                    rel = line.strip()
                    if rel:
                        rel_norm = os.path.relpath(os.path.join(cwd, rel), cwd)
                        if rel_norm not in refs:
                            refs[rel_norm] = []
                        if sym not in refs[rel_norm]:
                            refs[rel_norm].append(sym)
        except Exception:
            pass
    return refs

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
    elif "Modules/" in rel_path:
        parts = rel_path.split("/")
        idx = parts.index("Modules")
        if len(parts) > idx + 1:
            module_dir = "/".join(parts[:idx+2])

    base_name, stripped_name, classes = extract_file_symbols(rel_path, cwd)
    test_dirs = get_all_test_directories(cwd, module_dir)
    all_tests = find_candidate_test_files(cwd, module_dir)
    ref_map = find_referencing_test_files(classes, test_dirs, cwd)

    ranked_tests = []
    combined_test_files = list(set(all_tests + list(ref_map.keys())))

    for tf in combined_test_files:
        tf_base = os.path.splitext(os.path.basename(tf))[0]
        score = 0
        reasons = []

        # 1. Direct symbol reference in test code (via rg)
        if tf in ref_map:
            ref_syms = ref_map[tf]
            if base_name in ref_syms:
                score += 150
                reasons.append(f"References {base_name}")
            else:
                score += 120
                reasons.append(f"References {', '.join(ref_syms)}")

        # 2. Exact Name Match: User.php -> UserTest.php
        if tf_base == f"{base_name}Test":
            score += 200
            reasons.append(f"Exact match on {tf_base}")
        elif stripped_name != base_name and tf_base == f"{stripped_name}Test":
            score += 120
            reasons.append(f"Exact match on {tf_base}")
        # 3. Prefix Match
        elif tf_base.startswith(f"{base_name}"):
            score += 90
            reasons.append(f"Prefix match on {tf_base}")
        elif stripped_name != base_name and len(stripped_name) >= 4 and tf_base.startswith(f"{stripped_name}"):
            score += 60
            reasons.append(f"Prefix match on {tf_base}")
        # 4. Keyword in test name (only if specific enough)
        elif stripped_name != base_name and len(stripped_name) >= 5 and stripped_name.lower() in tf_base.lower():
            score += 35
            reasons.append(f"Keyword '{stripped_name}' in test name")

        # 5. Same module priority (ONLY bonus if already has direct reference or name match)
        if score > 0 and module_dir and tf.startswith(module_dir):
            score += 15
            reasons.append("Same module")

        # Discard tests with 0 relevance or only module-level noise
        if score >= 40:
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
