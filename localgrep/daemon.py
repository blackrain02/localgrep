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
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, token=token, local_files_only=True)
    except Exception:
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

def compute_file_path_score(filepath, terms, query):
    base = os.path.splitext(os.path.basename(filepath))[0].lower()
    f_lower = filepath.lower()
    q_compact = query.lower().replace(" ", "").replace("-", "").replace("_", "")

    score = 0.0
    # Exact or near-exact basename matches
    if q_compact and q_compact == base:
        score += 20.0
    elif q_compact and q_compact in base:
        score += 15.0
    elif terms and all(t in base for t in terms):
        score += 12.0
    else:
        score += sum(3.5 for t in terms if t in base)

    # General path matches
    score += sum(1.0 for t in terms if t in f_lower)

    # Noise dampening
    if "/lang/" in f_lower or "/locales/" in f_lower:
        score -= 15.0
    if filepath.endswith(".json") or filepath.endswith(".lock"):
        score -= 6.0
    if "/tests/" in f_lower or "/test/" in f_lower:
        score -= 4.0

    # Code extension preference
    if any(filepath.endswith(ext) for ext in (".vue", ".php", ".ts", ".js", ".py")):
        score += 2.0

    return score

def get_candidates(query, cwd, top_k=3, max_candidates=50, search_dirs=None):
    terms = extract_search_terms(query)
    if not terms:
        return []

    expanded = expand_search_terms(terms, max_terms=12)
    candidates = {}

    # Detect symbol / component intent for Tier 1 Fast-Path
    q_clean = query.strip()
    is_single_ident = bool(re.match(r'^[A-Za-z0-9_\-\.]+$', q_clean))
    is_camel_pascal = bool(re.search(r'[a-z][A-Z]', q_clean))
    is_symbol_intent = is_single_ident or is_camel_pascal or (
        len(terms) <= 2 and not any(w in q_clean.lower() for w in ("how", "what", "where", "why", "logic", "explain", "bug", "recalculates"))
    )

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

    # Dampen translation / dictionary noise unless explicitly queried
    if not any(k in query.lower() for k in ("lang", "translation", "locale", "dictionary")):
        globs += [
            "--glob", "!**/lang/**",
            "--glob", "!**/locales/**",
            "--glob", "!lang/**",
            "--glob", "!locales/**",
        ]

    # 1. Path-based search (Always executed to discover primary component & class files)
    try:
        res_files = subprocess.run(
            ["rg", "--files"] + globs + search_dirs,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        if res_files.stdout:
            file_lines = [f.strip() for f in res_files.stdout.strip().split("\n") if f.strip()]
            scored_files = []
            for f in file_lines:
                ps = compute_file_path_score(f, terms, query)
                if ps > 2.0:
                    scored_files.append((ps, f))
            scored_files.sort(key=lambda x: x[0], reverse=True)

            for ps, filepath in scored_files[:15]:
                full_path = os.path.join(cwd, filepath)
                snippet, best_line = extract_meaningful_file_snippet(full_path, terms)
                if snippet:
                    key = (filepath, str(best_line))
                    candidates[key] = {
                        "filepath": filepath,
                        "lineno": str(best_line),
                        "snippet": snippet,
                        "path_bonus": ps,
                        "content_score": 0.0
                    }
    except Exception:
        pass

    # 2. Content-based search with ripgrep
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

            # Declaration boost
            decl_keywords = ("class ", "function ", "interface ", "trait ", "const ", "export ", "<template", "<script")
            if any(dk in snippet for dk in decl_keywords):
                score += 3.0

            if any(filepath.endswith(ext) for ext in (".php", ".ts", ".vue", ".js", ".py")):
                score += 1.0
            scored_blocks.append((score, filepath, lineno, snippet))

        scored_blocks.sort(key=lambda x: x[0], reverse=True)

        for score, filepath, lineno, snippet in scored_blocks:
            if filepath and snippet:
                key = (filepath, lineno)
                p_bonus = compute_file_path_score(filepath, terms, query)
                if key in candidates:
                    candidates[key]["content_score"] = max(candidates[key]["content_score"], score)
                    candidates[key]["snippet"] = snippet
                    candidates[key]["lineno"] = lineno
                else:
                    candidates[key] = {
                        "filepath": filepath,
                        "lineno": lineno,
                        "snippet": snippet,
                        "path_bonus": p_bonus,
                        "content_score": score
                    }
    except Exception:
        pass

    cand_list = list(candidates.values())
    if not cand_list:
        return []

    # Tier 1: Fast-Path for symbol / component lookups (< 15ms)
    if is_symbol_intent:
        top_path_bonus = max((c.get("path_bonus", 0.0) for c in cand_list), default=0.0)
        top_content_score = max((c.get("content_score", 0.0) for c in cand_list), default=0.0)

        # If strong symbol or path matches exist, rank directly and bypass ONNX
        if top_path_bonus >= 8.0 or top_content_score >= 8.0:
            fast_ranked = []
            for c in cand_list:
                total = c.get("path_bonus", 0.0) * 1.5 + c.get("content_score", 0.0)
                content_lower = (c["filepath"] + " " + c["snippet"]).lower()
                matched_count = sum(1 for t in terms if t in content_lower)
                total += matched_count * 2.0
                if any(c["filepath"].endswith(ext) for ext in (".vue", ".php", ".ts", ".js", ".py")):
                    total += 1.0
                fast_ranked.append({
                    "score": round(total, 3),
                    "filepath": c["filepath"],
                    "lineno": c["lineno"],
                    "snippet": c["snippet"]
                })
            fast_ranked.sort(key=lambda x: x["score"], reverse=True)
            return fast_ranked[:top_k]

    # Tier 2: Neural Semantic Search (Bounded to top 12 candidates to guarantee < 250ms)
    def initial_ranking_key(c):
        return c.get("path_bonus", 0.0) + c.get("content_score", 0.0)

    cand_list.sort(key=initial_ranking_key, reverse=True)
    bounded_candidates = cand_list[:12]

    pairs = [[query, f"File: {c['filepath']}\n{c['snippet']}"] for c in bounded_candidates]
    logits = run_cross_encoder_inference(pairs, max_length=256)

    ranked = []
    for score, cand in zip(logits, bounded_candidates):
        total_score = score + (cand["path_bonus"] * 0.8)
        content_lower = (cand["filepath"] + " " + cand["snippet"]).lower()
        matched_count = sum(1 for t in terms if t in content_lower)
        total_score += matched_count * 2.0
        if any(cand["filepath"].endswith(ext) for ext in (".php", ".ts", ".vue", ".js", ".py")):
            total_score += 1.0
        ranked.append({
            "score": round(total_score, 3),
            "filepath": cand["filepath"],
            "lineno": cand["lineno"],
            "snippet": cand["snippet"]
        })

    del pairs, cand_list, bounded_candidates, logits
    import gc
    gc.collect()

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]

