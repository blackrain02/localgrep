import os
import re
import subprocess
from typing import Dict, Any, List

def parse_use_statements(content: str) -> Dict[str, str]:
    """Extract use statements into alias -> full namespace mapping."""
    uses = {}
    for m in re.finditer(r"use\s+([A-Za-z0-9_\\]+)(?:\s+as\s+([A-Za-z0-9_]+))?\s*;", content):
        full = m.group(1).strip("\\")
        alias = m.group(2) if m.group(2) else full.split("\\")[-1]
        uses[alias] = full
    return uses

def inspect_listener_details(listener_cls: str, cwd: str) -> Dict[str, Any]:
    """Inspect listener implementation to detect queue status, queue name, and dispatched jobs."""
    clean_name = listener_cls.split("\\")[-1]
    search_dirs = [d for d in ["app", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"{clean_name}.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    target_file = ""
    if res.stdout:
        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        if files:
            target_file = files[0]

    queued = False
    queue_name = "sync"
    jobs = []

    if target_file and os.path.isfile(os.path.join(cwd, target_file)):
        try:
            with open(os.path.join(cwd, target_file), "r", encoding="utf-8", errors="ignore") as f:
                c = f.read()
            if "implements ShouldQueue" in c or "implements \\Illuminate\\Contracts\\Queue\\ShouldQueue" in c:
                queued = True
                queue_name = "default"
                q_m = re.search(r"public\s+\$queue\s*=\s*['\"]([^'\"]+)['\"]", c)
                if q_m:
                    queue_name = q_m.group(1)

            job_matches = re.findall(r"([A-Za-z0-9_]+Job)::dispatch", c)
            job_matches += re.findall(r"dispatch\s*\(\s*new\s+([A-Za-z0-9_]+Job)", c)
            jobs = sorted(list(set(job_matches)))
        except Exception:
            pass

    return {
        "file": target_file,
        "queued": queued,
        "queue": queue_name,
        "dispatches_jobs": jobs
    }

def get_event_map(query: str, cwd: str) -> Dict[str, Any]:
    """Map all Laravel Events, Listeners, Queue strategies, and Dispatched Jobs."""
    search_dirs = [d for d in ["app", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", "*EventServiceProvider.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    provider_files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip() and "vendor/laravel/framework" not in f]

    events_map: Dict[str, List[Dict[str, Any]]] = {}

    for pf in provider_files:
        full_path = os.path.join(cwd, pf)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            uses = parse_use_statements(content)
            listen_m = re.search(r"protected\s+\$listen\s*=\s*\[(.*?)\];", content, re.DOTALL)
            if not listen_m:
                continue
            block = listen_m.group(1)

            for em in re.finditer(r"([A-Za-z0-9_\\]+)::class\s*=>\s*\[(.*?)\]", block, re.DOTALL):
                event_raw = em.group(1)
                listeners_raw = em.group(2)

                event_short = event_raw.split("\\")[-1]
                event_full = uses.get(event_short, event_raw)

                listener_names = re.findall(r"([A-Za-z0-9_\\]+)::class", listeners_raw)
                for l_name in listener_names:
                    l_short = l_name.split("\\")[-1]
                    l_full = uses.get(l_short, l_name)
                    details = inspect_listener_details(l_short, cwd)

                    entry = {
                        "event": event_short,
                        "event_class": event_full,
                        "listener": l_short,
                        "listener_class": l_full,
                        "listener_file": details["file"],
                        "queued": details["queued"],
                        "queue": details["queue"],
                        "dispatches_jobs": details["dispatches_jobs"],
                        "provider_file": pf
                    }
                    events_map.setdefault(event_short, []).append(entry)
        except Exception:
            continue

    q_lower = query.lower().strip()
    filtered_map: Dict[str, List[Dict[str, Any]]] = {}

    for evt, listeners in events_map.items():
        if not q_lower:
            filtered_map[evt] = listeners
        else:
            matching_listeners = [
                l for l in listeners
                if q_lower in evt.lower()
                or q_lower in l["event_class"].lower()
                or q_lower in l["listener"].lower()
                or any(q_lower in j.lower() for j in l["dispatches_jobs"])
            ]
            if matching_listeners or q_lower in evt.lower():
                filtered_map[evt] = matching_listeners if matching_listeners else listeners

    total_listeners = sum(len(l) for l in filtered_map.values())
    card_lines = [
        f"=== Laravel Event Map ({len(filtered_map)} Events, {total_listeners} Listeners) ==="
    ]
    for evt, listeners in filtered_map.items():
        evt_class = listeners[0]["event_class"] if listeners else evt
        card_lines.append(f"\n[Event] {evt} ({evt_class})")
        for l in listeners:
            q_type = f"Queue: {l['queue']}" if l["queued"] else "Sync"
            jobs_str = f" -> Dispatches: {', '.join(l['dispatches_jobs'])}" if l["dispatches_jobs"] else ""
            card_lines.append(f"  └── [{q_type}] {l['listener']}{jobs_str}")
            if l.get("listener_file"):
                card_lines.append(f"       File: {l['listener_file']}")

    return {
        "status": "ok",
        "query": query,
        "events_count": len(filtered_map),
        "listeners_count": total_listeners,
        "events": filtered_map,
        "card": "\n".join(card_lines)
    }
