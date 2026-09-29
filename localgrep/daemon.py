#!/usr/bin/env python3
import sys
import os
import signal
import socket
import json
import subprocess
import re
import warnings
import time
import fcntl

def get_runtime_dir():
    runtime_dir = os.path.expanduser("~/.local/localgrep")
    try:
        os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
        os.chmod(runtime_dir, 0o700)
        return runtime_dir
    except Exception:
        uid = os.getuid() if hasattr(os, 'getuid') else 1000
        fallback = f"/tmp/localgrep-{uid}"
        try:
            os.makedirs(fallback, mode=0o700, exist_ok=True)
            os.chmod(fallback, 0o700)
            return fallback
        except Exception:
            return "/tmp"

RUNTIME_DIR = get_runtime_dir()
SOCKET_PATH = os.path.join(RUNTIME_DIR, "daemon.sock")
PID_FILE = os.path.join(RUNTIME_DIR, "daemon.pid")
LOG_FILE = os.path.join(RUNTIME_DIR, "daemon.log")
DEFAULT_ONNX_PATH = os.path.join(RUNTIME_DIR, "model.onnx")
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

STOP_WORDS = {
    "where", "what", "which", "when", "how", "who", "whom", "this", "that",
    "there", "here", "with", "from", "have", "been", "does", "checked",
    "check", "find", "show", "code", "file", "logic", "implementation",
    "look", "give", "tell", "name", "component", "active", "page",
    "function", "method", "class", "trait", "interface", "variable"
}

GENERIC_TERMS = {
    "product", "products", "item", "items", "data", "value", "values",
    "model", "models", "user", "users"
}

tokenizer = None
onnx_session = None
torch_model = None
sess_inputs = set()
start_time = time.time()
_pid_file_fd = None

def acquire_pid_lock(pid_path):
    global _pid_file_fd
    try:
        _pid_file_fd = open(pid_path, 'a+')
        fcntl.flock(_pid_file_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _pid_file_fd.seek(0)
        _pid_file_fd.truncate()
        _pid_file_fd.write(str(os.getpid()) + "\n")
        _pid_file_fd.flush()
        return True
    except (IOError, OSError):
        return False

def get_rss_mb():
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if 'VmRSS' in line:
                    parts = line.split()
                    return round(int(parts[1]) / 1024, 1)
    except Exception:
        pass
    return None

def init_model():
    global tokenizer, onnx_session, torch_model, sess_inputs
    from transformers import AutoTokenizer, logging
    logging.set_verbosity_error()
    warnings.filterwarnings("ignore")

    token = os.environ.get("HF_TOKEN")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, token=token)

    # 1. Check local ONNX model paths
    pkg_onnx = os.path.join(os.path.dirname(__file__), "model.onnx")
    onnx_file = pkg_onnx if os.path.exists(pkg_onnx) else (DEFAULT_ONNX_PATH if os.path.exists(DEFAULT_ONNX_PATH) else None)

    # 2. If ONNX model is missing on disk, download the official ONNX model from Hugging Face
    if not onnx_file:
        try:
            from huggingface_hub import hf_hub_download
            onnx_file = hf_hub_download(repo_id=MODEL_NAME, filename="onnx/model.onnx", token=token)
        except Exception:
            onnx_file = None

    if onnx_file and os.path.exists(onnx_file):
        try:
            import onnxruntime as ort
            sess_opts = ort.SessionOptions()
            # Disable memory arena and pattern caching to prevent unbounded RSS growth
            sess_opts.enable_cpu_mem_arena = False
            sess_opts.enable_mem_pattern = False
            sess_opts.intra_op_num_threads = min(4, os.cpu_count() or 1)
            onnx_session = ort.InferenceSession(onnx_file, sess_opts, providers=['CPUExecutionProvider'])
            sess_inputs = {i.name for i in onnx_session.get_inputs()}

            # Warmup with dynamic input keys (handling input_ids, attention_mask, token_type_ids)
            dummy = tokenizer([["warmup", "test"]], padding=True, truncation=True, return_tensors='np')
            feed = {k: v for k, v in dummy.items() if k in sess_inputs}
            _ = onnx_session.run(["logits"], feed)
            del dummy, feed
            import gc
            gc.collect()
            return
        except Exception:
            onnx_session = None

    # 3. Fallback to PyTorch
    try:
        import torch
        from transformers import AutoModelForSequenceClassification
        torch_model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, token=token)
        torch_model.eval()
        dummy = tokenizer([["warmup", "test"]], padding=True, truncation=True, return_tensors='pt')
        with torch.no_grad():
            _ = torch_model(**dummy)
        del dummy
        import gc
        gc.collect()
    except ImportError:
        raise RuntimeError(
            "LocalGrep requires either onnxruntime with model.onnx (recommended) or PyTorch ('pip install torch'). "
            "Neither ONNX session could be loaded nor PyTorch was found."
        )