def handle_prune(filepath, query, cwd, top_k=2):
    try:
        from localgrep.chunker import chunk_file, extract_declaration_block
    except ImportError:
        try:
            from .chunker import chunk_file, extract_declaration_block
        except ImportError:
            from chunker import chunk_file, extract_declaration_block

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

    clean_query = query.strip()
    is_symbol_mode = False
    if clean_query.startswith("--symbol ") or clean_query.startswith("-s "):
        clean_query = clean_query.split(None, 1)[1].strip().strip('"\'')
        is_symbol_mode = True
    elif re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', clean_query):
        is_symbol_mode = True

    # 1. Exact Identifier Short-Circuit Pass on AST Chunks
    decl_regex = re.compile(
        rf'(?:'
        rf'\b(?:function|def|class|interface|trait|enum|const|let|var|val|fn|type)\s+(?:\$)?{re.escape(clean_query)}\b'
        rf'|\b(?:public|protected|private|static)\s+(?:(?:readonly|static)\s+)*(?:[\w\?\|\[\]]+\s+)?\${re.escape(clean_query)}\b'
        rf'|\b{re.escape(clean_query)}\s*[:=]\s*(?:ref|reactive|computed|shallowRef|\()'
        rf')'
    )

    exact_matches = []
    for c in chunks:
        c_name = c.get("name", "")
        matched = False
        score = 0.0

        if c_name and c_name == clean_query:
            matched = True
            score = 2000.0 - min(500.0, (c["end"] - c["start"]) * 0.5)
        elif c_name and is_symbol_mode and c_name.lower() == clean_query.lower():
            matched = True
            score = 1800.0 - min(500.0, (c["end"] - c["start"]) * 0.5)
        elif is_symbol_mode and decl_regex.search(c["text"]):
            matched = True
            score = 1000.0 - min(500.0, (c["end"] - c["start"]) * 1.0)

        if matched:
            exact_matches.append({
                "score": round(score, 2),
                "filepath": filepath,
                "name": c_name or clean_query,
                "start": c["start"],
                "end": c["end"],
                "snippet": c["text"].strip(),
                "kind": c.get("kind", "ast_block")
            })

    if exact_matches:
        exact_matches.sort(key=lambda x: x["score"], reverse=True)
        return {"status": "ok", "results": exact_matches[:top_k]}

    # 2. Raw Text Line Scan Fallback for Symbol Declarations
    if is_symbol_mode:
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("//", "#", "/*", "*")):
                continue
            if decl_regex.search(line):
                start_l, end_l, block_text = extract_declaration_block(lines, idx)
                exact_matches.append({
                    "score": 1000.0,
                    "filepath": filepath,
                    "name": clean_query,
                    "start": start_l,
                    "end": end_l,
                    "snippet": block_text,
                    "kind": "ast_declaration"
                })
                break

    if exact_matches:
        return {"status": "ok", "results": exact_matches[:top_k]}

    # 3. Symbol Usages Fast-Path (Skip Heavy Cross-Encoder for Identifiers)
    if is_symbol_mode:
        usage_matches = []
        sym_pattern = re.compile(rf'\b{re.escape(clean_query)}\b')
        for c in chunks:
            count = len(sym_pattern.findall(c["text"]))
            if count > 0:
                usage_matches.append({
                    "score": 100.0 + count,
                    "filepath": filepath,
                    "name": c.get("name", clean_query),
                    "start": c["start"],
                    "end": c["end"],
                    "snippet": c["text"].strip(),
                    "kind": c.get("kind", "usage")
                })
        usage_matches.sort(key=lambda x: x["score"], reverse=True)
        return {"status": "ok", "results": usage_matches[:top_k]}

    # 2. Semantic Cross-Encoder Ranking with AST Boost
    pairs = [[clean_query, c["text"]] for c in chunks]
    logits = run_cross_encoder_inference(pairs, max_length=512)

    ranked = []
    for score, c in zip(logits, chunks):
        c_name = c.get("name", "")
        adjusted_score = float(score)

        if c_name:
            if clean_query.lower() in c_name.lower():
                adjusted_score += 50.0
            elif c_name.lower() in clean_query.lower():
                adjusted_score += 25.0

        if re.search(r'\b(return|throw)\b[^;]*;', c["text"]):
            adjusted_score += 5.0

        ranked.append({
            "score": round(adjusted_score, 2),
            "filepath": filepath,
            "name": c_name,
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
        elif action == "slice":
            filepath = req.get("file", "")
            symbol = req.get("symbol", "")
            try:
                from localgrep.slice import extract_file_slice
            except ImportError:
                try:
                    from .slice import extract_file_slice
                except ImportError:
                    from slice import extract_file_slice
            resp = extract_file_slice(filepath, symbol, cwd)
        elif action == "lint_fast":
            filepath = req.get("file", "")
            try:
                from localgrep.lint_fast import lint_fast_file
            except ImportError:
                try:
                    from .lint_fast import lint_fast_file
                except ImportError:
                    from lint_fast import lint_fast_file
            resp = lint_fast_file(filepath, cwd)
        elif action == "test_map":
            filepath = req.get("file", "")
            try:
                from localgrep.test_map import map_test_for_file
            except ImportError:
                try:
                    from .test_map import map_test_for_file
                except ImportError:
                    from test_map import map_test_for_file
            resp = map_test_for_file(filepath, cwd)
        elif action == "sample":
            target = req.get("target", "")
            try:
                from localgrep.sample import get_sample_record
            except ImportError:
                try:
                    from .sample import get_sample_record
                except ImportError:
                    from sample import get_sample_record
            resp = get_sample_record(target, cwd)
        elif action == "impact":
            target = req.get("target", "")
            try:
                from localgrep.impact import calculate_impact
            except ImportError:
                try:
                    from .impact import calculate_impact
                except ImportError:
                    from impact import calculate_impact
            resp = calculate_impact(target, cwd)
        elif action == "error_decode":
            raw_input = req.get("input", "")
            try:
                from localgrep.error_decode import decode_error
            except ImportError:
                try:
                    from .error_decode import decode_error
                except ImportError:
                    from error_decode import decode_error
            resp = decode_error(raw_input, cwd)
        elif action == "env_audit":
            try:
                from localgrep.env_audit import audit_environment
            except ImportError:
                try:
                    from .env_audit import audit_environment
                except ImportError:
                    from env_audit import audit_environment
            resp = audit_environment(cwd)
        elif action == "state_map":
            component = req.get("component", "")
            try:
                from localgrep.state_map import generate_state_map
            except ImportError:
                try:
                    from .state_map import generate_state_map
                except ImportError:
                    from state_map import generate_state_map
            resp = generate_state_map(component, cwd)
        elif action == "api_shape":
            target = req.get("target", "")
            try:
                from localgrep.api_shape import synthesize_api_shape
            except ImportError:
                try:
                    from .api_shape import synthesize_api_shape
                except ImportError:
                    from api_shape import synthesize_api_shape
            resp = synthesize_api_shape(target, cwd)
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
        elif action == "contract":
            target = req.get("target", "")
            full = bool(req.get("full", False))
            try:
                from localgrep.contract import extract_contract
            except ImportError:
                try:
                    from .contract import extract_contract
                except ImportError:
                    from contract import extract_contract
            resp = extract_contract(target, cwd, full=full)
        elif action == "route":
            query = req.get("query", "")
            try:
                from localgrep.router import lookup_route
            except ImportError:
                try:
                    from .router import lookup_route
                except ImportError:
                    from router import lookup_route
            resp = lookup_route(query, cwd, top_k=top_k)
        elif action == "topo":
            try:
                from localgrep.topo import get_project_topology
            except ImportError:
                try:
                    from .topo import get_project_topology
                except ImportError:
                    from topo import get_project_topology
            resp = get_project_topology(cwd)
        elif action == "callers":
            symbol = req.get("symbol", "")
            include_imports = req.get("include_imports", False)
            try:
                from localgrep.callers import find_callers
            except ImportError:
                try:
                    from .callers import find_callers
                except ImportError:
                    from callers import find_callers
            resp = find_callers(symbol, cwd, include_imports=include_imports, top_k=top_k)
        elif action == "event_map":
            query = req.get("query", "")
            try:
                from localgrep.events import get_event_map
            except ImportError:
                try:
                    from .events import get_event_map
                except ImportError:
                    from events import get_event_map
            resp = get_event_map(query, cwd)
        elif action == "schema":
            model = req.get("model", "")
            try:
                from localgrep.schema import get_model_schema
            except ImportError:
                try:
                    from .schema import get_model_schema
                except ImportError:
                    from schema import get_model_schema
            resp = get_model_schema(model, cwd)
        elif action == "verify_patch":
            file_path = req.get("file", "")
            target_content = req.get("target_content", "")
            try:
                from localgrep.verify_patch import verify_patch
            except ImportError:
                try:
                    from .verify_patch import verify_patch
                except ImportError:
                    from verify_patch import verify_patch
            resp = verify_patch(file_path, target_content, cwd=cwd)
        elif action == "patch":
            file_path = req.get("file", "")
            search_block = req.get("search", "")
            replace_block = req.get("replace", "")
            dry_run = req.get("dry_run", False)
            force = req.get("force", False)
            try:
                from localgrep.patch import apply_patch
            except ImportError:
                try:
                    from .patch import apply_patch
                except ImportError:
                    from patch import apply_patch
            resp = apply_patch(file_path, search_block, replace_block, cwd=cwd, dry_run=dry_run, force=force)
        elif action == "audit_diff":
            staged = req.get("staged", False)
            file_path = req.get("file", None)
            try:
                from localgrep.audit_diff import audit_diff
            except ImportError:
                try:
                    from .audit_diff import audit_diff
                except ImportError:
                    from audit_diff import audit_diff
            resp = audit_diff(cwd, staged_only=staged, file_path=file_path)
        elif action == "test_isolate":
            raw_output = req.get("output", "")
            cmd = req.get("cmd", [])
            try:
                from localgrep.test_isolate import parse_test_output, run_test_isolate
            except ImportError:
                try:
                    from .test_isolate import parse_test_output, run_test_isolate
                except ImportError:
                    from test_isolate import parse_test_output, run_test_isolate
            if raw_output:
                resp = parse_test_output(raw_output, cwd=cwd)
            elif cmd:
                resp = run_test_isolate(cmd, cwd=cwd)
            else:
                resp = {"status": "error", "message": "Neither output nor cmd provided for test_isolate"}
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
