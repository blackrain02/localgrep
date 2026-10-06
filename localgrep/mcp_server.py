import os
import sys
import json
from mcp.server.mcpserver import MCPServer
try:
    from localgrep.cli import send_request
except ImportError:
    try:
        from .cli import send_request
    except ImportError:
        try:
            from cli import send_request
        except ImportError:
            from client import send_request

app = MCPServer("localgrep")

@app.tool()
def localgrep_search(query: str, path: str = ".", top_k: int = 3) -> str:
    """
    Search the codebase semantically for concepts, components, models, routes, or functions.
    Returns ranked code snippets with file paths and line numbers without indexing overhead.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "search", "query": query, "cwd": cwd, "top_k": top_k}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"No code snippets matched keywords from: '{query}'"

    results = resp.get("results", [])
    if not results:
        return f"No code snippets matched keywords from: '{query}'"

    out = [f"=== Top Relevant Results for: '{query}' ==="]
    for item in results:
        score = item["score"]
        filepath = item["filepath"]
        lineno = item["lineno"]
        snippet = item["snippet"]
        out.append(f"\n[Score: {score:+.2f}] {filepath}:{lineno}\n{'-'*50}\n{snippet}\n{'-'*50}")
    return "\n".join(out)

@app.tool()
def localgrep_prune(file_path: str, query: str, top_k: int = 2) -> str:
    """
    Context Pruner: Extract the exact 20-30 line function, class, or code block from a large file
    matching your query. Slashes token consumption by 90% instead of reading the whole file.
    """
    cwd = os.getcwd()
    payload = {"action": "prune", "file": file_path, "query": query, "cwd": cwd, "top_k": top_k}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Error pruning {file_path}: {resp.get('message') if resp else 'Daemon error'}"

    results = resp.get("results", [])
    if not results:
        return f"No relevant blocks found in {file_path} for: '{query}'"

    out = [f"=== Top Pruned Blocks in {file_path} for: '{query}' ==="]
    for item in results:
        score = item["score"]
        start = item["start"]
        end = item["end"]
        snippet = item["snippet"]
        out.append(f"\n[Score: {score:+.2f}] Lines {start}-{end}\n{'-'*50}\n{snippet}\n{'-'*50}")
    return "\n".join(out)

@app.tool()
def localgrep_slice(file_path: str, symbol: str, path: str = ".") -> str:
    """
    Skeletonized File Context: Generates a compressed skeleton of a file around a target method.
    Preserves imports, class properties, and reactive state while collapsing all non-target methods
    into 1-line signature stubs. Expands the target method in full with exact 1-indexed line numbers.
    Achieves 85% to 92% token reduction for large file editing tasks.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "slice", "file": file_path, "symbol": symbol, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Error slicing {file_path}: {resp.get('message') if resp else 'Daemon error'}"

    return (
        f"=== Skeletonized Slice: {resp.get('filepath')} [{resp.get('symbol')}] (Saved {resp.get('saving_pct')}) ===\n"
        f"{'-'*65}\n"
        f"{resp.get('skeleton', '')}\n"
        f"{'-'*65}\n"
        f"Original: {resp.get('original_lines')} lines | Sliced: {resp.get('sliced_lines')} lines | Token reduction: {resp.get('saving_pct')}"
    )

@app.tool()
def localgrep_lint_fast(file_path: str, path: str = ".") -> str:
    """
    Sub-20ms Pre-Flight Linter: Instant local verification before marking tasks complete.
    Checks syntax errors (php -l / py_compile), unclosed Vue SFC template tags, and unimported classes.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "lint_fast", "file": file_path, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") == "error" and not resp.get("issues"):
        return f"Error running lint-fast on {file_path}: {resp.get('message') if resp else 'Daemon error'}"

    if resp.get("status") == "clean":
        return f"[OK] {resp.get('filepath')} is clean ({resp.get('elapsed_ms')}). Zero syntax issues."

    out = [f"=== Lint Issues: {resp.get('filepath')} [{resp.get('status').upper()}] ({resp.get('elapsed_ms')}) ==="]
    out.append("-" * 60)
    for iss in resp.get("issues", []):
        sev = iss.get("severity", "error").upper()
        line = iss.get("line", 1)
        msg = iss.get("message", "")
        out.append(f"[{sev}] Line {line}: {msg}")
    out.append("-" * 60)
    return "\n".join(out)

@app.tool()
def localgrep_test_map(file_path: str, path: str = ".") -> str:
    """
    Targeted Test Selector: Maps any source file to its corresponding Pest or PHPUnit test files
    across the root application or vendor/bina modules. Enables fast, targeted test verification.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "test_map", "file": file_path, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Error mapping tests for {file_path}: {resp.get('message') if resp else 'Daemon error'}"

    matched = resp.get("matched_tests", [])
    if not matched:
        return f"No direct test cases found mapping to: {file_path}"

    out = [f"=== Mapped Tests for: {resp.get('filepath')} ==="]
    for idx, t in enumerate(matched, start=1):
        reasons = ", ".join(t.get("reasons", []))
        out.append(f"{idx}. {t['test_file']} (score: {t['score']}) [{reasons}]")
    return "\n".join(out)

