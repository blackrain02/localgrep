#!/usr/bin/env python3
import sys
import os
import socket
import json
import time
import subprocess
import signal

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

def is_daemon_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                return False
            pid = int(content)
        os.kill(pid, 0)
        if os.path.exists(SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(SOCKET_PATH)
                s.close()
                return True
            except socket.error:
                return False
        return False
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

        os.makedirs(RUNTIME_DIR, mode=0o700, exist_ok=True)
        log_fp = open(LOG_FILE, "a")

        subprocess.Popen(
            cmd,
            env=env,
            stdout=log_fp,
            stderr=log_fp,
            start_new_session=True
        )

    for _ in range(80):
        if os.path.exists(SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(SOCKET_PATH)
                s.close()
                return True
            except socket.error:
                pass
        time.sleep(0.1)

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                last_lines = "".join(lines[-6:]).strip()
                if last_lines:
                    sys.stderr.write(f"\n[LocalGrep Daemon Log]:\n{last_lines}\n")
        except Exception:
            pass
    return False

def stop_daemon():
    if not is_daemon_running():
        # Check if stale PID file exists
        if os.path.exists(PID_FILE):
            try:
                os.unlink(PID_FILE)
            except OSError:
                pass
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        print("LocalGrep daemon is not running.")
        return True

    # 1. Try graceful stop via socket
    try:
        resp = send_request({"action": "stop"})
        if resp and resp.get("status") == "ok":
            print("LocalGrep daemon stopped gracefully.")
            return True
    except Exception:
        pass

    # 2. Fallback to SIGTERM via PID
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        print(f"Stopping LocalGrep daemon (PID {pid})...")
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    except Exception as e:
        print(f"Error terminating PID: {e}")

    for p in (SOCKET_PATH, PID_FILE):
        if os.path.exists(p):
            try:
                os.unlink(p)
            except OSError:
                pass

    print("LocalGrep daemon stopped.")
    return True

def get_daemon_status():
    running = is_daemon_running()
    if not running:
        print("LocalGrep daemon: Stopped")
        return

    pid = "Unknown"
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = f.read().strip()
        except Exception:
            pass

    resp = send_request({"action": "status"})
    rss_mb = "Unknown"
    backend = "Unknown"
    uptime = "Unknown"
    if resp and resp.get("status") == "ok":
        rss_mb = resp.get("rss_mb", "Unknown")
        backend = resp.get("backend", "Unknown")
        uptime = f"{resp.get('uptime_seconds', '?')}s"

    print("LocalGrep daemon: Running")
    print(f"  PID:        {pid}")
    print(f"  Socket:     {SOCKET_PATH}")
    print(f"  Backend:    {backend}")
    print(f"  Memory RSS: {rss_mb} MB")
    print(f"  Uptime:     {uptime}")

def send_request(payload):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(30.0)
        s.connect(SOCKET_PATH)
    except socket.error:
        if not start_daemon():
            return None
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(30.0)
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

def is_piped_input() -> bool:
    if sys.stdin.isatty():
        return False
    try:
        import stat
        mode = os.fstat(sys.stdin.fileno()).st_mode
        return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)
    except Exception:
        return False

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

def print_skill_results(query, results):
    if not results:
        print(f"No matching skills found for: '{query}'")
        return

    print(f"\n=== Recommended Skills for: '{query}' ===")
    for item in results:
        score = item["score"]
        name = item["name"]
        path = item["path"]
        desc = item["desc"]
        print(f"\n[Score: {score:+.2f}] {name}")
        print(f"Path: {path}")
        if desc:
            print(f"Description: {desc[:200]}...")

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("LocalGrep (lg): Fast index-free local semantic search & context pruner for AI coding agents.\n")
        print("Usage:")
        print("  lg '<query>'                       # Semantic codebase search")
        print("  lg contract <file|component>       # Extract Vue props/emits, PHP class or TS signatures")
        print("  lg route '<uri|name|controller>'   # Map route directly to Controller action & file line")
        print("  lg topo                            # Dense executive project topology card for agent start")
        print("  lg prune <file> '<query>'          # Extract targeted function / code block from file")
        print("  <cmd> | lg '<query>'               # Filter long CLI outputs via pipe")
        print("  lg filter '<query>'                # Filter stdin manually")
        print("  lg test '<query>'                  # Search test suite")
        print("  lg error '<error/stacktrace>'      # Trace exception/error to source file")
        print("  lg skill '<task/intent>'           # Semantic skill recommender for Claude / Antigravity")
        print("  lg status                          # Show daemon status, memory RSS, and backend")
        print("  lg stop                            # Stop background daemon process")
        print("  lg mcp                             # Launch Model Context Protocol (MCP) server")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    cwd = os.getcwd()
    cmd = sys.argv[1]

    # Explicit subcommands first
    if cmd == "stop":
        stop_daemon()
        return

    if cmd == "status":
        get_daemon_status()
        return

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

    if cmd == "prune":
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
        return

    if cmd == "test":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        payload = {"action": "test", "query": query, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_search_results(query, resp.get("results", []))
        else:
            print(f"Test search error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "error":
        err_msg = sys.argv[2] if len(sys.argv) > 2 else ""
        payload = {"action": "error", "error": err_msg, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_search_results(err_msg[:40], resp.get("results", []))
        else:
            print(f"Error search error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "skill":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        payload = {"action": "skill", "query": query, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_skill_results(query, resp.get("results", []))
        else:
            print(f"Skill search error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "contract":
        if len(sys.argv) < 3:
            print("Usage: lg contract <file_or_component>")
            sys.exit(1)
        target = sys.argv[2]
        payload = {"action": "contract", "target": target, "cwd": cwd}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print(f"\n=== Public Contract: {resp.get('filepath')} [{resp.get('language')}] ===")
            print("--------------------------------------------------")
            print(resp.get("contract", ""))
            print("--------------------------------------------------")
        else:
            print(f"Contract error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "route":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        payload = {"action": "route", "query": query, "cwd": cwd, "top_k": 5}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            results = resp.get("results", [])
            if not results:
                print(f"No routes matched: '{query}'")
            else:
                print(f"\n=== Route Matches for: '{query}' ===")
                for r in results:
                    name_str = f" (name: {r['name']})" if r.get("name") else ""
                    print(f"\n[{r['method']}] {r['uri']}{name_str}")
                    print(f"  Route Def:   {r['route_file']}:{r['route_line']}")
                    if r.get("controller"):
                        action_str = f"@{r['action']}" if r.get("action") else ""
                        print(f"  Controller:  {r['controller']}{action_str}")
                    if r.get("target_file"):
                        print(f"  Target File: {r['target_file']}:{r.get('target_line', 1)}")
        else:
            print(f"Route lookup error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "topo":
        payload = {"action": "topo", "cwd": cwd}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print(resp.get("card", ""))
        else:
            print(f"Topology error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "filter":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        text = sys.stdin.read()
        payload = {"action": "filter", "text": text, "query": query, "top_k": 5}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_filter_results(query, resp.get("results", []))
        else:
            print(f"Filter error: {resp.get('message') if resp else 'Daemon error'}")
        return

    # Check if input is piped or redirected via stdin (e.g. `cmd | lg "query"`)
    if is_piped_input():
        query = cmd
        text = sys.stdin.read()
        payload = {"action": "filter", "text": text, "query": query, "top_k": 5}
        resp = send_request(payload)
        if resp and resp.get("status") == "ok":
            print_filter_results(query, resp.get("results", []))
        else:
            print(f"Filter error: {resp.get('message') if resp else 'Daemon error'}")
        return

    # Default fallback: Semantic codebase search (works cleanly in non-tty agent environments)
    query = cmd
    payload = {"action": "search", "query": query, "cwd": cwd, "top_k": 3}
    resp = send_request(payload)
    if resp and resp.get("status") == "warning":
        print(f"\n[Notice] {resp.get('message')}")
    elif resp and resp.get("status") == "ok":
        print_search_results(query, resp.get("results", []))
    else:
        print(f"No code snippets matched keywords from: '{query}'")

if __name__ == "__main__":
    main()