def run_cross_encoder_inference(pairs, max_length=256):
    global onnx_session, tokenizer, sess_inputs, torch_model
    if not pairs:
        return []

    batch_size = 16
    all_logits = []

    if onnx_session is not None:
        if not sess_inputs:
            sess_inputs = {i.name for i in onnx_session.get_inputs()}

        for i in range(0, len(pairs), batch_size):
            batch_pairs = pairs[i:i + batch_size]
            enc = tokenizer(batch_pairs, padding=True, truncation=True, return_tensors='np', max_length=max_length)
            feed = {k: v for k, v in enc.items() if k in sess_inputs}
            out = onnx_session.run(["logits"], feed)[0]
            all_logits.extend(out.flatten().tolist())
            del enc, feed, out

        import gc
        gc.collect()
        return all_logits

    import torch
    for i in range(0, len(pairs), batch_size):
        batch_pairs = pairs[i:i + batch_size]
        inputs = tokenizer(batch_pairs, padding=True, truncation=True, return_tensors='pt', max_length=max_length)
        with torch.no_grad():
            logits = torch_model(**inputs).logits.view(-1).float().tolist()
            all_logits.extend(logits)
        del inputs

    import gc
    gc.collect()
    return all_logits

def stem_word(word: str) -> list[str]:
    w = word.lower()
    variants = set()
    if len(w) < 4:
        return [w]

    bases = [w]
    if w.startswith("re") and len(w) > 5:
        bases.append(w[2:])
    if w.startswith("un") and len(w) > 5:
        bases.append(w[2:])

    for b in bases:
        variants.add(b)
        if b.endswith("ies") and len(b) > 4:
            variants.add(b[:-3] + "y")
        elif b.endswith(("ses", "xes", "zes", "ches", "shes")) and len(b) > 4:
            variants.add(b[:-2])
        elif b.endswith("s") and not b.endswith(("ss", "has", "us", "is", "as")) and len(b) > 3:
            variants.add(b[:-1])

        if b.endswith("ing") and len(b) > 5:
            variants.add(b[:-3])
            variants.add(b[:-3] + "e")
        elif b.endswith("ed") and len(b) > 4:
            variants.add(b[:-2])
            variants.add(b[:-1])

    if "calc" in w:
        variants.add("calc")
        variants.add("recalc")

    return [v for v in variants if len(v) >= 3 and v != w]

PROGRAMMING_SYNONYMS = {
    # CRUD & Operations
    "fetch": ["get", "retrieve", "find", "load", "query"],
    "get": ["fetch", "retrieve", "find", "load", "query"],
    "find": ["search", "query", "lookup", "locate", "where"],
    "search": ["find", "filter", "query", "index", "lookup"],
    "save": ["store", "persist", "insert", "create", "write"],
    "create": ["make", "build", "store", "save", "generate"],
    "update": ["edit", "modify", "patch", "sync", "refresh", "save"],
    "delete": ["remove", "destroy", "drop", "purge", "clear"],
    "remove": ["delete", "detach", "strip", "clear"],

    # Computational & Processing
    "calculate": ["recalculate", "compute", "calc", "recalc", "total", "sum"],
    "recalculate": ["calculate", "recalc", "calc", "compute", "sync", "refresh", "update"],
    "compute": ["calculate", "evaluate", "process"],
    "recalculates": ["recalculate", "calculate", "recalc", "compute", "update"],
    "validate": ["verify", "check", "assert", "sanitize", "rule"],
    "verify": ["validate", "check", "confirm", "ensure"],

    # Status & States
    "published": ["publish", "active", "status", "draft", "visible", "online", "enabled"],
    "publish": ["published", "active", "status", "draft", "visible"],
    "active": ["enabled", "status", "live", "published", "valid"],
    "status": ["state", "condition", "published", "active"],

    # Entities & Domain
    "price": ["pricing", "cost", "amount", "rate", "fee", "sale_price"],
    "prices": ["price", "pricing", "cost", "amount", "sale_price"],
    "variation": ["variant", "attribute", "option", "sku", "product"],
    "variations": ["variation", "variant", "attribute", "option", "sku"],
    "product": ["item", "catalog", "sku", "goods"],
    "products": ["product", "item", "catalog"],
    "cart": ["basket", "checkout", "order", "item"],
    "order": ["invoice", "checkout", "purchase", "transaction"],
    "discount": ["coupon", "sale", "voucher", "promo"],
    "customer": ["user", "client", "buyer", "account"],
    "user": ["account", "member", "customer", "auth"],

    # Framework & Eloquent & Debugging
    "bug": ["issue", "fix", "error", "patch", "wherehas", "orwherehas"],
    "issue": ["bug", "problem", "fix"],
    "wherehas": ["orwherehas", "relation", "scope", "query"],
    "orwherehas": ["wherehas", "relation", "scope", "query"],
    "relation": ["relationship", "belongs", "hasone", "hasmany", "wherehas"],
    "cache": ["redis", "remember", "store", "memory"],
    "event": ["listener", "dispatch", "broadcast", "trigger"],
    "job": ["queue", "worker", "dispatch", "schedule"],
}

