import os
import re
import subprocess
from typing import Dict, Any, List, Set, Tuple, Optional

def resolve_vue_file(target: str, cwd: str) -> str:
    """Find the full path to a Vue component."""
    if os.path.isfile(os.path.join(cwd, target)):
        return os.path.join(cwd, target)

    clean = target.replace(".vue", "")
    search_dirs = [d for d in ["resources/js", "vendor/bina"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"*{clean}*.vue"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if res.stdout:
        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        for f in files:
            if os.path.basename(f) == f"{clean}.vue":
                return os.path.join(cwd, f)
        if files:
            return os.path.join(cwd, files[0])
    return ""

def extract_script_content(content: str) -> str:
    """Extract code inside <script> and <script setup> tags."""
    m = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    if m:
        return "\n".join(m)
    return content

def parse_vue_reactive_elements(script: str) -> Dict[str, Any]:
    """Extract props, emits, refs, computed, watchers, and methods from script."""
    props = set()
    emits = set()
    refs = set()
    computeds: Dict[str, str] = {}  # name -> body
    watchers: List[Dict[str, Any]] = []  # list of { sources: [], body: "" }
    methods: Dict[str, str] = {}  # name -> body

    # 1. Props
    # defineProps<{ prop1: type, prop2: type }>()
    m_ts_props = re.search(r"defineProps<\s*\{([^}]+)\}\s*>", script, re.DOTALL)
    if m_ts_props:
        for p_line in m_ts_props.group(1).split("\n"):
            p_match = re.match(r"\s*([a-zA-Z0-9_]+)\s*\??\s*:", p_line)
            if p_match:
                props.add(p_match.group(1))

    # defineProps(['prop1', 'prop2'])
    m_arr_props = re.search(r"defineProps\(\s*\[(.*?)\]\s*\)", script, re.DOTALL)
    if m_arr_props:
        for p in re.findall(r"['\"]([a-zA-Z0-9_]+)['\"]", m_arr_props.group(1)):
            props.add(p)

    # defineProps({ prop1: ..., prop2: ... })
    m_obj_props = re.search(r"defineProps\(\s*\{", script)
    if m_obj_props and not m_ts_props and not m_arr_props:
        start_idx = m_obj_props.end()
        # Find closing });
        end_idx = script.find("});", start_idx)
        if end_idx != -1:
            prop_block = script[start_idx:end_idx]
            for p_m in re.finditer(r"^\s*['\"]?([a-zA-Z0-9_]+)['\"]?\s*:\s*(?:\{|[a-zA-Z0-9_\[\]]+)", prop_block, re.MULTILINE):
                props.add(p_m.group(1))

    # 2. Emits
    # defineEmits(['emit1', 'emit2'])
    m_arr_emits = re.search(r"defineEmits\(\s*\[(.*?)\]\s*\)", script, re.DOTALL)
    if m_arr_emits:
        for e in re.findall(r"['\"]([a-zA-Z0-9_:-]+)['\"]", m_arr_emits.group(1)):
            emits.add(e)

    # emit('eventName') or $emit('eventName') calls in script
    for e in re.findall(r"(?:\$emit|emit)\(\s*['\"]([a-zA-Z0-9_:-]+)['\"]", script):
        emits.add(e)

    # 3. Refs / Reactives
    # const foo = ref(...) or reactive(...)
    for r_match in re.finditer(r"(?:const|let)\s+([a-zA-Z0-9_]+)\s*=\s*(?:ref|reactive|shallowRef)\s*\(", script):
        refs.add(r_match.group(1))

    # 4. Computeds
    # const myComp = computed(() => { ... }) or computed(() => expr)
    for c_match in re.finditer(r"(?:const|let)\s+([a-zA-Z0-9_]+)\s*=\s*computed\s*\(\s*(?:\([^)]*\)|[a-zA-Z0-9_]+)?\s*=>\s*(\{.*?\n\s*\}|[^\n;]+)", script, re.DOTALL):
        c_name = c_match.group(1)
        c_body = c_match.group(2)
        computeds[c_name] = c_body

    # 5. Watchers
    # watch(source, (val) => { ... }) or watch(() => props.foo, ...) or watch([s1, s2], ...)
    for w_match in re.finditer(r"watch\s*\(\s*([^,]+?)\s*,\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)?\s*=>\s*\{(?P<body>.*?)\n\s*\}\s*\)", script, re.DOTALL):
        w_sources_raw = w_match.group(1).strip()
        w_body = w_match.group("body")

        # Parse source expressions
        sources = []
        if w_sources_raw.startswith("[") and w_sources_raw.endswith("]"):
            sources = [s.strip() for s in w_sources_raw[1:-1].split(",") if s.strip()]
        else:
            sources = [w_sources_raw]

        clean_sources = []
        for s in sources:
            # Handle () => props.foo or () => foo.value
            m_fn = re.search(r"=>\s*(?:props\.)?([a-zA-Z0-9_]+)", s)
            if m_fn:
                clean_sources.append(m_fn.group(1))
            else:
                m_direct = re.search(r"(?:props\.)?([a-zA-Z0-9_]+)", s)
                if m_direct:
                    clean_sources.append(m_direct.group(1))

        watchers.append({
            "sources": clean_sources,
            "body": w_body
        })

    # 6. Methods / Functions
    # function myMethod() { ... } or const myMethod = () => { ... }
    for fn_match in re.finditer(r"(?:function\s+([a-zA-Z0-9_]+)\s*\([^\)]*\)|(?:const|let)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^\)]*\)\s*=>)\s*\{", script):
        name = fn_match.group(1) or fn_match.group(2)
        if name and name not in refs and name not in computeds:
            # find rough body
            start = fn_match.end()
            methods[name] = script[start:start+300]

    return {
        "props": sorted(list(props)),
        "emits": sorted(list(emits)),
        "refs": sorted(list(refs)),
        "computeds": computeds,
        "watchers": watchers,
        "methods": methods
    }

def build_reactive_dag(elements: Dict[str, Any]) -> List[List[str]]:
    """Build directed causal flow chains: prop/ref -> computed -> watch -> emit/method."""
    props = set(elements["props"])
    refs = set(elements["refs"])
    computeds = elements["computeds"]
    watchers = elements["watchers"]
    emits = set(elements["emits"])
    methods = elements["methods"]

    all_state_sources = props | refs
    chains = []

    # Map computed dependencies
    comp_deps: Dict[str, Set[str]] = {}
    for c_name, c_body in computeds.items():
        comp_deps[c_name] = set()
        for src in all_state_sources | set(computeds.keys()):
            if src != c_name and re.search(rf"\b(?:props\.)?{re.escape(src)}\b", c_body):
                comp_deps[c_name].add(src)

    # Map watcher flows
    # source -> watch -> emit/method/ref
    for idx, w in enumerate(watchers):
        w_sources = w["sources"]
        w_body = w["body"]

        # find what watch modifies or emits
        w_emits = [e for e in emits if re.search(rf"emit\(\s*['\"]{re.escape(e)}['\"]", w_body)]
        w_methods = [m for m in methods if re.search(rf"\b{re.escape(m)}\s*\(", w_body)]
        w_refs_mod = [r for r in refs if re.search(rf"\b{re.escape(r)}\.value\s*=", w_body)]

        outcomes = []
        for e in w_emits: outcomes.append(f"[emit: {e}]")
        for m in w_methods: outcomes.append(f"[method: {m}]")
        for r in w_refs_mod: outcomes.append(f"[ref: {r}]")

        if not outcomes:
            outcomes = ["(internal side-effect)"]

        for src in w_sources:
            src_type = "prop" if src in props else ("ref" if src in refs else ("computed" if src in computeds else "state"))
            for out in outcomes:
                chains.append([f"[{src_type}: {src}]", f"[watch: {src}]", out])

    # Map computed chains
    for c_name, deps in comp_deps.items():
        for d in deps:
            d_type = "prop" if d in props else ("ref" if d in refs else "computed")
            chains.append([f"[{d_type}: {d}]", f"[computed: {c_name}]"])

    # Map methods triggering emits
    for m_name, m_body in methods.items():
        m_emits = [e for e in emits if re.search(rf"emit\(\s*['\"]{re.escape(e)}['\"]", m_body)]
        for e in m_emits:
            chains.append([f"[method: {m_name}]", f"[emit: {e}]"])

    return chains

def generate_state_map(target: str, cwd: str = ".") -> Dict[str, Any]:
    """Generate state and reactive dependency map for Vue 3 SFC."""
    full_path = resolve_vue_file(target, cwd)
    if not full_path or not os.path.isfile(full_path):
        return {
            "status": "error",
            "message": f"Vue component '{target}' not found."
        }

    rel_path = os.path.relpath(full_path, cwd)
    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    script = extract_script_content(content)
    elements = parse_vue_reactive_elements(script)
    chains = build_reactive_dag(elements)

    return {
        "status": "ok",
        "file": rel_path,
        "component": os.path.basename(rel_path).replace(".vue", ""),
        "props_count": len(elements["props"]),
        "props": elements["props"],
        "refs_count": len(elements["refs"]),
        "refs": elements["refs"],
        "computeds_count": len(elements["computeds"]),
        "computeds": list(elements["computeds"].keys()),
        "emits_count": len(elements["emits"]),
        "emits": elements["emits"],
        "watchers_count": len(elements["watchers"]),
        "flow_chains": chains
    }

def format_state_map_text(res: Dict[str, Any]) -> str:
    """Format reactive dependency graph into ASCII DAG."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to generate state map.')}"

    comp = res.get("component")
    f_path = res.get("file")

    lines = [
        f"=== Reactive State DAG for: {comp}.vue ===",
        f"File: {f_path}",
        f"Summary: {res.get('props_count', 0)} props | {res.get('refs_count', 0)} refs | {res.get('computeds_count', 0)} computeds | {res.get('emits_count', 0)} emits",
        ""
    ]

    chains = res.get("flow_chains", [])
    if chains:
        lines.append("Reactive Dependency Flows:")
        for c in chains:
            lines.append("  " + " ──> ".join(c))
    else:
        lines.append("No reactive dependency chains detected.")

    lines.append("")
    props = res.get("props", [])
    if props:
        lines.append(f"Props: {', '.join(props)}")
    emits = res.get("emits", [])
    if emits:
        lines.append(f"Emits: {', '.join(emits)}")

    return "\n".join(lines)
