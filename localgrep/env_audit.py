import os
import re
import json
import subprocess
from typing import Dict, Any, List, Set, Optional

def parse_env_file(cwd: str) -> Dict[str, str]:
    """Parse .env file into key-value dictionary."""
    env_path = os.path.join(cwd, ".env")
    env_vars = {}
    if not os.path.isfile(env_path):
        return env_vars

    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"\'')
                env_vars[k] = v
    except Exception:
        pass
    return env_vars

def scan_config_env_calls(cwd: str) -> Dict[str, List[Dict[str, Any]]]:
    """Scan all config/*.php files for env('KEY', default) calls."""
    config_dirs = [d for d in ["config", "vendor/bina"] if os.path.isdir(os.path.join(cwd, d))]
    env_refs: Dict[str, List[Dict[str, Any]]] = {}

    for cdir in config_dirs:
        for root, _, files in os.walk(os.path.join(cwd, cdir)):
            if "/vendor/bina/" in root and not root.endswith("/config"):
                continue
            for file in files:
                if not file.endswith(".php"):
                    continue
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, cwd)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Find env('VAR_NAME', default)
                    matches = re.finditer(r"env\(\s*['\"]([A-Z0-9_]+)['\"](?:\s*,\s*([^)]*))?\)", content)
                    for m in matches:
                        var_name = m.group(1)
                        default_val = m.group(2).strip() if m.group(2) else None
                        env_refs.setdefault(var_name, []).append({
                            "file": rel_path,
                            "default": default_val
                        })
                except Exception:
                    pass

    return env_refs

def check_db_tables(cwd: str, env_vars: Dict[str, str]) -> Set[str]:
    """Peek database tables via psql or sqlite to verify table-dependent env features."""
    conn = env_vars.get("DB_CONNECTION", "pgsql").lower()
    database = env_vars.get("DB_DATABASE", "")
    tables = set()

    if conn in ("pgsql", "postgres", "postgresql") and database:
        cmd = ["psql"]
        socket = env_vars.get("DB_SOCKET", "")
        host = env_vars.get("DB_HOST", "127.0.0.1")
        user = env_vars.get("DB_USERNAME", "")
        pwd = env_vars.get("DB_PASSWORD", "")

        if socket and os.path.exists(socket):
            cmd.extend(["-h", socket])
        elif host and host not in ("localhost", "127.0.0.1"):
            cmd.extend(["-h", host])
        if user:
            cmd.extend(["-U", user])
        cmd.extend(["-d", database, "-t", "-A", "-c", "SELECT tablename FROM pg_tables WHERE schemaname='public';"])

        env = os.environ.copy()
        if pwd:
            env["PGPASSWORD"] = pwd

        try:
            p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
            if p.returncode == 0:
                for line in p.stdout.strip().split("\n"):
                    if line.strip():
                        tables.add(line.strip().lower())
        except Exception:
            pass

    elif conn == "sqlite":
        db_path = database if os.path.isabs(database) else os.path.join(cwd, database)
        if os.path.isfile(db_path):
            try:
                import sqlite3
                con = sqlite3.connect(db_path)
                cur = con.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
                for row in cur.fetchall():
                    tables.add(row[0].lower())
                con.close()
            except Exception:
                pass

    return tables