def extract_search_terms(query):
    # Extract raw alphanumeric words (preserving compound words like orWhereHas, camelCase, snake_case)
    raw_tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]+', query)]
    split_query = re.sub(r'([a-z])([A-Z])', r'\1 \2', query).replace('-', ' ').replace('_', ' ')
    split_tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]+', split_query)]
    combined = []
    seen = set()
    for t in raw_tokens + split_tokens:
        if t not in seen:
            seen.add(t)
            combined.append(t)
    meaningful = [t for t in combined if len(t) > 2 and t not in STOP_WORDS]
    return meaningful if meaningful else [t for t in combined if len(t) > 1]

def expand_search_terms(terms, max_terms=16):
    expanded = []
    seen = set()

    def add(t):
        tc = t.lower().strip()
        if len(tc) >= 3 and tc not in seen and tc not in STOP_WORDS:
            seen.add(tc)
            expanded.append(tc)

    # 1. Original terms first
    for t in terms:
        add(t)

    # 2. Direct taxonomy synonyms (high value)
    for t in terms:
        t_low = t.lower()
        for syn in PROGRAMMING_SYNONYMS.get(t_low, [])[:3]:
            add(syn)

    # 3. Algorithmic stems
    for t in terms:
        for s in stem_word(t):
            add(s)

    # 4. Synonyms of stems
    for t in terms:
        for s in stem_word(t):
            for syn in PROGRAMMING_SYNONYMS.get(s, [])[:2]:
                add(syn)

    # Prioritize specific action/keyword terms before generic entity terms
    expanded.sort(key=lambda t: (t in GENERIC_TERMS, -len(t)))
    return expanded[:max_terms]

def extract_meaningful_file_snippet(full_path, terms, max_lines=12):
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        if not all_lines:
            return "", 1

        # 1. Prefer line matching one of the search terms
        for idx, line in enumerate(all_lines):
            line_lower = line.lower()
            if any(t in line_lower for t in terms):
                start = max(0, idx - 1)
                end = min(len(all_lines), start + max_lines)
                return "".join(all_lines[start:end]).strip(), start + 1

        # 2. Look for declaration header (class, function, def, export)
        decl_keywords = ("class ", "interface ", "trait ", "function ", "def ", "export ", "const ", "<template", "<script")
        for idx, line in enumerate(all_lines):
            stripped = line.strip()
            if any(stripped.startswith(k) for k in decl_keywords):
                end = min(len(all_lines), idx + max_lines)
                return "".join(all_lines[idx:end]).strip(), idx + 1

        # 3. Fallback to start of file
        return "".join(all_lines[:max_lines]).strip(), 1
    except Exception:
        return "", 1

