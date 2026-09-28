#!/usr/bin/env python3
import sys
import os
import socket
import json
import time
import subprocess

SOCKET_PATH = "/tmp/localgrep.sock"
PID_FILE = "/tmp/localgrep.pid"

def is_daemon_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False

def get_python_exe():
    venv_python = os.path.expanduser("~/.local/localgrep/venv/bin/python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable or "python3"

def start_daemon():
    if not is_daemon_running():
        env = os.environ.copy()
        python_bin = get_python_exe()
        daemon_file = os.path.join(os.path.dirname(__file__), "daemon.py")
        if os.path.exists(daemon_file):
            cmd = [python_bin, daemon_file]
        else:
            cmd = [python_bin, "-m", "localgrep.daemon"]

        subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    for _ in range(80):
        if os.path.exists(SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(SOCKET_PATH)
                s.close()
                return True
            except socket.error:
                pass
        time.sleep(0.1)
    return False

def send_request(payload):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCKET_PATH)
    except socket.error:
        if not start_daemon():
            return None
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(SOCKET_PATH)
        except socket.error:
            return None

    try:
        data = json.dumps(payload)
        s.sendall(data.encode('utf-8'))
        s.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            chunk = s.recv(16384)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks).decode('utf-8')
        return json.loads(raw)
    except Exception:
        return None
    finally:
        s.close()

def print_search_results(query, results):
    if not results:
        print(f"No code snippets matched keywords from: '{query}'")
        return

    print(f"\n=== Top Relevant Results for: '{query}' ===")
    for item in results:
        score = item["score"]
        filepath = item["filepath"]
        lineno = item["lineno"]
        snippet = item["snippet"]
        print(f"\n[Score: {score:+.2f}] {filepath}:{lineno}")
        print("--------------------------------------------------")
        print(snippet)
        print("--------------------------------------------------")

def print_prune_results(filepath, query, results):
    if not results:
        print(f"No relevant blocks found in {filepath} for: '{query}'")
        return

    print(f"\n=== Top Pruned Blocks in {filepath} for: '{query}' ===")
    for item in results:
        score = item["score"]
        start = item["start"]
        end = item["end"]
        snippet = item["snippet"]
        print(f"\n[Score: {score:+.2f}] Lines {start}-{end}")
        print("--------------------------------------------------")
        print(snippet)
        print("--------------------------------------------------")

def print_filter_results(query, results):
    if not results:
        print(f"No lines matched for: '{query}'")
        return

    print(f"\n=== Top Filtered Results for: '{query}' ===")
    for item in results:
        score = item["score"]
        line = item["line"]
        print(f"[{score:+.2f}] {line}")

def main():
    if len(sys.argv) < 2:
        print("LocalGrep (lg): Fast index-free local semantic search & context pruner for AI coding agents.\n")
        print("Usage:")
        print("  lg '<query>'                       # Semantic codebase search")
        print("  lg prune <file> '<query>'          # Extract targeted function / code block from file")
        print("  <cmd> | lg '<query>'               # Filter long CLI outputs via pipe")
        print("  lg test '<query>'                  # Search test suite")
        print("  lg error '<error/stacktrace>'      # Trace exception/error to source file")
        print("  lg mcp                             # Launch Model Context Protocol (MCP) server")
        sys.exit(1)

    cwd = os.getcwd()
    cmd = sys.argv[1]
    has_pipe = not sys.stdin.isatty()

    if cmd == "mcp":
        venv_python = os.path.expanduser("~/.local/localgrep/venv/bin/python")
        if os.path.exists(venv_python) and sys.executable != venv_python:
            os.execv(venv_python, [venv_python] + sys.argv)
        try:
            from localgrep.mcp_server import main as run_mcp
        except ImportError:
            try:
                from .mcp_server import main as run_mcp
            except ImportError:
                from mcp_server import main as run_mcp
        run_mcp()
        return

    elif cmd == "prune":
        if len(sys.argv) < 4:
            print("Usage: lg prune <file> '<query>'")
            sys.exit(1)
        filepath = sys.argv[2]
        query = sys.argv[3]
        payload = {"action": "prune", "file": filepath, "query": query, "cwd": cwd, "top_k": 2}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_prune_results(filepath, query, resp.get("results", []))
        else:
            print(f"Error pruning {filepath}: {resp.get('message') if resp else 'Daemon error'}")

    elif has_pipe or cmd == "filter":
        query = cmd if cmd != "filter" else (sys.argv[2] if len(sys.argv) > 2 else "")
        text = sys.stdin.read()
        payload = {"action": "filter", "text": text, "query": query, "top_k": 5}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_filter_results(query, resp.get("results", []))
        else:
            print(f"Filter error: {resp.get('message') if resp else 'Daemon error'}")

    elif cmd == "test":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        payload = {"action": "test", "query": query, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_search_results(query, resp.get("results", []))
        else:
            print(f"Test search error: {resp.get('message') if resp else 'Daemon error'}")

    elif cmd == "error":
        err_msg = sys.argv[2] if len(sys.argv) > 2 else ""
        payload = {"action": "error", "error": err_msg, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_search_results(err_msg[:40], resp.get("results", []))
        else:
            print(f"Error search error: {resp.get('message') if resp else 'Daemon error'}")

    else:
        query = cmd
        payload = {"action": "search", "query": query, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_search_results(query, resp.get("results", []))
        else:
            print(f"No code snippets matched keywords from: '{query}'")

if __name__ == "__main__":
    main()
