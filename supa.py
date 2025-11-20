
from supabase import create_client
import json
import os

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://fuynmwpwcekkyfkiaunu.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ1eW5td3B3Y2Vra3lma2lhdW51Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MjYyODM0NiwiZXhwIjoyMDc4MjA0MzQ2fQ.J_uTfrIaMkS03OclH4o2c3UzNQNGbYGMhHd79w8MT4I")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Caminho dos JSONs locais
data_path = "./data"
files = ["users.json", "schools.json", "materials.json", "requests.json", "stock_kimonos.json"]

# Campos permitidos por tabela (evita erro por colunas inexistentes)
allowed_fields = {
    "users": ["ps_number", "password", "credential", "name"],
    "schools": ["id", "nome", "city", "coaches"],
    "materials": ["category", "subcategory", "item"],
    "requests": ["id", "school_id", "category", "material", "quantity", "date", "ps_number", "status"],
    "stock_kimonos": ["id", "school_id", "project", "type", "size", "quantity"],
}

def shape_rows(table: str, rows):
    cols = set(allowed_fields.get(table, []))
    if not cols:
        return rows
    shaped = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        o = {k: v for k, v in r.items() if k in cols}
        if table == "requests" and "quantity" in o:
            try:
                o["quantity"] = int(o["quantity"])
            except Exception:
                pass
        shaped.append(o)
    return shaped

for file_name in files:
    table_name = file_name.replace(".json", "")
    file_path = os.path.join(data_path, file_name)

    if not os.path.exists(file_path):
        print(f"⚠️  File not found: {file_path}")
        continue

    # Skip syncing if table already has any data
    try:
        existing = supabase.table(table_name).select("*").limit(1).execute()
        existing_count = len(existing.data) if isinstance(existing.data, list) else 0
        first_time_sync = (existing_count == 0)
        if existing_count > 0:
            print(f"⏭️  Skipping '{table_name}': data already exists in Supabase.")
            continue
    except Exception as e:
        print(f"⚠️  Could not check existing data for '{table_name}': {e}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"⚠️  Skipping {file_name}: invalid format (expected list)")
        continue

    shaped = shape_rows(table_name, data)
    print(f"⬆️  Upserting {file_name} → {table_name} ({len(shaped)}/{len(data)} records)")
    try:
        conflict_targets = {
            "users": "ps_number",
            "schools": "id",
            "requests": "id",
        }
        kwargs = {}
        if table_name in conflict_targets:
            kwargs["on_conflict"] = conflict_targets[table_name]
        supabase.table(table_name).upsert(shaped, **kwargs).execute()
        if first_time_sync:
            try:
                os.remove(file_path)
                print(f"🗑️  Deleted local file after first sync: {file_path}")
            except Exception as de:
                print(f"⚠️  Could not delete local file '{file_path}': {de}")
        # Mirror users into coaches when present in workspace
        if table_name == "users":
            try:
                mirrored = [
                    {"ps_number": r.get("ps_number"), "password": r.get("password"), "credential": r.get("credential", "Coach")}
                    for r in shaped if r.get("ps_number")
                ]
                if mirrored:
                    supabase.table("coaches").upsert(mirrored, on_conflict="ps_number").execute()
                    print(f"🔁 Mirrored {len(mirrored)} user(s) into coaches.")
            except Exception as me:
                print(f"Mirror to 'coaches' skipped: {me}")
        print(f"✅ Upserted into {table_name}: {len(shaped)} rows.")
    except Exception as e:
        print(f"⚠️ Error upserting {table_name}: {e}")