def get_candidates(query, cwd, top_k=3, max_candidates=50, search_dirs=None):
    terms = extract_search_terms(query)
    if not terms:
        return []

    expanded = expand_search_terms(terms, max_terms=12)
    candidates = {}

    if not search_dirs:
        target_candidates = ["resources", "app", "routes", "config", "src", "packages", "lib", "Modules"]

        # Dynamic discovery for modular monorepos (e.g. Laravel Modules via config/modules.php)
        modules_cfg = os.path.join(cwd, "config", "modules.php")
        if os.path.isfile(modules_cfg):
            try:
                with open(modules_cfg, "r", encoding="utf-8", errors="ignore") as f:
                    cfg_text = f.read()
                m = re.search(r"['\"]modules['\"]\s*=>\s*base_path\(['\"]([^'\"]+)['\"]\)", cfg_text)
                if m:
                    custom_module_path = m.group(1).strip("/\\")
                    if custom_module_path and custom_module_path not in target_candidates:
                        target_candidates.append(custom_module_path)
            except Exception:
                pass

        # Environment variable override for arbitrary monorepo structures
        env_extra_dirs = os.environ.get("LOCALGREP_DIRS")
        if env_extra_dirs:
            for d in env_extra_dirs.split(","):
                d_clean = d.strip()
                if d_clean and d_clean not in target_candidates:
                    target_candidates.append(d_clean)

        target_dirs = [d for d in target_candidates if os.path.isdir(os.path.join(cwd, d))]
        search_dirs = target_dirs if target_dirs else ["."]

    globs = [
        "--glob", "!node_modules/**",
        "--glob", "!.git/**",
        "--glob", "!storage/**",
        "--glob", "!public/**",
        "--glob", "!dist/**",
        "--glob", "!graphify-out/**",
        "--glob", "!resources/views/vendor/**",
        "--glob", "!**/prompts/**",
        "--glob", "!*.lock"
    ]
    if "." in search_dirs:
        globs += ["--glob", "!vendor/**"]
    if not search_dirs or "tests" not in search_dirs:
        globs += ["--glob", "!tests/**"]

    # 1. Content-based search with ripgrep (Primary source of truth)
    try:
        regex_pattern = "|".join(expanded[:8])
        cmd = [
            "rg", "-i", "-n", "-C", "3", "--max-count", "10"
        ] + globs + ["-e", regex_pattern] + search_dirs

        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        blocks = res.stdout.strip().split("\n--\n") if res.stdout else []

        scored_blocks = []
        for block in blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue
            first_line = lines[0]
            parts = first_line.split(":", 2) if ":" in first_line else first_line.split("-", 2)
            filepath = parts[0].strip() if len(parts) > 0 else ""
            lineno = parts[1].strip() if len(parts) > 1 else "1"
            snippet = "\n".join(lines[:7])

            text_lower = (filepath + " " + snippet).lower()
            score = sum(3 for t in terms if t in text_lower) + sum(1 for t in expanded if t in text_lower)
            if any(filepath.endswith(ext) for ext in (".php", ".ts", ".vue", ".js", ".py")):
                score += 1
            scored_blocks.append((score, filepath, lineno, snippet))

        scored_blocks.sort(key=lambda x: x[0], reverse=True)

        for _, filepath, lineno, snippet in scored_blocks:
            if filepath and snippet and (filepath, lineno) not in candidates:
                candidates[(filepath, lineno)] = {
                    "filepath": filepath,
                    "lineno": lineno,
                    "snippet": snippet,
                    "path_bonus": 0.0
                }
            if len(candidates) >= max_candidates:
                break
    except Exception:
        pass

    # 2. Path-based search (Only to supplement if content search found few candidates)
    if len(candidates) < max_candidates:
        try:
            path_pattern = "|".join(terms)
            res_files = subprocess.run(
                ["rg", "--files"] + globs + ["-i", "-e", path_pattern] + search_dirs,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            if res_files.stdout:
                file_lines = [f.strip() for f in res_files.stdout.strip().split("\n") if f.strip()]
                def path_score(p):
                    p_lower = p.lower()
                    base = os.path.basename(p_lower)
                    base_matches = sum(2 for t in terms if t in base)
                    path_matches = sum(1 for t in terms if t in p_lower)
                    return base_matches + path_matches

                sorted_files = sorted(file_lines, key=path_score, reverse=True)
                for filepath in sorted_files[:10]:
                    # Don't add file if we already have content matches from it
                    if any(k[0] == filepath for k in candidates):
                        continue

                    full_path = os.path.join(cwd, filepath)
                    snippet, best_line = extract_meaningful_file_snippet(full_path, terms)
                    if snippet:
                        candidates[(filepath, str(best_line))] = {
                            "filepath": filepath,
                            "lineno": str(best_line),
                            "snippet": snippet,
                            "path_bonus": 0.5
                        }
                    if len(candidates) >= max_candidates:
                        break
        except Exception:
            pass

    cand_list = list(candidates.values())
    if not cand_list:
        return []

    # 3. Model scoring via ONNX / PyTorch
    pairs = [[query, f"File: {c['filepath']}\n{c['snippet']}"] for c in cand_list]
    logits = run_cross_encoder_inference(pairs, max_length=384)

    ranked = []
    for score, cand in zip(logits, cand_list):
        total_score = score + cand["path_bonus"]
        content_lower = (cand["filepath"] + " " + cand["snippet"]).lower()
        matched_count = sum(1 for t in terms if t in content_lower)
        total_score += matched_count * 2.5
        if any(cand["filepath"].endswith(ext) for ext in (".php", ".ts", ".vue", ".js", ".py")):
            total_score += 1.0
        ranked.append({
            "score": round(total_score, 3),
            "filepath": cand["filepath"],
            "lineno": cand["lineno"],
            "snippet": cand["snippet"]
        })

    del pairs, cand_list, logits
    import gc
    gc.collect()

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]

