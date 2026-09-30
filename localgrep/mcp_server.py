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
def localgrep_contract(target: str, path: str = ".") -> str:
    """
    Component & Class Contract Extractor: Extract Vue defineProps/defineEmits/slots,
    PHP public methods/constructor parameters, or TypeScript interfaces in <10ms.
    Eliminates reading huge 400+ line files when you only need to know props or method signatures.
    """
    cwd = os.path.abspath(path)
    payload = {"action": "contract", "target": target, "cwd": cwd}
    resp = send_request(payload)
    if not resp or resp.get("status") != "ok":
        return f"Error extracting contract for '{target}': {resp.get('message') if resp else 'Daemon error'}"

    return f"=== Public Contract: {resp.get('filepath')} [{resp.get('language')}] ===\n{'-'*50}\n{resp.get('contract', '')}\n{'-'*50}"

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

def main():
    app.run("stdio")

if __name__ == "__main__":
    main()
