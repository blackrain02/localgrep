import os
import json
import re
from typing import Dict, Any, List

def get_project_topology(cwd: str) -> Dict[str, Any]:
    topo = {
        "status": "ok",
        "app_name": "Unknown",
        "php_version": "Unknown",
        "framework": "Unknown",
        "ecosystem": [],
        "modules_count": 0,
        "modules": [],
        "frontend": [],
        "runtime": {},
        "entrypoints": {}
    }

    # 1. Composer Inspection
    comp_file = os.path.join(cwd, "composer.json")
    if os.path.isfile(comp_file):
        try:
            with open(comp_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            topo["app_name"] = cdata.get("name", os.path.basename(cwd))
            req = cdata.get("require", {})
            req_dev = cdata.get("require-dev", {})
            all_req = {**req, **req_dev}

            if "php" in req:
                topo["php_version"] = req["php"].strip("^~")

            if "laravel/framework" in req:
                topo["framework"] = "Laravel " + req["laravel/framework"].strip("^~")

            # Ecosystem packages
            eco_keys = [
                ("laravel/octane", "Octane"),
                ("laravel/horizon", "Horizon"),
                ("laravel/reverb", "Reverb"),
                ("laravel/sanctum", "Sanctum"),
                ("inertiajs/inertia-laravel", "Inertia"),
                ("livewire/livewire", "Livewire"),
                ("pestphp/pest", "Pest"),
                ("tightenco/ziggy", "Ziggy")
            ]
            for pkg, label in eco_keys:
                if pkg in all_req:
                    ver = all_req[pkg].strip("^~")
                    topo["ecosystem"].append(f"{label} v{ver}")

            # Modules discovery (bina/ packages or vendor/bina or Modules/)
            bina_mods = [k.replace("bina/", "") for k in req.keys() if k.startswith("bina/")]
            if not bina_mods:
                # Check vendor/bina directory
                bina_dir = os.path.join(cwd, "vendor", "bina")
                if os.path.isdir(bina_dir):
                    bina_mods = [d for d in os.listdir(bina_dir) if os.path.isdir(os.path.join(bina_dir, d))]
                else:
                    mod_dir = os.path.join(cwd, "Modules")
                    if os.path.isdir(mod_dir):
                        bina_mods = [d for d in os.listdir(mod_dir) if os.path.isdir(os.path.join(mod_dir, d))]

            bina_mods = sorted(list(set(bina_mods)))
            topo["modules_count"] = len(bina_mods)
            topo["modules"] = bina_mods
        except Exception:
            pass

    # 2. Package.json Inspection
    pkg_file = os.path.join(cwd, "package.json")
    if os.path.isfile(pkg_file):
        try:
            with open(pkg_file, "r", encoding="utf-8") as f:
                pdata = json.load(f)
            deps = {**pdata.get("dependencies", {}), **pdata.get("devDependencies", {})}
            fe_keys = [
                ("vue", "Vue"),
                ("@inertiajs/vue3", "Inertia Vue"),
                ("tailwindcss", "Tailwind"),
                ("typescript", "TypeScript"),
                ("vite", "Vite")
            ]
            for pkg, label in fe_keys:
                if pkg in deps:
                    ver = deps[pkg].strip("^~")
                    topo["frontend"].append(f"{label} {ver}")
        except Exception:
            pass

    # 3. Server / DB / Queue Runtime Config
    db_default = "MySQL"
    env_file = os.path.join(cwd, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("DB_CONNECTION="):
                        db_default = line.split("=")[1].strip()
                    elif line.startswith("OCTANE_SERVER="):
                        topo["runtime"]["octane_server"] = line.split("=")[1].strip()
                    elif line.startswith("QUEUE_CONNECTION="):
                        topo["runtime"]["queue"] = line.split("=")[1].strip()
        except Exception:
            pass

    topo["runtime"]["database"] = db_default

    # 4. Entrypoints
    routes = []
    if os.path.isfile(os.path.join(cwd, "routes", "web.php")):
        routes.append("routes/web.php")
    if os.path.isfile(os.path.join(cwd, "routes", "api.php")):
        routes.append("routes/api.php")

    topo["entrypoints"]["routes"] = routes
    if os.path.isdir(os.path.join(cwd, "resources", "js", "Pages")):
        topo["entrypoints"]["pages"] = "resources/js/Pages"
    if os.path.isdir(os.path.join(cwd, "resources", "config")):
        topo["entrypoints"]["settings"] = "resources/config"

    # Format Card
    card_lines = [
        "=" * 70,
        f"Project Topology: {topo['app_name']} ({topo['framework']} · PHP {topo['php_version']})",
        "=" * 70,
        f"Frontend:    {' · '.join(topo['frontend']) if topo['frontend'] else 'Blade / SSR'}",
        f"Ecosystem:   {' · '.join(topo['ecosystem']) if topo['ecosystem'] else 'Standard Laravel'}",
        f"Database:    {topo['runtime'].get('database', 'Default')} (Queue: {topo['runtime'].get('queue', 'default')})",
        f"Modules:     {topo['modules_count']} active modules in vendor/bina/ or Modules/",
    ]
    if topo["modules"]:
        mod_chunk = ", ".join(topo["modules"][:15])
        if len(topo["modules"]) > 15:
            mod_chunk += f", +{len(topo['modules']) - 15} more"
        card_lines.append(f"             [{mod_chunk}]")

    card_lines.append(f"Entrypoints: {', '.join(topo['entrypoints'].get('routes', []))}")
    if "pages" in topo["entrypoints"]:
        card_lines.append(f"             {topo['entrypoints']['pages']}/ (Inertia Pages)")
    if "settings" in topo["entrypoints"]:
        card_lines.append(f"             {topo['entrypoints']['settings']}/ (Client Settings)")

    card_lines.append("=" * 70)

    topo["card"] = "\n".join(card_lines)
    return topo