def handle_prune(filepath, query, cwd, top_k=2):
    try:
        from localgrep.chunker import chunk_file
    except ImportError:
        try:
            from .chunker import chunk_file
        except ImportError:
            from chunker import chunk_file

    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full_path):
        return {"status": "error", "message": f"File not found: {filepath}"}

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        return {"status": "error", "message": str(e)}

    if not lines:
        return {"status": "ok", "results": []}

    chunks = chunk_file(filepath, lines)
    if not chunks:
        return {"status": "ok", "results": []}

    pairs = [[query, c["text"]] for c in chunks]
    logits = run_cross_encoder_inference(pairs, max_length=512)

    ranked = []
    for score, c in zip(logits, chunks):
        ranked.append({
            "score": score,
            "filepath": filepath,
            "start": c["start"],
            "end": c["end"],
            "snippet": c["text"].strip(),
            "kind": c.get("kind", "snippet")
        })

    del pairs, chunks, logits
    import gc
    gc.collect()

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"status": "ok", "results": ranked[:top_k]}

def handle_filter(text, query, top_k=5):
    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not raw_lines:
        return {"status": "ok", "results": []}

    terms = extract_search_terms(query)
    candidates = raw_lines
    if len(raw_lines) > 50 and terms:
        filtered = [l for l in raw_lines if any(t in l.lower() for t in terms)]
        if len(filtered) >= top_k:
            candidates = filtered[:50]
        else:
            candidates = (filtered + [l for l in raw_lines if l not in filtered])[:50]
    elif len(raw_lines) > 50:
        candidates = raw_lines[:50]

    pairs = [[query, line] for line in candidates]
    logits = run_cross_encoder_inference(pairs, max_length=256)

    ranked = []
    for score, line in zip(logits, candidates):
        ranked.append({
            "score": score,
            "line": line
        })

    del pairs, candidates, logits
    import gc
    gc.collect()

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"status": "ok", "results": ranked[:top_k]}

def handle_test(query, cwd, top_k=3):
    test_dirs = [d for d in ["tests", "test", "spec"] if os.path.isdir(os.path.join(cwd, d))]
    target = test_dirs if test_dirs else ["."]
    res = get_candidates(query, cwd, top_k=top_k, search_dirs=target)
    return {"status": "ok", "results": res}

def handle_error(error_text, cwd, top_k=3):
    clean_error = re.sub(r'#\d+.*', '', error_text)
    terms = extract_search_terms(clean_error)
    query = " ".join(terms[:5]) if terms else error_text[:100]
    res = get_candidates(query, cwd, top_k=top_k)
    return {"status": "ok", "results": res}

