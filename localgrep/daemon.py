#!/usr/bin/env python3
import sys
import os
import signal
import socket
import json
import subprocess
import re
import warnings

SOCKET_PATH = "/tmp/localgrep.sock"
PID_FILE = "/tmp/localgrep.pid"
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_ONNX_PATH = os.path.expanduser("~/.local/localgrep/model.onnx")

STOP_WORDS = {
    "where", "what", "which", "when", "how", "who", "whom", "this", "that",
    "there", "here", "with", "from", "have", "been", "does", "checked",
    "check", "find", "show", "code", "file", "logic", "implementation",
    "look", "give", "tell", "name", "component", "active", "page"
}

tokenizer = None
onnx_session = None
torch_model = None

def init_model():
    global tokenizer, onnx_session, torch_model
    from transformers import AutoTokenizer, logging
    logging.set_verbosity_error()
    warnings.filterwarnings("ignore")

    token = os.environ.get("HF_TOKEN")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, token=token)

    # Check if ONNX model is available for ultra-fast (sub-millisecond) inference
    pkg_onnx = os.path.join(os.path.dirname(__file__), "model.onnx")
    onnx_file = pkg_onnx if os.path.exists(pkg_onnx) else (DEFAULT_ONNX_PATH if os.path.exists(DEFAULT_ONNX_PATH) else None)

    if onnx_file:
        try:
            import onnxruntime as ort
            sess_opts = ort.SessionOptions()
            sess_opts.intra_op_num_threads = 4
            onnx_session = ort.InferenceSession(onnx_file, sess_opts, providers=['CPUExecutionProvider'])
            # Warmup
            dummy = tokenizer([["warmup", "test"]], padding=True, truncation=True, return_tensors='np')
            _ = onnx_session.run(["logits"], {"input_ids": dummy["input_ids"], "attention_mask": dummy["attention_mask"]})
            return
        except Exception:
            onnx_session = None

    # Fallback to PyTorch
    import torch
    from transformers import AutoModelForSequenceClassification
    torch_model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, token=token)
    torch_model.eval()
    dummy = tokenizer([["warmup", "test"]], padding=True, truncation=True, return_tensors='pt')
    with torch.no_grad():
        _ = torch_model(**dummy)

def run_cross_encoder_inference(pairs, max_length=384):
    if onnx_session is not None:
        inputs = tokenizer(pairs, padding=True, truncation=True, return_tensors='np', max_length=max_length)
        raw = onnx_session.run(["logits"], {"input_ids": inputs["input_ids"], "attention_mask": inputs["attention_mask"]})[0]
        return raw.flatten().tolist()

    import torch
    inputs = tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=max_length)
    with torch.no_grad():
        logits = torch_model(**inputs).logits.view(-1).float().tolist()
    return logits

def extract_search_terms(query):
    normalized = re.sub(r'([a-z])([A-Z])', r'\1 \2', query)
    normalized = normalized.replace('-', ' ').replace('_', ' ')
    tokens = re.findall(r'[a-zA-Z0-9]+', normalized.lower())
    meaningful = [t for t in tokens if len(t) > 2 and t not in STOP_WORDS]
    return meaningful if meaningful else [t for t in tokens if len(t) > 1]