@app.tool()
def localgrep_sample(target: str, path: str = ".") -> str:
    """
    Zero-Query Database Sample Peek: Retrieves 1 realistic, sanitized runtime record directly from
    the local database (PostgreSQL/SQLite/MySQL) for an Eloquent model or table name, showing exact column types
    and data formats without executing manual Tinker code.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "sample", "target": target, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Error: LocalGrep daemon unreachable."
    if resp.get("status") != "ok":
        return f"Error: {resp.get('message', 'Failed to retrieve sample record.')}"
    try:
        from localgrep.sample import format_sample_text
    except ImportError:
        from sample import format_sample_text
    return format_sample_text(resp)

@app.tool()
def localgrep_impact(target: str, path: str = ".") -> str:
    """
    Blast Radius Engine: Computes downstream impact and blast radius before modifying or refactoring
    a symbol, method, class, or file. Maps direct callers across Vue/TS and PHP, associated routes,
    and affected Pest/PHPUnit test files with a risk assessment.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "impact", "target": target, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Error: LocalGrep daemon unreachable."
    if resp.get("status") != "ok":
        return f"Error: {resp.get('message', 'Failed to calculate blast radius.')}"
    try:
        from localgrep.impact import format_impact_text
    except ImportError:
        from impact import format_impact_text
    return format_impact_text(resp)

@app.tool()
def localgrep_error_decode(error_or_log: str = "storage/logs/laravel.log", path: str = ".") -> str:
    """
    Intelligent Stack-Trace Distiller: Distills complex Laravel framework error dumps and 300-line stack traces
    down to the innermost application frame, bound raw SQL queries, and the exact code context snippet.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "error_decode", "input": error_or_log, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Error: LocalGrep daemon unreachable."
    if resp.get("status") != "ok":
        return f"Error: {resp.get('message', 'Failed to decode error.')}"
    try:
        from localgrep.error_decode import format_error_decode_text
    except ImportError:
        from error_decode import format_error_decode_text
    return format_error_decode_text(resp)

@app.tool()
def localgrep_env_audit(path: str = ".") -> str:
    """
    Configuration & Environment Validator: Audits .env variables against config files and database tables,
    detecting missing credentials, disabled tables (e.g. Telescope/Pulse), and security misconfigurations.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "env_audit", "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Error: LocalGrep daemon unreachable."
    if resp.get("status") != "ok":
        return f"Error: {resp.get('message', 'Failed to run env audit.')}"
    try:
        from localgrep.env_audit import format_env_audit_text
    except ImportError:
        from env_audit import format_env_audit_text
    return format_env_audit_text(resp)

@app.tool()
def localgrep_state_map(component: str, path: str = ".") -> str:
    """
    Frontend Reactive Dependency Graph: Extracts an ASCII Directed Acyclic Graph (DAG) for Vue 3 SFCs,
    mapping the causal flows between props, refs, computeds, watchers, and emits.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "state_map", "component": component, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Error: LocalGrep daemon unreachable."
    if resp.get("status") != "ok":
        return f"Error: {resp.get('message', 'Failed to generate state map.')}"
    try:
        from localgrep.state_map import format_state_map_text
    except ImportError:
        from state_map import format_state_map_text
    return format_state_map_text(resp)

@app.tool()
def localgrep_api_shape(target: str, path: str = ".") -> str:
    """
    Full-Stack Contract Synthesizer: Synthesizes route definitions, controller methods, FormRequest
    validation rules, Eloquent resource schemas, and Inertia components into a single card in <25ms.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "api_shape", "target": target, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Error: LocalGrep daemon unreachable."
    if resp.get("status") != "ok":
        return f"Error: {resp.get('message', 'Failed to synthesize API shape.')}"
    try:
        from localgrep.api_shape import format_api_shape_text
    except ImportError:
        from api_shape import format_api_shape_text
    return format_api_shape_text(resp)

