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

def main():
    app.run("stdio")

if __name__ == "__main__":
    main()