def audit_environment(cwd: str = ".") -> Dict[str, Any]:
    """Audit .env integrity, config bindings, and service dependencies."""
    env_path = os.path.join(cwd, ".env")
    if not os.path.isfile(env_path):
        return {
            "status": "error",
            "message": "No .env file found in root workspace directory.",
            "issues": [{"severity": "ERROR", "message": "Missing .env file in root workspace."}]
        }

    env_vars = parse_env_file(cwd)
    config_refs = scan_config_env_calls(cwd)
    existing_tables = check_db_tables(cwd, env_vars)

    issues = []

    # 1. Core Required Keys
    app_key = env_vars.get("APP_KEY", "")
    if not app_key:
        issues.append({
            "severity": "ERROR",
            "key": "APP_KEY",
            "message": "APP_KEY is missing or empty in .env. Run 'php artisan key:generate'."
        })

    # 2. Production Debug Check
    app_env = env_vars.get("APP_ENV", "local").lower()
    app_debug = env_vars.get("APP_DEBUG", "false").lower()
    if app_env == "production" and app_debug == "true":
        issues.append({
            "severity": "ERROR",
            "key": "APP_DEBUG",
            "message": "APP_DEBUG is true while APP_ENV is production. Security exposure risk!"
        })

    # 3. Database Integrity
    db_conn = env_vars.get("DB_CONNECTION")
    db_name = env_vars.get("DB_DATABASE")
    if not db_name and db_conn != "sqlite":
        issues.append({
            "severity": "ERROR",
            "key": "DB_DATABASE",
            "message": f"DB_DATABASE is empty in .env with connection '{db_conn}'."
        })

    # 4. Service Specific Checks: Telescope
    telescope_enabled = env_vars.get("TELESCOPE_ENABLED", "").lower()
    if telescope_enabled in ("true", "1") and existing_tables and "telescope_entries" not in existing_tables:
        issues.append({
            "severity": "WARN",
            "key": "TELESCOPE_ENABLED",
            "message": "TELESCOPE_ENABLED=true in .env, but table 'telescope_entries' does not exist in database."
        })

    # 5. Service Specific Checks: Pulse
    pulse_enabled = env_vars.get("PULSE_ENABLED", "").lower()
    if pulse_enabled in ("true", "1") and existing_tables and "pulse_entries" not in existing_tables and "pulse_values" not in existing_tables:
        issues.append({
            "severity": "WARN",
            "key": "PULSE_ENABLED",
            "message": "PULSE_ENABLED=true in .env, but table 'pulse_entries' does not exist in database."
        })

    # 6. Service Specific Checks: Reverb / Broadcasting
    bcast = env_vars.get("BROADCAST_CONNECTION", env_vars.get("BROADCAST_DRIVER", "")).lower()
    if bcast == "reverb":
        if not env_vars.get("REVERB_APP_KEY"):
            issues.append({
                "severity": "WARN",
                "key": "REVERB_APP_KEY",
                "message": "BROADCAST_CONNECTION=reverb, but REVERB_APP_KEY is empty in .env."
            })
        if not env_vars.get("REVERB_APP_SECRET"):
            issues.append({
                "severity": "WARN",
                "key": "REVERB_APP_SECRET",
                "message": "BROADCAST_CONNECTION=reverb, but REVERB_APP_SECRET is empty in .env."
            })

    # 7. Service Specific Checks: Redis Queue / Cache
    queue_driver = env_vars.get("QUEUE_CONNECTION", "").lower()
    cache_driver = env_vars.get("CACHE_STORE", env_vars.get("CACHE_DRIVER", "")).lower()
    if (queue_driver == "redis" or cache_driver == "redis") and not env_vars.get("REDIS_HOST"):
        issues.append({
            "severity": "WARN",
            "key": "REDIS_HOST",
            "message": "Redis driver is used for queue or cache, but REDIS_HOST is not specified in .env."
        })

    # 8. Check Missing Env Keys with No Default in Config
    critical_prefixes = ("DB_", "APP_", "CACHE_", "QUEUE_", "SESSION_", "MAIL_", "AWS_", "S3_")
    for key, refs in config_refs.items():
        if not key.startswith(critical_prefixes):
            continue
        if key not in env_vars:
            no_default_refs = [r for r in refs if r["default"] in (None, "null", "''", '""')]
            if no_default_refs:
                files = ", ".join(list(set(r["file"] for r in no_default_refs))[:2])
                issues.append({
                    "severity": "WARN",
                    "key": key,
                    "message": f"'{key}' referenced in {files} without default value, but missing in .env."
                })

    errors_count = sum(1 for i in issues if i["severity"] == "ERROR")
    warns_count = sum(1 for i in issues if i["severity"] == "WARN")

    return {
        "status": "ok",
        "env_path": os.path.relpath(env_path, cwd),
        "total_env_keys": len(env_vars),
        "total_config_refs": len(config_refs),
        "tables_detected": len(existing_tables),
        "errors_count": errors_count,
        "warns_count": warns_count,
        "issues": issues
    }

def format_env_audit_text(res: Dict[str, Any]) -> str:
    """Format environment audit report into clean CLI card."""
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to run env audit.')}"

    err_c = res.get("errors_count", 0)
    warn_c = res.get("warns_count", 0)
    status_str = "CLEAN" if (err_c == 0 and warn_c == 0) else f"{err_c} ERROR(S), {warn_c} WARNING(S)"

    lines = [
        f"=== Environment & Configuration Audit [{status_str}] ===",
        f"Target: {res.get('env_path', '.env')} ({res.get('total_env_keys', 0)} keys defined)",
        f"Database Schema: {res.get('tables_detected', 0)} public tables detected",
        ""
    ]

    issues = res.get("issues", [])
    if not issues:
        lines.append("  All critical environment variables and configuration dependencies are valid.")
    else:
        for iss in issues:
            sev = iss.get("severity", "WARN")
            key = f" [{iss['key']}]" if iss.get("key") else ""
            lines.append(f"[{sev}]{key} {iss['message']}")

    return "\n".join(lines)