@app.tool()
def localgrep_test(query: str, path: str = ".", top_k: int = 3) -> str:
    """
    Find existing test cases (Pest, PHPUnit, Pytest, Jest) matching a feature or method.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "test", "query": query, "cwd": cwd, "top_k": top_k}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"No test cases found for: '{query}'"

    results = resp.get("results", [])
    if not results:
        return f"No test cases found for: '{query}'"

    out = [f"=== Top Test Cases for: '{query}' ==="]
    for item in results:
        score = item["score"]
        filepath = item["filepath"]
        lineno = item["lineno"]
        snippet = item["snippet"]
        out.append(f"\n[Score: {score:+.2f}] {filepath}:{lineno}\n{'-'*50}\n{snippet}\n{'-'*50}")
    return "\n".join(out)

@app.tool()
def localgrep_error(error_message: str, path: str = ".", top_k: int = 3) -> str:
    """
    Root Cause Localization: Match an exception stack trace or error log directly
    to probable throwing locations, validation rules, or controllers in the codebase.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "error", "error": error_message, "cwd": cwd, "top_k": top_k}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"No source locations matched for error: '{error_message}'"

    results = resp.get("results", [])
    if not results:
        return f"No source locations matched for error: '{error_message}'"

    out = [f"=== Probable Error Locations for: '{error_message[:50]}' ==="]
    for item in results:
        score = item["score"]
        filepath = item["filepath"]
        lineno = item["lineno"]
        snippet = item["snippet"]
        out.append(f"\n[Score: {score:+.2f}] {filepath}:{lineno}\n{'-'*50}\n{snippet}\n{'-'*50}")
    return "\n".join(out)

@app.tool()
def localgrep_skill(intent: str, path: str = ".", top_k: int = 3) -> str:
    """
    Semantic Skill Recommender: Match any coding task, user intent, or problem
    to the most relevant installed Claude / Antigravity skill, returning skill names, paths, and descriptions.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "skill", "query": intent, "cwd": cwd, "top_k": top_k}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"No skills matched for intent: '{intent}'"

    results = resp.get("results", [])
    if not results:
        return f"No skills matched for intent: '{intent}'"

    out = [f"=== Recommended Skills for: '{intent}' ==="]
    for item in results:
        score = item["score"]
        name = item["name"]
        skill_path = item["path"]
        desc = item.get("desc", "")
        out.append(f"\n[Score: {score:+.2f}] {name}\nPath: {skill_path}\nDescription: {desc[:250]}...")
    return "\n".join(out)

@app.tool()
def localgrep_contract(target: str, path: str = ".", full: bool = False) -> str:
    """
    Component & Class Contract Extractor: Extract Vue defineProps/defineEmits/slots/hooks,
    PHP public methods/constructor parameters/traits, or TypeScript interfaces in <10ms.
    Set full=True to extract lifecycle hooks (onMounted, etc.), watchers, reactive state, and internal properties.
    Eliminates reading huge 400+ line files when you only need to know props, lifecycle or method signatures.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "contract", "target": target, "cwd": cwd, "full": full}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Error extracting contract for '{target}': {resp.get('message') if resp else 'Daemon error'}"

    title = "Full Contract & Internals" if full else "Public Contract"
    return f"=== {title}: {resp.get('filepath')} [{resp.get('language')}] ===\n{'-'*50}\n{resp.get('contract', '')}\n{'-'*50}"

@app.tool()
def localgrep_route(query: str, path: str = ".", top_k: int = 5) -> str:
    """
    Fast Route-to-Controller Mapper: Instant (<15ms) resolution of route URLs, route names,
    or controller methods to their exact definition in routes/*.php and target controller file line.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "route", "query": query, "cwd": cwd, "top_k": top_k}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Route lookup error: {resp.get('message') if resp else 'Daemon error'}"

    results = resp.get("results", [])
    if not results:
        return f"No routes matched: '{query}'"

    out = [f"=== Route Matches for: '{query}' ==="]
    for r in results:
        name_str = f" (name: {r['name']})" if r.get("name") else ""
        lines = [
            f"\n[{r['method']}] {r['uri']}{name_str}",
            f"  Route Def:   {r['route_file']}:{r['route_line']}"
        ]
        if r.get("controller"):
            action_str = f"@{r['action']}" if r.get("action") else ""
            lines.append(f"  Controller:  {r['controller']}{action_str}")
        if r.get("target_file"):
            lines.append(f"  Target File: {r['target_file']}:{r.get('target_line', 1)}")
        out.append("\n".join(lines))
    return "\n".join(out)

@app.tool()
def localgrep_topo(path: str = ".") -> str:
    """
    Zero-Token Project Topology Card: Generates an ultra-dense, 200-token executive digest
    of framework version, PHP version, modular packages, active frontend stack, DB drivers,
    and entry points. Ideal for orienting at the start of an agent session without reading 30k tokens.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "topo", "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Topology error: {resp.get('message') if resp else 'Daemon error'}"
    return resp.get("card", "")

