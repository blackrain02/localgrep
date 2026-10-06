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

    try:
        resp = send_request({"action": "stop"})
        if resp and resp.get("status") == "ok":
            print("LocalGrep daemon stopped gracefully.")
            return True
    except Exception:
        pass

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

def get_daemon_status(is_json: bool = False):
    running = is_daemon_running()
    if not running:
        if is_json:
            print(json.dumps({"status": "stopped", "running": False}, indent=2))
        else:
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
    uptime = 0
    if resp and resp.get("status") == "ok":
        rss_mb = resp.get("rss_mb", "Unknown")
        backend = resp.get("backend", "Unknown")
        uptime = resp.get("uptime_seconds", 0)

    if is_json:
        data = {
            "status": "ok",
            "running": True,
            "pid": int(pid) if pid.isdigit() else pid,
            "socket": SOCKET_PATH,
            "backend": backend,
            "rss_mb": rss_mb,
            "uptime_seconds": uptime
        }
        print(json.dumps(data, indent=2))
    else:
        print("LocalGrep daemon: Running")
        print(f"  PID:        {pid}")
        print(f"  Socket:     {SOCKET_PATH}")
        print(f"  Backend:    {backend}")
        print(f"  Memory RSS: {rss_mb} MB")
        print(f"  Uptime:     {uptime}s")

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
    is_json = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--json"]

    if not args or args[0] in ("-h", "--help"):
        print("LocalGrep (lg): Fast index-free local semantic search & context pruner for AI coding agents.\n")
        print("Usage:")
        print("  lg '<query>' [--json]                      # Semantic codebase search")
        print("  lg contract <file|component> [--full] [--json] # Extract Vue props/emits/hooks, PHP class or TS signatures")
        print("  lg route '<uri|name|controller>' [--json]  # Map route directly to Controller action & file line")
        print("  lg topo [--json]                           # Dense executive project topology card for agent start")
        print("  lg callers <Method|Class> [--json]         # Find actual call sites and references")
        print("  lg event-map [<filter>] [--json]           # Laravel Event -> Listener -> Queue -> Job map")
        print("  lg schema <Model> [--json]                 # Extract model table schema, columns, casts & relations")
        print("  lg verify-patch <file> [target] [--json]   # Pre-validate edit block, resolve StartLine/EndLine")
        print("  lg patch <file> -s <old> -r <new> [--json] # Atomic fuzzy edit with auto-indent & syntax guard")
        print("  lg audit-diff [--staged] [--file <f>]      # Audit git diff for debug code, markers, secrets & lints")
        print("  lg test-isolate <cmd...> [--json]          # Run test command & distill failure noise to exact app frame")
        print("  lg prune <file> '<query>' [--json]         # Extract targeted function / code block from file")
        print("  lg slice <file> '<symbol>' [--json]        # Skeletonized file context around target method (85%+ token cut)")
        print("  lg lint-fast <file> [--json]               # Sub-20ms pre-flight linter (syntax, Vue tags, imports)")
        print("  lg test-map <file> [--run] [--json]        # Targeted Pest/PHPUnit test selector & isolated runner")
        print("  lg sample <Model|table> [--json]           # Peek 1 realistic runtime record from database")
        print("  lg impact <symbol|file> [--json]           # Blast radius engine across PHP & Vue/TS")
        print("  lg error-decode [log|stdin] [--json]       # Distill 300-line stack trace to innermost app frame & SQL")
        print("  lg env-audit [--json]                      # Reconcile .env variables against config & database")
        print("  lg state-map <component.vue> [--json]      # Frontend reactive dependency DAG (prop->computed->watch->emit)")
        print("  lg api-shape <route|controller@method>     # Full-stack contract synthesis (FormRequest + Resource + Inertia)")
        print("  <cmd> | lg '<query>'                       # Filter long CLI outputs via pipe")
        print("  lg filter '<query>'                        # Filter stdin manually")
        print("  lg test '<query>' [--json]                 # Search test suite")
        print("  lg error '<error/stacktrace>' [--json]     # Trace exception/error to source file")
        print("  lg skill '<task/intent>' [--json]          # Semantic skill recommender for Claude / Antigravity")
        print("  lg status [--json]                         # Show daemon status, memory RSS, and backend")
        print("  lg stop                                    # Stop background daemon process")
        print("  lg mcp                                     # Launch Model Context Protocol (MCP) server")
        sys.exit(0 if args else 1)

    cwd = os.getcwd()
    cmd = args[0]

    # Explicit subcommands first
    if cmd == "stop":
        stop_daemon()
        return

    if cmd == "status":
        get_daemon_status(is_json=is_json)
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
        prune_args = [a for a in args[1:] if a not in ("--symbol", "-s")]
        is_symbol = "--symbol" in args or "-s" in args
        if len(prune_args) < 2:
            print("Usage: lg prune <file> '<query>' [--symbol] [--json]")
            sys.exit(1)
        filepath = prune_args[0]
        query = prune_args[1]
        if is_symbol:
            query = f"--symbol {query}"
        payload = {"action": "prune", "file": filepath, "query": query, "cwd": cwd, "top_k": 2}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print_prune_results(filepath, query, resp.get("results", []))
        else:
            print(f"Error pruning {filepath}: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "slice":
        if len(args) < 3:
            print("Usage: lg slice <file> '<symbol>' [--json]")
            sys.exit(1)
        filepath = args[1]
        symbol = args[2]
        payload = {"action": "slice", "file": filepath, "symbol": symbol, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            header = f"\n=== Skeletonized Slice: {resp.get('filepath')} [{resp.get('symbol')}] (Saved {resp.get('saving_pct')}) ==="
            print(header)
            print("-" * 65)
            print(resp.get("skeleton", ""))
            print("-" * 65)
            print(f"Original: {resp.get('original_lines')} lines | Sliced: {resp.get('sliced_lines')} lines | Token reduction: {resp.get('saving_pct')}")
        else:
            print(f"Error slicing {filepath}: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd in ("lint-fast", "lint"):
        if len(args) < 2:
            print("Usage: lg lint-fast <file> [--json]")
            sys.exit(1)
        filepath = args[1]
        payload = {"action": "lint_fast", "file": filepath, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "clean":
            print(f"\n[OK] {resp.get('filepath')} is clean ({resp.get('elapsed_ms')}). Zero syntax issues.")
        elif resp and resp.get("issues"):
            print(f"\n=== Lint Issues: {resp.get('filepath')} [{resp.get('status').upper()}] ({resp.get('elapsed_ms')}) ===")
            print("-" * 65)
            for iss in resp.get("issues", []):
                sev = iss.get("severity", "error").upper()
                line = iss.get("line", 1)
                msg = iss.get("message", "")
                print(f"[{sev}] Line {line}: {msg}")
            print("-" * 65)
        else:
            print(f"Lint error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "test-map":
        test_args = [a for a in args[1:] if a != "--run"]
        if not test_args:
            print("Usage: lg test-map <file> [--run] [--json]")
            sys.exit(1)
        filepath = test_args[0]
        should_run = "--run" in args
        payload = {"action": "test_map", "file": filepath, "cwd": cwd}
        resp = send_request(payload)
        if is_json and not should_run:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if not resp or resp.get("status") != "ok":
            print(f"Error mapping tests for {filepath}: {resp.get('message') if resp else 'Daemon error'}")
            return

        matched = resp.get("matched_tests", [])
        if not matched:
            print(f"\nNo direct test cases found mapping to: {filepath}")
            return

        print(f"\n=== Mapped Tests for: {resp.get('filepath')} ===")
        for idx, t in enumerate(matched, start=1):
            reasons = ", ".join(t.get("reasons", []))
            print(f"{idx}. {t['test_file']} (score: {t['score']}) [{reasons}]")

        if should_run and matched:
            top_test = matched[0]["test_file"]
            print(f"\n--- Running Top Test: {top_test} ---")
            try:
                from localgrep.test_map import run_mapped_test
            except ImportError:
                from test_map import run_mapped_test
            run_res = run_mapped_test(top_test, cwd)
            if is_json:
                print(json.dumps(run_res, indent=2))
                return
            if run_res.get("passed"):
                print(f"[PASS] {top_test} passed successfully!")
            else:
                print(f"[FAIL] {top_test} failed:")
                print(run_res.get("distilled_output", ""))
        return

    if cmd == "sample":
        sample_args = [a for a in args[1:] if a != "--json"]
        if not sample_args:
            print("Usage: lg sample <Model | table> [--json]")
            sys.exit(1)
        target = sample_args[0]
        payload = {"action": "sample", "target": target, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        else:
            if resp and resp.get("status") == "ok":
                try:
                    from localgrep.sample import format_sample_text
                except ImportError:
                    from sample import format_sample_text
                print("\n" + format_sample_text(resp))
            else:
                msg = resp.get("message") if resp else "Daemon unreachable"
                print(f"Error: {msg}")
        return

    if cmd == "impact":
        impact_args = [a for a in args[1:] if a != "--json"]
        if not impact_args:
            print("Usage: lg impact <symbol | file> [--json]")
            sys.exit(1)
        target = impact_args[0]
        payload = {"action": "impact", "target": target, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        else:
            if resp and resp.get("status") == "ok":
                try:
                    from localgrep.impact import format_impact_text
                except ImportError:
                    from impact import format_impact_text
                print("\n" + format_impact_text(resp))
            else:
                msg = resp.get("message") if resp else "Daemon unreachable"
                print(f"Error: {msg}")
        return

    if cmd == "error-decode":
        raw_args = [a for a in args[1:] if a != "--json"]
        raw_input = ""
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read()
        elif raw_args:
            raw_input = " ".join(raw_args)
        else:
            # Default to storage/logs/laravel.log if exists
            default_log = os.path.join(cwd, "storage/logs/laravel.log")
            if os.path.isfile(default_log):
                raw_input = default_log
            else:
                print("Usage: lg error-decode [log_file | 'error_text' | stdin] [--json]")
                sys.exit(1)

        payload = {"action": "error_decode", "input": raw_input, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        else:
            if resp and resp.get("status") == "ok":
                try:
                    from localgrep.error_decode import format_error_decode_text
                except ImportError:
                    from error_decode import format_error_decode_text
                print("\n" + format_error_decode_text(resp))
            else:
                msg = resp.get("message") if resp else "Daemon unreachable"
                print(f"Error: {msg}")
        return

    if cmd == "env-audit":
        payload = {"action": "env_audit", "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        else:
            if resp and resp.get("status") == "ok":
                try:
                    from localgrep.env_audit import format_env_audit_text
                except ImportError:
                    from env_audit import format_env_audit_text
                print("\n" + format_env_audit_text(resp))
            else:
                msg = resp.get("message") if resp else "Daemon unreachable"
                print(f"Error: {msg}")
        return

    if cmd == "state-map":
        comp_args = [a for a in args[1:] if a != "--json"]
        if not comp_args:
            print("Usage: lg state-map <component.vue> [--json]")
            sys.exit(1)
        target = comp_args[0]
        payload = {"action": "state_map", "component": target, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        else:
            if resp and resp.get("status") == "ok":
                try:
                    from localgrep.state_map import format_state_map_text
                except ImportError:
                    from state_map import format_state_map_text
                print("\n" + format_state_map_text(resp))
            else:
                msg = resp.get("message") if resp else "Daemon unreachable"
                print(f"Error: {msg}")
        return

    if cmd == "api-shape":
        shape_args = [a for a in args[1:] if a != "--json"]
        if not shape_args:
            print("Usage: lg api-shape <route | controller@method> [--json]")
            sys.exit(1)
        target = shape_args[0]
        payload = {"action": "api_shape", "target": target, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        else:
            if resp and resp.get("status") == "ok":
                try:
                    from localgrep.api_shape import format_api_shape_text
                except ImportError:
                    from api_shape import format_api_shape_text
                print("\n" + format_api_shape_text(resp))
            else:
                msg = resp.get("message") if resp else "Daemon unreachable"
                print(f"Error: {msg}")
        return

    if cmd == "test":
        query = args[1] if len(args) > 1 else ""
        payload = {"action": "test", "query": query, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print_search_results(query, resp.get("results", []))
        else:
            print(f"Test search error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "error":
        err_msg = args[1] if len(args) > 1 else ""
        payload = {"action": "error", "error": err_msg, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print_search_results(err_msg[:40], resp.get("results", []))
        else:
            print(f"Error search error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "skill":
        query = args[1] if len(args) > 1 else ""
        payload = {"action": "skill", "query": query, "cwd": cwd, "top_k": 3}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print_skill_results(query, resp.get("results", []))
        else:
            print(f"Skill search error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "contract":
        contract_args = [a for a in args[1:] if a not in ("--full", "--hooks")]
        if not contract_args:
            print("Usage: lg contract <file_or_component> [--full] [--json]")
            sys.exit(1)
        target = contract_args[0]
        is_full = "--full" in args or "--hooks" in args
        payload = {"action": "contract", "target": target, "cwd": cwd, "full": is_full}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            header = f"\n=== {'Full' if is_full else 'Public'} Contract: {resp.get('filepath')} [{resp.get('language')}] ==="
            print(header)
            print("--------------------------------------------------")
            print(resp.get("contract", ""))
            print("--------------------------------------------------")
        else:
            print(f"Contract error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "route":
        query = args[1] if len(args) > 1 else ""
        payload = {"action": "route", "query": query, "cwd": cwd, "top_k": 5}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
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
                    if r.get("inertia_file"):
                        print(f"  Inertia Page: {r['inertia_file']}")
                    if r.get("blade_view"):
                        print(f"  Blade View:  {r['blade_view']}")
        else:
            print(f"Route lookup error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "topo":
        payload = {"action": "topo", "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print(resp.get("card", ""))
        else:
            print(f"Topology error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "callers":
        if len(args) < 2:
            print("Usage: lg callers <symbol> [--json] [--all]")
            sys.exit(1)
        symbol = args[1]
        include_imports = "--all" in sys.argv
        payload = {"action": "callers", "symbol": symbol, "include_imports": include_imports, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print(resp.get("card", ""))
        else:
            print(f"Callers error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "event-map":
        query = args[1] if len(args) > 1 else ""
        payload = {"action": "event_map", "query": query, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print(resp.get("card", ""))
        else:
            print(f"Event map error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "schema":
        if len(args) < 2:
            print("Usage: lg schema <Model> [--json]")
            sys.exit(1)
        model = args[1]
        payload = {"action": "schema", "model": model, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print(resp.get("card", ""))
        else:
            print(f"Schema error: {resp.get('message') if resp else 'Daemon error'}")
        return

    if cmd == "verify-patch":
        if len(args) < 2:
            print("Usage: lg verify-patch <file> [target_content] [--search <text>] [--json]")
            sys.exit(1)
        file_path = args[1]
        target_content = ""
        if len(args) > 2 and not args[2].startswith("--"):
            target_content = args[2]
        elif "--search" in sys.argv:
            s_idx = sys.argv.index("--search")
            if s_idx + 1 < len(sys.argv):
                target_content = sys.argv[s_idx + 1]
        elif is_piped_input():
            target_content = sys.stdin.read()

        if not target_content:
            print("Error: Target content to verify is required (pass as argument, via --search, or pipe via stdin).")
            sys.exit(1)

        payload = {"action": "verify_patch", "file": file_path, "target_content": target_content, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp:
            print(resp.get("card", ""))
        else:
            print("Verify patch error: Daemon error")
        return

    if cmd == "patch":
        if len(args) < 2:
            print("Usage: lg patch <file> --search <old> --replace <new> [--dry-run] [--force] [--json]")
            sys.exit(1)
        file_path = args[1]
        search_block = ""
        replace_block = ""
        dry_run = "--dry-run" in sys.argv
        force = "--force" in sys.argv

        if "--search" in sys.argv:
            s_idx = sys.argv.index("--search")
            if s_idx + 1 < len(sys.argv):
                search_block = sys.argv[s_idx + 1]
        elif "-s" in sys.argv:
            s_idx = sys.argv.index("-s")
            if s_idx + 1 < len(sys.argv):
                search_block = sys.argv[s_idx + 1]

        if "--replace" in sys.argv:
            r_idx = sys.argv.index("--replace")
            if r_idx + 1 < len(sys.argv):
                replace_block = sys.argv[r_idx + 1]
        elif "-r" in sys.argv:
            r_idx = sys.argv.index("-r")
            if r_idx + 1 < len(sys.argv):
                replace_block = sys.argv[r_idx + 1]

        if not search_block:
            print("Error: Search block is required via --search (or -s).")
            sys.exit(1)

        payload = {
            "action": "patch",
            "file": file_path,
            "search": search_block,
            "replace": replace_block,
            "dry_run": dry_run,
            "force": force,
            "cwd": cwd
        }
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp:
            if resp.get("status") == "ok":
                print(resp.get("card", "Patch applied successfully."))
            else:
                print(f"Error ({resp.get('status')}): {resp.get('message')}")
                if resp.get("error_detail"):
                    print(f"Details: {resp.get('error_detail')}")
        else:
            print("Patch error: Daemon error")
        return

    if cmd == "audit-diff":
        staged = "--staged" in sys.argv
        target_file = None
        if "--file" in sys.argv:
            f_idx = sys.argv.index("--file")
            if f_idx + 1 < len(sys.argv):
                target_file = sys.argv[f_idx + 1]
        elif len(args) > 1 and not args[1].startswith("--"):
            target_file = args[1]

        payload = {"action": "audit_diff", "staged": staged, "file": target_file, "cwd": cwd}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp:
            print(resp.get("card", ""))
        else:
            print("Audit diff error: Daemon error")
        return

    if cmd == "test-isolate":
        if is_piped_input():
            raw_output = sys.stdin.read()
            payload = {"action": "test_isolate", "output": raw_output, "cwd": cwd}
        elif len(args) > 1:
            test_cmd = [a for a in args[1:] if a != "--json"]
            payload = {"action": "test_isolate", "cmd": test_cmd, "cwd": cwd}
        else:
            print("Usage: lg test-isolate <test_command...> OR <command> | lg test-isolate [--json]")
            sys.exit(1)

        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp:
            print(resp.get("card", ""))
        else:
            print("Test isolate error: Daemon error")
        return

    if cmd == "filter":
        query = args[1] if len(args) > 1 else ""
        text = sys.stdin.read()
        payload = {"action": "filter", "text": text, "query": query, "top_k": 5}
        resp = send_request(payload)
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
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
        if is_json:
            print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
            return
        if resp and resp.get("status") == "ok":
            print_filter_results(query, resp.get("results", []))
        else:
            print(f"Filter error: {resp.get('message') if resp else 'Daemon error'}")
        return

    # Default fallback: Semantic codebase search (works cleanly in non-tty agent environments)
    query = cmd
    payload = {"action": "search", "query": query, "cwd": cwd, "top_k": 3}
    resp = send_request(payload)
    if is_json:
        print(json.dumps(resp or {"status": "error", "message": "Daemon error"}, indent=2))
        return
    if resp and resp.get("status") == "warning":
        print(f"\n[Notice] {resp.get('message')}")
    elif resp and resp.get("status") == "ok":
        print_search_results(query, resp.get("results", []))
    else:
        print(f"No code snippets matched keywords from: '{query}'")

if __name__ == "__main__":
    main()