def get_candidates(query, cwd, top_k=3, max_candidates=45, search_dirs=None):
    terms = extract_search_terms(query)
    if not terms:
        terms = ["account", "component"]

    candidates = {}

    globs = [
        "--glob", "!vendor/**",
        "--glob", "!node_modules/**",
        "--glob", "!.git/**",
        "--glob", "!storage/**",
        "--glob", "!public/**",
        "--glob", "!dist/**",
        "--glob", "!graphify-out/**",
        "--glob", "!resources/views/vendor/**",
        "--glob", "!*.lock"
    ]
    if not search_dirs or "tests" not in search_dirs:
        globs += ["--glob", "!tests/**"]

    if not search_dirs:
        target_candidates = ["resources", "app", "routes", "config", "src", "packages", "lib"]
        target_dirs = [d for d in target_candidates if os.path.isdir(os.path.join(cwd, d))]
        search_dirs = target_dirs if target_dirs else ["."]

    # 1. Path-based search
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
                ext_boost = 1 if p.endswith(('.vue', '.ts', '.php', '.js', '.py', '.rs', '.go')) else 0
                return base_matches + path_matches + ext_boost

            sorted_files = sorted(file_lines, key=path_score, reverse=True)
            for filepath in sorted_files[:15]:
                full_path = os.path.join(cwd, filepath)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = [f.readline() for _ in range(16)]
                    snippet = "".join(lines).strip()
                    if snippet:
                        score_val = path_score(filepath)
                        candidates[(filepath, "1")] = {
                            "filepath": filepath,
                            "lineno": "1",
                            "snippet": snippet,
                            "is_path_match": True,
                            "path_bonus": 2.5 if score_val >= 3 else 1.0
                        }
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Content-based search with ripgrep
    try:
        regex_pattern = "|".join(terms[:4])
        cmd = [
            "rg", "-i", "-n", "-C", "3", "--max-count", "3"
        ] + globs + ["-e", regex_pattern] + search_dirs

        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        blocks = res.stdout.strip().split("\n--\n")

        for block in blocks[:80]:
            lines = block.strip().split("\n")
            if not lines:
                continue
            first_line = lines[0]
            parts = first_line.split(":", 2) if ":" in first_line else first_line.split("-", 2)
            filepath = parts[0].strip() if len(parts) > 0 else ""
            lineno = parts[1].strip() if len(parts) > 1 else "1"
            snippet = "\n".join(lines[:7])
            if filepath and snippet and (filepath, lineno) not in candidates:
                candidates[(filepath, lineno)] = {
                    "filepath": filepath,
                    "lineno": lineno,
                    "snippet": snippet,
                    "is_path_match": False,
                    "path_bonus": 0.0
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
        content_lower = cand["snippet"].lower()
        if all(t in content_lower for t in terms):
            total_score += 1.0
        ranked.append({
            "score": total_score,
            "filepath": cand["filepath"],
            "lineno": cand["lineno"],
            "snippet": cand["snippet"]
        })

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

    # AST-aware or sliding-window chunking
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

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"status": "ok", "results": ranked[:top_k]}

def handle_filter(text, query, top_k=5):
    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not raw_lines:
        return {"status": "ok", "results": []}

    terms = extract_search_terms(query)
    candidates = raw_lines
    if len(raw_lines) > 100 and terms:
        filtered = [l for l in raw_lines if any(t in l.lower() for t in terms)]
        if len(filtered) >= top_k:
            candidates = filtered[:80]
        else:
            candidates = raw_lines[:80]
    elif len(raw_lines) > 80:
        candidates = raw_lines[:80]

    pairs = [[query, line] for line in candidates]
    logits = run_cross_encoder_inference(pairs, max_length=256)

    ranked = []
    for score, line in zip(logits, candidates):
        ranked.append({
            "score": score,
            "line": line
        })

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

        # Name match bonus
        if any(t in name_lower for t in terms):
            boost += 3.0

        # Keyword overlap bonus
        matching_terms = sum(1 for t in terms if t in desc_lower)
        boost += matching_terms * 0.8

        ranked.append({
            "score": score + boost,
            "name": s["name"],
            "path": s["path"],
            "desc": s["desc"]
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"status": "ok", "results": ranked[:top_k]}

def handle_client(conn):
    try:
        chunks = []
        while True:
            chunk = conn.recv(16384)
            if not chunk:
                break
            chunks.append(chunk)
        if not chunks:
            return

        raw_req = b"".join(chunks).decode('utf-8')
        req = json.loads(raw_req)
        action = req.get("action", "search")
        cwd = req.get("cwd", os.getcwd())
        top_k = req.get("top_k", 3)

        if action == "prune":
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
            res = get_candidates(query, cwd, top_k=top_k)
            resp = {"status": "ok", "results": res}

        conn.sendall(json.dumps(resp).encode('utf-8'))
    except Exception as e:
        err = json.dumps({"status": "error", "message": str(e)})
        conn.sendall(err.encode('utf-8'))
    finally:
        conn.close()

def cleanup(*args):
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
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

    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    init_model()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(10)
    os.chmod(SOCKET_PATH, 0o777)

    while True:
        conn, _ = server.accept()
        handle_client(conn)

if __name__ == "__main__":
    start_daemon_server()