@app.tool()
def localgrep_callers(symbol: str, path: str = ".", include_imports: bool = False) -> str:
    """
    Deterministic Call-Site & Reference Tracker: Find all actual invocations and references
    to a method, function, or class across PHP and Vue/TS/JS. Automatically excludes
    method definitions, class headers, docblocks, and comments.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "callers", "symbol": symbol, "include_imports": include_imports, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Callers error: {resp.get('message') if resp else 'Daemon error'}"
    return resp.get("card", "")

@app.tool()
def localgrep_event_map(filter: str = "", path: str = ".") -> str:
    """
    Laravel Event-Listener-Queue-Job Architecture Map: Maps registered events to listeners,
    identifying whether each listener runs synchronously or queued, its queue connection,
    and any dispatched jobs.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "event_map", "query": filter, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Event map error: {resp.get('message') if resp else 'Daemon error'}"
    return resp.get("card", "")

@app.tool()
def localgrep_schema(model: str, path: str = ".") -> str:
    """
    Offline Database Schema & Relationship Extractor: Instantly extracts model table columns,
    types, nullability, indexing, casts, fillable attributes, and Eloquent relationships
    without connecting to a live database or running tinker.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "schema", "model": model, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Schema error: {resp.get('message') if resp else 'Daemon error'}"
    return resp.get("card", "")

@app.tool()
def localgrep_verify_patch(file_path: str, target_content: str, path: str = ".") -> str:
    """
    Pre-validate Edit/Patch Block: Validates target content uniqueness, resolves exact
    StartLine and EndLine, detects indentation/whitespace discrepancies, and returns
    drop-in arguments for replace_file_content or diff tools.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "verify_patch", "file": file_path, "target_content": target_content, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Verify patch error: Daemon error"
    return resp.get("card", "")

@app.tool()
def localgrep_patch(file_path: str, search: str, replace: str, dry_run: bool = False, force: bool = False, path: str = ".") -> str:
    """
    Atomic Fuzzy File Patcher: Replaces search block with replace block in file.
    Features:
    - Whitespace & indentation agnostic matching (resolves tab vs space discrepancies).
    - Automatically realigns the replacement block's indentation to match surrounding code.
    - Pre-flight syntax validation with automatic rollback (aborts if replacement introduces syntax errors).
    - Atomic file write to prevent corrupted states.
    Set dry_run=True to preview changes without saving.
    """
    cwd = os.path.abspath(path)
    payload = {
        "action": "patch",
        "file": file_path,
        "search": search,
        "replace": replace,
        "dry_run": dry_run,
        "force": force,
        "cwd": cwd
    }
    resp = send_request(payload)
    if not resp:
        return "Patch error: Daemon error"
    if resp.get("status") == "ok":
        return resp.get("card", "Patch applied successfully.")
    err_msg = f"Error ({resp.get('status')}): {resp.get('message')}"
    if resp.get("error_detail"):
        err_msg += f"\nDetails: {resp.get('error_detail')}"
    return err_msg

@app.tool()
def localgrep_audit_diff(staged_only: bool = False, file: str = "", path: str = ".") -> str:
    """
    Git Diff Code Auditor: Audits current git diff for leftover debug calls (dd, dump, console.log),
    temporary markers (TODO remove), potential hardcoded secrets, and PHP syntax errors before committing.
    """
    cwd = os.path.abspath(path)
    f_val = file if file else None
    payload = {"action": "audit_diff", "staged": staged_only, "file": f_val, "cwd": cwd}
    resp = send_request(payload)
    if not resp:
        return "Audit diff error: Daemon error"
    return resp.get("card", "")

@app.tool()
def localgrep_test_isolate(test_command: str = "", raw_output: str = "", path: str = ".") -> str:
    """
    Test Failure Distiller & Isolator: Executes test command or parses raw test output,
    stripping 95% of framework and vendor stack frames to isolate the exact failing test,
    assertion reason, application stack frame, and code snippet.
    """
    cwd = os.path.abspath(path)
    if raw_output:
        payload = {"action": "test_isolate", "output": raw_output, "cwd": cwd}
    elif test_command:
        cmd_parts = test_command.split()
        payload = {"action": "test_isolate", "cmd": cmd_parts, "cwd": cwd}
    else:
        return "Error: Either test_command or raw_output must be provided."

    resp = send_request(payload)
    if not resp:
        return "Test isolate error: Daemon error"
    return resp.get("card", "")

def main():
    app.run("stdio")

if __name__ == "__main__":
    main()