def handle_skill(query, cwd, top_k=3):
    import glob
    dirs = [
        os.path.join(cwd, ".agents/skills"),
        os.path.join(cwd, ".claude/skills"),
        os.path.expanduser("~/.claude/skills"),
        os.path.expanduser("~/.gemini/antigravity-cli/builtin/skills"),
        os.path.expanduser("~/.gemini/config/skills"),
    ]

    skills = []
    seen = set()
    for d in dirs:
        if os.path.exists(d):
            for s in glob.glob(os.path.join(d, "*/SKILL.md")):
                name = os.path.basename(os.path.dirname(s))
                if name in seen:
                    continue
                seen.add(name)
                try:
                    with open(s, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    parts = content.split("---", 2)
                    yaml_block = parts[1] if len(parts) >= 3 else ""
                    desc_match = re.search(r'description:\s*(?:>|\|)?\s*[\'\"]?(.*?)[\'\"]?\n(?=[a-zA-Z0-9_-]+:|$)', yaml_block, re.DOTALL)
                    desc = desc_match.group(1).strip() if desc_match else ""
                    if not desc:
                        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("---") and not l.startswith("#")]
                    desc = ' '.join(desc.split())
                    skills.append({
                        "name": name,
                        "path": s,
                        "desc": desc,
                        "text": f"{name} - {desc}"
                    })
                except Exception:
                    pass

    if not skills:
        return {"status": "ok", "results": []}

    terms = extract_search_terms(query)
    pairs = [[query, s["text"]] for s in skills]
    logits = run_cross_encoder_inference(pairs, max_length=256)

    ranked = []
    for score, s in zip(logits, skills):
        boost = 0.0
        name_lower = s["name"].lower()
        desc_lower = s["desc"].lower()

        if terms:
            if any(t in name_lower for t in terms):
                boost += 3.0
            matching_terms = sum(1 for t in terms if t in desc_lower)
            boost += matching_terms * 0.8

        ranked.append({
            "score": score + boost,
            "name": s["name"],
            "path": s["path"],
            "desc": s["desc"]
        })

    del pairs, skills, logits
    import gc
    gc.collect()

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"status": "ok", "results": ranked[:top_k]}

def handle_client(conn):
    try:
        conn.settimeout(30.0)
        chunks = []
        total_bytes = 0
        max_bytes = 10 * 1024 * 1024

        while True:
            chunk = conn.recv(16384)
            if not chunk:
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise ValueError("Payload exceeds maximum size (10 MB)")

        if not chunks:
            return

        raw_req = b"".join(chunks).decode('utf-8')
        req = json.loads(raw_req)
        action = req.get("action", "search")
        cwd = req.get("cwd", os.getcwd())
        top_k = req.get("top_k", 3)

        if action == "status":
            resp = {
                "status": "ok",
                "backend": "ONNX Runtime" if onnx_session is not None else "PyTorch",
                "rss_mb": get_rss_mb(),
                "uptime_seconds": round(time.time() - start_time, 1)
            }
        elif action == "stop":
            resp = {"status": "ok", "message": "Daemon shutting down"}
            conn.sendall(json.dumps(resp).encode('utf-8'))
            conn.close()
            cleanup()
            return
        elif action == "prune":
            filepath = req.get("file", "")
            query = req.get("query", "")
            resp = handle_prune(filepath, query, cwd, top_k=top_k)
        elif action == "filter":
            text = req.get("text", "")
            query = req.get("query", "")
            resp = handle_filter(text, query, top_k=top_k)
        elif action == "test":
            query = req.get("query", "")
            resp = handle_test(query, cwd, top_k=top_k)
        elif action == "error":
            error_text = req.get("error", "")
            resp = handle_error(error_text, cwd, top_k=top_k)
        elif action == "skill":
            query = req.get("query", "")
            resp = handle_skill(query, cwd, top_k=top_k)
        else:
            query = req.get("query", "")
            terms = extract_search_terms(query)
            if not terms and query.strip():
                resp = {
                    "status": "warning",
                    "message": "Query contains no Latin keywords. Please use English/Latin terms for code search (e.g. 'payment callback').",
                    "results": []
                }
            else:
                res = get_candidates(query, cwd, top_k=top_k)
                resp = {"status": "ok", "results": res}

        conn.sendall(json.dumps(resp).encode('utf-8'))
    except Exception as e:
        try:
            err = json.dumps({"status": "error", "message": str(e)})
            conn.sendall(err.encode('utf-8'))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
        import gc
        gc.collect()

def cleanup(*args):
    global _pid_file_fd
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
    if _pid_file_fd is not None:
        try:
            fcntl.flock(_pid_file_fd.fileno(), fcntl.LOCK_UN)
            _pid_file_fd.close()
        except OSError:
            pass
    if os.path.exists(PID_FILE):
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
    sys.exit(0)

def start_daemon_server():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    if not acquire_pid_lock(PID_FILE):
        sys.stderr.write(f"LocalGrep daemon already running (PID locked at {PID_FILE}).\n")
        sys.exit(0)

    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    init_model()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(10)
    try:
        os.chmod(SOCKET_PATH, 0o600)
    except OSError:
        pass

    while True:
        try:
            conn, _ = server.accept()
            handle_client(conn)
        except Exception:
            continue

if __name__ == "__main__":
    start_daemon_server()
