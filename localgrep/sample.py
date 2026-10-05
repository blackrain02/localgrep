import os
import re
import json
import subprocess
from typing import Dict, Any, Optional, Tuple

SENSITIVE_FIELDS = {
    "password", "remember_token", "two_factor_secret", "two_factor_recovery_codes",
    "secret", "api_key", "token", "access_token", "refresh_token", "card_token"
}

def parse_env_db(cwd: str) -> Dict[str, str]:
    env_file = os.path.join(cwd, ".env")
    db_config = {
        "connection": "pgsql",
        "database": "",
        "username": "",
        "password": "",
        "host": "127.0.0.1",
        "port": "5432",
        "socket": ""
    }
    if not os.path.isfile(env_file):
        return db_config

    try:
        with open(env_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"\'')
                if k == "DB_CONNECTION": db_config["connection"] = v
                elif k == "DB_DATABASE": db_config["database"] = v
                elif k == "DB_USERNAME": db_config["username"] = v
                elif k == "DB_PASSWORD": db_config["password"] = v
                elif k == "DB_HOST": db_config["host"] = v
                elif k == "DB_PORT": db_config["port"] = v
                elif k == "DB_SOCKET": db_config["socket"] = v
    except Exception:
        pass

    return db_config

def resolve_table_for_target(target: str, cwd: str) -> Tuple[str, str, str]:
    clean_target = target.strip()
    try:
        from localgrep.schema import resolve_model_file, to_snake_case_plural
    except ImportError:
        try:
            from .schema import resolve_model_file, to_snake_case_plural
        except ImportError:
            from schema import resolve_model_file, to_snake_case_plural

    rel_model_file = resolve_model_file(clean_target, cwd)
    full_path = os.path.join(cwd, rel_model_file) if rel_model_file else ""
    if full_path and os.path.isfile(full_path):
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        model_name = os.path.basename(full_path).replace(".php", "")
        t_match = re.search(r"protected\s+\$table\s*=\s*['\"]([^'\"]+)['\"]", content)
        table_name = t_match.group(1) if t_match else to_snake_case_plural(model_name)
        return model_name, table_name, rel_model_file

    # Assume direct table name
    return clean_target, clean_target.lower(), ""

def fetch_sample_row(table: str, db_config: Dict[str, str], cwd: str) -> Optional[Dict[str, Any]]:
    conn = db_config["connection"].lower()
    database = db_config["database"]

    if conn in ("pgsql", "postgres", "postgresql"):
        query = f'SELECT row_to_json(t) FROM (SELECT * FROM "{table}" LIMIT 1) t;'
        env = os.environ.copy()
        if db_config["password"]:
            env["PGPASSWORD"] = db_config["password"]

        cmd = ["psql"]
        if db_config.get("socket") and os.path.exists(db_config["socket"]):
            cmd.extend(["-h", db_config["socket"]])
        elif db_config.get("host") and db_config["host"] not in ("localhost", "127.0.0.1"):
            cmd.extend(["-h", db_config["host"]])

        if db_config.get("username"):
            cmd.extend(["-U", db_config["username"]])
        if database:
            cmd.extend(["-d", database])
        cmd.extend(["-t", "-A", "-c", query])

        try:
            proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                return json.loads(proc.stdout.strip())
        except Exception:
            pass

    elif conn == "sqlite":
        db_path = database if os.path.isabs(database) else os.path.join(cwd, database)
        if os.path.isfile(db_path):
            try:
                import sqlite3
                con = sqlite3.connect(db_path)
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                cur.execute(f"SELECT * FROM `{table}` LIMIT 1")
                row = cur.fetchone()
                if row:
                    return dict(row)
            except Exception:
                pass

    # Fallback via artisan tinker
    tinker_code = f"echo json_encode(\\DB::table('{table}')->first());"
    try:
        proc = subprocess.run(
            ["php", "artisan", "tinker", "--execute", tinker_code],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            # extract JSON object
            m = re.search(r'\{.*\}', out)
            if m:
                return json.loads(m.group(0))
    except Exception:
        pass

    return None

def get_sample_record(target: str, cwd: str = ".") -> Dict[str, Any]:
    model_name, table_name, model_file = resolve_table_for_target(target, cwd)
    db_config = parse_env_db(cwd)
    row = fetch_sample_row(table_name, db_config, cwd)

    if not row:
        return {
            "status": "error",
            "message": f"Could not retrieve sample record for table '{table_name}' (Model: {model_name}). Table may be empty or database unreachable.",
            "target": target,
            "table": table_name
        }

    # Format fields and types
    fields = []
    sample_id = row.get("id", None)
    for col, val in row.items():
        is_sensitive = col.lower() in SENSITIVE_FIELDS
        if is_sensitive:
            val_str = "[REDACTED]"
            val_type = "hidden"
        elif val is None:
            val_str = "null"
            val_type = "null"
        elif isinstance(val, bool):
            val_str = str(val).lower()
            val_type = "boolean"
        elif isinstance(val, (int, float)):
            val_str = str(val)
            val_type = "integer" if isinstance(val, int) else "float"
        elif isinstance(val, (dict, list)):
            val_str = json.dumps(val, ensure_ascii=False)
            val_type = "json"
        else:
            val_str = str(val)
            # Try to see if string is actually JSON
            if (val_str.startswith("{") and val_str.endswith("}")) or (val_str.startswith("[") and val_str.endswith("]")):
                try:
                    parsed = json.loads(val_str)
                    val_str = json.dumps(parsed, ensure_ascii=False)
                    val_type = "json_string"
                except Exception:
                    val_type = "string"
            else:
                val_type = "string"

            # Truncate long strings (> 80 chars) for compactness
            if len(val_str) > 80:
                val_str = val_str[:77] + "..."

        fields.append({
            "column": col,
            "type": val_type,
            "value": val_str
        })

    return {
        "status": "ok",
        "target": target,
        "model": model_name,
        "table": table_name,
        "model_file": model_file,
        "sample_id": sample_id,
        "fields": fields
    }

def format_sample_text(res: Dict[str, Any]) -> str:
    if res.get("status") != "ok":
        return f"Error: {res.get('message', 'Failed to retrieve sample record.')}"

    model_label = res.get("model") or res.get("target")
    table_label = res.get("table", "")
    sample_id = res.get("sample_id")
    id_str = f" (Sample ID: {sample_id})" if sample_id is not None else ""
    lines = [
        f"=== Sample Record: {model_label}{id_str} [table: {table_label}] ==="
    ]
    if res.get("model_file"):
        lines.append(f"Model File: {res['model_file']}")
    lines.append("")

    for f in res.get("fields", []):
        col = f["column"]
        t = f["type"]
        v = f["value"]
        lines.append(f"  - {col}: {v} ({t})")

    return "\n".join(lines)
