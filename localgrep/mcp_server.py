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
