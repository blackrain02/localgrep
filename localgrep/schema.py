import os
import re
import subprocess
from typing import Dict, Any, List

def to_snake_case_plural(name: str) -> str:
    """Convert PascalCase model name to snake_case plural table name."""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    if snake.endswith('y') and not snake.endswith(('ay', 'ey', 'oy', 'uy')):
        return snake[:-1] + 'ies'
    if snake.endswith(('s', 'x', 'z', 'ch', 'sh')):
        return snake + 'es'
    return snake + 's'

def resolve_model_file(model_target: str, cwd: str) -> str:
    """Find the Model PHP file path from model name or partial path."""
    if os.path.isfile(os.path.join(cwd, model_target)):
        return model_target

    clean_name = model_target.replace(".php", "").split("\\")[-1]
    search_dirs = [d for d in ["app/Models", "app", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"{clean_name}.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if res.stdout:
        files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]
        for f in files:
            if "/Models/" in f or f.startswith("app/Models"):
                return f
        if files:
            return files[0]
    return ""

def parse_migration_columns(table_name: str, cwd: str) -> List[Dict[str, Any]]:
    """Scan migration files to extract table columns, types, nullability, and indexing."""
    search_dirs = [d for d in ["database/migrations", "vendor/bina", "Modules"] if os.path.isdir(os.path.join(cwd, d))]
    if not search_dirs:
        search_dirs = ["."]

    cmd = ["rg", "--files", "-g", f"*create_{table_name}_table.php", "-g", f"*{table_name}*.php"] + search_dirs
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if not res.stdout:
        return []

    migration_files = [f.strip() for f in res.stdout.strip().split("\n") if f.strip() and "/migrations/" in f]
    columns = []
    seen = set()

    create_files = [f for f in migration_files if f"create_{table_name}_table" in f]
    other_files = [f for f in migration_files if f not in create_files]
    ordered_files = create_files + other_files

    for mf in ordered_files:
        full_path = os.path.join(cwd, mf)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            pat = rf"Schema::(?:create|table)\s*\(\s*['\"]{table_name}['\"]\s*,\s*function\s*\([^\)]*\)\s*\{{(?P<body>.*?)\}}\s*\);"
            match = re.search(pat, content, re.DOTALL)
            if not match:
                continue

            body = match.group("body")
            col_matches = re.findall(r"\$table->([a-zA-Z0-9_]+)\s*\((.*?)\)(.*?);", body)
            for col_type, col_args, modifiers in col_matches:
                if col_type.startswith("drop") or col_type in ("index", "unique", "primary", "foreign"):
                    continue

                if col_type == "timestamps":
                    for ts_col in ("created_at", "updated_at"):
                        if ts_col not in seen:
                            seen.add(ts_col)
                            columns.append({"name": ts_col, "type": "timestamp", "nullable": True})
                    continue
                if col_type == "softDeletes":
                    if "deleted_at" not in seen:
                        seen.add("deleted_at")
                        columns.append({"name": "deleted_at", "type": "timestamp", "nullable": True})
                    continue
                if col_type in ("id", "bigIncrements"):
                    if "id" not in seen:
                        seen.add("id")
                        columns.append({"name": "id", "type": "id (PK)", "nullable": False})
                    continue

                name_m = re.search(r"['\"]([a-zA-Z0-9_]+)['\"]", col_args)
                if not name_m:
                    continue
                col_name = name_m.group(1)
                if col_name not in seen:
                    seen.add(col_name)
                    columns.append({
                        "name": col_name,
                        "type": col_type,
                        "nullable": "nullable" in modifiers,
                        "indexed": "index" in modifiers or "unique" in modifiers
                    })
        except Exception:
            continue

    return columns

def get_model_schema(model_target: str, cwd: str) -> Dict[str, Any]:
    """Offline extraction of Laravel Model database schema, columns, casts, fillable, and relations."""
    model_file = resolve_model_file(model_target, cwd)
    if not model_file or not os.path.isfile(os.path.join(cwd, model_file)):
        return {"status": "error", "message": f"Model '{model_target}' not found."}

    with open(os.path.join(cwd, model_file), "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    model_name = os.path.basename(model_file).replace(".php", "")

    t_match = re.search(r"protected\s+\$table\s*=\s*['\"]([^'\"]+)['\"]", content)
    table_name = t_match.group(1) if t_match else to_snake_case_plural(model_name)

    fillable = []
    fil_m = re.search(r"protected\s+\$fillable\s*=\s*\[(.*?)\];", content, re.DOTALL)
    if fil_m:
        fillable = re.findall(r"['\"]([a-zA-Z0-9_]+)['\"]", fil_m.group(1))

    casts = {}
    cast_m = re.search(r"protected\s+\$casts\s*=\s*\[(.*?)\];", content, re.DOTALL)
    if not cast_m:
        cast_m = re.search(r"function\s+casts\s*\(\s*\)[^{]*\{.*?return\s*\[(.*?)\];", content, re.DOTALL)
    if cast_m:
        for cm in re.finditer(r"['\"]([a-zA-Z0-9_]+)['\"]\s*=>\s*([^,\n]+)", cast_m.group(1)):
            k = cm.group(1)
            v = cm.group(2).strip().strip("'\"")
            if "::class" in v:
                v = v.split("\\")[-1].replace("::class", "")
            casts[k] = v

    rel_types = ["hasMany", "belongsTo", "hasOne", "belongsToMany", "morphTo", "morphMany", "morphOne", "hasManyThrough"]
    pattern = rf"public\s+function\s+([a-zA-Z0-9_]+)\s*\([^\)]*\)\s*(?::\s*[A-Za-z0-9_\\]+\s*)?\{{[^{{}}]*?\$this->({'|'.join(rel_types)})\s*\(\s*([A-Za-z0-9_\\]+)::class"
    raw_relations = re.findall(pattern, content, re.DOTALL)
    relations = []
    for r_name, r_type, r_target in raw_relations:
        target_clean = r_target.split("\\")[-1]
        relations.append({
            "name": r_name,
            "type": r_type,
            "target": target_clean
        })

    columns = parse_migration_columns(table_name, cwd)

    if not columns:
        prop_matches = re.findall(r"@property(?:-read)?\s+([^\s]+)\s+\$([a-zA-Z0-9_]+)", content)
        for p_type, p_name in prop_matches:
            if not p_type.startswith("Collection") and p_name not in ("created_at", "updated_at"):
                columns.append({
                    "name": p_name,
                    "type": p_type,
                    "nullable": "null" in p_type.lower()
                })

    card_lines = [
        "=" * 70,
        f"Schema: {model_name} -> '{table_name}' ({model_file})",
        "=" * 70
    ]

    card_lines.append(f"Columns ({len(columns)}):")
    for col in columns:
        details = [col["type"]]
        if col.get("nullable"):
            details.append("nullable")
        if col.get("indexed"):
            details.append("indexed")
        if col["name"] in casts:
            details.append(f"cast: {casts[col['name']]}")
        if col["name"] in fillable:
            details.append("fillable")
        card_lines.append(f"  {col['name']:<22} {', '.join(details)}")

    if relations:
        card_lines.append(f"\nRelationships ({len(relations)}):")
        for rel in relations:
            card_lines.append(f"  {rel['name']:<22} {rel['type']}({rel['target']})")

    if casts:
        card_lines.append(f"\nCasts & Enums ({len(casts)}):")
        cast_str = ", ".join(f"{k}: {v}" for k, v in list(casts.items())[:8])
        card_lines.append(f"  [{cast_str}]")

    card_lines.append("=" * 70)

    return {
        "status": "ok",
        "model": model_name,
        "table": table_name,
        "file": model_file,
        "columns_count": len(columns),
        "columns": columns,
        "relations_count": len(relations),
        "relations": relations,
        "fillable": fillable,
        "casts": casts,
        "card": "\n".join(card_lines)
    }
