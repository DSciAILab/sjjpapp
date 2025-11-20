# ============================================================
# SJJP Requests Portal - app.py
# Version: v4.0 (2025-11-09)
# Changelog:
# - Added automatic Supabase sync for all JSON datasets
# - New "Data Sync" section (admin-only)
# - Maintains all request, school, and user logic from v3.6
# ============================================================

import os
import json
import re
import uuid
import pandas as pd
import streamlit as st
from datetime import datetime
from supabase import create_client

# ------------------------------------------------------------
# 0) PAGE CONFIGURATION
# ------------------------------------------------------------
st.set_page_config(page_title="SJJP - Requests Portal", layout="wide")

# ------------------------------------------------------------
# 1) SUPABASE CONNECTION
# ------------------------------------------------------------
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.warning(f"⚠️ Could not connect to Supabase: {e}")
else:
    st.warning("⚠️ Supabase is not configured. Add SUPABASE_URL and SUPABASE_KEY to your secrets.")

# ------------------------------------------------------------
# 2) FILE PATHS & HELPERS
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")

FILES = {
    "users": os.path.join(DATA_DIR, "users.json"),
    "schools": os.path.join(DATA_DIR, "schools.json"),
    "materials": os.path.join(DATA_DIR, "materials.json"),
    "requests": os.path.join(DATA_DIR, "requests.json"),
    "stock": os.path.join(DATA_DIR, "stock_kimonos.json"),
}

os.makedirs(DATA_DIR, exist_ok=True)
UNSYNCED_REQUEST_SESSION_KEY = "unsynced_request_ids"


def ensure_json(path: str, default_content):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_content, f, ensure_ascii=False, indent=2)


def load_json(path: str):
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Unified status helpers
def notify(kind: str, message: str):
    icons = {
        "success": "✅ ",
        "info": "ℹ️ ",
        "warning": "⚠️ ",
        "error": "❌ ",
    }
    prefix = icons.get(kind, "")
    if kind == "success":
        st.success(prefix + message)
    elif kind == "info":
        st.info(prefix + message)
    elif kind == "warning":
        st.warning(prefix + message)
    else:
        st.error(prefix + message)


def show_summary(action: str, **metrics):
    # Build compact one-line summary only with provided metrics
    parts = []
    labels = {
        "saved": "saved",
        "synced": "synced",
        "deleted": "deleted",
        "updated": "updated",
        "mirrored": "mirrored",
        "skipped": "skipped",
        "errors": "errors",
    }
    for k, v in metrics.items():
        if v is None:
            continue
        if k in labels:
            parts.append(f"{labels[k]}: {v}")
    msg = f"{action} — " + ", ".join(parts) if parts else action
    st.info("📋 " + msg)


# Bootstrap defaults
ensure_json(FILES["users"], [
    {"ps_number": "PS1724", "password": "PS1724", "credential": "Admin", "name": "Administrator"}
])
ensure_json(FILES["schools"], [])
ensure_json(FILES["materials"], [])
ensure_json(FILES["requests"], [])
ensure_json(FILES["stock"], [])


# Migration: merge data/coaches.json into users.json (one-off)
def migrate_coaches_into_users():
    coaches_path = os.path.join(DATA_DIR, "coaches.json")
    if not os.path.exists(coaches_path):
        return
    try:
        users = load_json(FILES["users"]) or []
        coaches = load_json(coaches_path) or []
        by_ps = {str(u.get("ps_number", "")).strip(): {
            "ps_number": str(u.get("ps_number", "")).strip(),
            "password": str(u.get("password", "")),
            "credential": u.get("credential", "Coach") or "Coach",
            "name": str(u.get("name", "")),
        } for u in users if str(u.get("ps_number", "")).strip()}

        for c in coaches:
            ps = str(c.get("ps_number", "")).strip()
            if not ps:
                continue
            curr = by_ps.get(ps, {})
            merged = {
                "ps_number": ps,
                "password": curr.get("password") or str(c.get("password", ps)),
                "credential": curr.get("credential") or c.get("credential", "Coach") or "Coach",
                "name": curr.get("name") or str(c.get("name", "")),
            }
            by_ps[ps] = merged

        merged_list = list(by_ps.values())
        save_json(FILES["users"], merged_list)
        # remove coaches.json after successful merge
        try:
            os.remove(coaches_path)
        except Exception:
            pass
    except Exception:
        # best-effort migration; ignore on failure
        pass


migrate_coaches_into_users()


# ------------------------------------------------------------
# 3) AUTHENTICATION
# ------------------------------------------------------------
def authenticate(ps_number: str, password: str):
    users = load_json(FILES["users"]) or []
    for u in users:
        if u.get("ps_number") == ps_number and str(u.get("password", "")) == password:
            return {"ps_number": u["ps_number"], "credential": u.get("credential", "Coach"), "name": u.get("name", u["ps_number"])}
    return None


def require_login():
    if st.session_state.get("user"):
        return st.session_state["user"]

    st.header("Login")
    with st.form("login_form", clear_on_submit=False):
        ps = st.text_input("PS Number", placeholder="PS1234")
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In")
    if submitted:
        user = authenticate(ps.strip(), pw.strip())
        if user:
            st.session_state["user"] = user
            st.success("Signed in successfully.")
            st.rerun()
        else:
            st.error("Invalid PS Number or password.")
    st.stop()


# ------------------------------------------------------------
# 4) HELPERS
# ------------------------------------------------------------
def ensure_request_id_and_defaults(rows):
    changed = False
    for r in rows:
        if "id" not in r:
            r["id"] = str(uuid.uuid4())
            changed = True
        if "status" not in r:
            r["status"] = "Pending"
            changed = True
        if "ps_number" not in r:
            r["ps_number"] = "unknown"
            changed = True
    if changed:
        save_json(FILES["requests"], rows)
    return rows


def ensure_stock_id_and_defaults(rows):
    """Ensure each stock row has an `id` and a numeric `quantity`.

    Expected stock row schema:
      {"id": "<uuid>", "school_id": "1565", "project": "MOE|ESE", "type": "KIMONO TYPE", "size": "C0|C1|...", "quantity": 10}
    """
    changed = False
    for r in rows:
        if "id" not in r:
            r["id"] = str(uuid.uuid4())
            changed = True
        # quantity must be int
        if "quantity" not in r:
            r["quantity"] = 0
            changed = True
        else:
            try:
                r["quantity"] = int(r["quantity"])
            except Exception:
                r["quantity"] = 0
                changed = True
        # normalize project label
        if "project" in r and isinstance(r["project"], str):
            r["project"] = r["project"].strip().upper()
    if changed:
        save_json(FILES["stock"], rows)
    return rows


def list_user_schools(user, schools):
    if user["credential"] == "Admin":
        return schools
    ps = user["ps_number"]
    return [s for s in schools if ps in s.get("coaches", [])]


def materials_by_category(materials, category):
    return [m for m in materials if m.get("category") == category]


def load_requests_data():
    """Load requests preferring Supabase; fallback to local JSON."""
    rows = []
    source = "local"
    error = None
    if supabase:
        try:
            data = supabase.table("requests").select("*").range(0, 100000).execute()
            rows = data.data or []
            source = "supabase"
            # keep local cache aligned when possible
            save_json(FILES["requests"], rows)
        except Exception as exc:
            error = exc
    if not rows:
        rows = load_json(FILES["requests"]) or []
        source = "local"
    rows = ensure_request_id_and_defaults(rows)
    return rows, source, error


def persist_requests(records):
    """Persist request records locally and sync with Supabase when available."""
    if not records:
        return {"saved": 0, "synced": 0, "error": None}

    existing = load_json(FILES["requests"]) or []
    by_id = {}
    for row in existing:
        rid = str(row.get("id", "")).strip()
        if rid:
            by_id[rid] = row

    payload = []
    saved = 0
    for rec in records:
        item = dict(rec) if isinstance(rec, dict) else {}
        rid = str(item.get("id") or "").strip() or str(uuid.uuid4())
        item["id"] = rid
        item.setdefault("status", "Pending")
        item.setdefault("ps_number", "unknown")
        # Normalize quantity to int when possible
        if "quantity" in item:
            try:
                item["quantity"] = int(item["quantity"])
            except Exception:
                pass
        by_id[rid] = item
        payload.append({
            "id": item.get("id"),
            "school_id": item.get("school_id"),
            "category": item.get("category"),
            "material": item.get("material"),
            "quantity": item.get("quantity"),
            "date": item.get("date"),
            "ps_number": item.get("ps_number"),
            "status": item.get("status"),
        })
        saved += 1

    save_json(FILES["requests"], list(by_id.values()))

    synced = 0
    error = None
    if supabase and payload:
        try:
            supabase.table("requests").upsert(payload, on_conflict="id").execute()
            synced = len(payload)
        except Exception as exc:
            error = exc

    return {"saved": saved, "synced": synced, "error": error}


# ------------------------------------------------------------
# 5) SUPABASE SYNC
# ------------------------------------------------------------
def sync_local_to_supabase(force: bool = False, replace: bool = False):
    if not supabase:
        st.error("Supabase is not configured.")
        return

    # Local file → logical source name
    TABLES = {
        "users": "users.json",
        "schools": "schools.json",
        "materials": "materials.json",
        "requests": "requests.json",
        "stock_kimonos": "stock_kimonos.json",
    }

    st.subheader("Data Synchronization Log")
    # Define allowed fields per table to avoid schema mismatches
    allowed_fields = {
        "users": ["ps_number", "password", "credential", "name"],
        "schools": ["id", "nome", "city", "coaches"],
        "materials": ["category", "subcategory", "item"],
        "requests": ["id", "school_id", "category", "material", "quantity", "date", "ps_number", "status"],
        "stock_kimonos": ["id", "school_id", "project", "type", "size", "quantity"],
    }
    conflict_targets = {
        "users": "ps_number",
        "schools": "id",
        "requests": "id",
        "stock_kimonos": "id",
        # materials has no unique constraint; avoid on_conflict
    }
    # No special table mapping needed now (coaches.json removed)

    total_synced = 0
    total_skipped = 0
    total_errors = 0

    for table, filename in TABLES.items():
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            st.warning(f"{filename} not found.")
            continue

        # 1) Check if the remote table already has data; if so, skip
        try:
            target_table = table
            existing = supabase.table(table).select("*").limit(1).execute()
            existing_count = len(existing.data) if isinstance(existing.data, list) else 0
            first_time_sync = (existing_count == 0 and not force and not replace)
            if not force and existing_count > 0:
                notify("info", f"Skipped '{table}': data already exists in Supabase.")
                total_skipped += 1
                continue
        except Exception as e:
            notify("warning", f"Could not check existing data for '{table}': {e}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            st.warning(f"Skipping {table}: invalid format.")
            continue

        # Shape data to match table schema (drop unexpected fields)
        shaped = data
        if table in allowed_fields:
            cols = set(allowed_fields[table])
            shaped = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                shaped_row = {k: v for k, v in row.items() if k in cols}
                # Minimal defaults/cleanup
                if table == "coaches":
                    # Ensure required key exists and provide fallback name
                    if "ps_number" not in shaped_row:
                        continue
                    shaped_row.setdefault("name", "")
                if table == "requests" and "quantity" in shaped_row:
                    try:
                        shaped_row["quantity"] = int(shaped_row["quantity"])
                    except Exception:
                        pass
                shaped.append(shaped_row)

        try:
            # Optionally replace remote with local (truncate-like)
            if replace:
                try:
                    key = {
                        "users": "ps_number",
                        "schools": "id",
                        "materials": "category",
                        "requests": "id",
                    }.get(table)
                    if key:
                        # delete all rows by filtering non-empty keys
                        supabase.table(table).delete().neq(key, "").execute()
                        notify("info", f"Cleared remote '{table}' before sync.")
                except Exception as de:
                    notify("warning", f"Could not clear remote '{table}': {de}")

            kwargs = {}
            if table in conflict_targets:
                kwargs["on_conflict"] = conflict_targets[table]
            response = supabase.table(table).upsert(shaped, **kwargs).execute()
            notify("success", f"Synced {len(shaped)} records to '{table}'")
            total_synced += 1

            # Optionally remove local JSON after first successful sync
            if first_time_sync:
                try:
                    os.remove(path)
                    notify("info", f"Deleted local file after first sync: {filename}")
                except Exception as de:
                    notify("warning", f"Could not delete local file '{filename}': {de}")

            # If syncing users, also mirror into 'coaches' table schema (ps_number, password, credential)
            if table == "users":
                try:
                    mirrored = [
                        {"ps_number": r.get("ps_number"), "password": r.get("password"), "credential": r.get("credential", "Coach")}
                        for r in shaped if r.get("ps_number")
                    ]
                    if mirrored:
                        supabase.table("coaches").upsert(mirrored, on_conflict="ps_number").execute()
                        notify("info", f"Mirrored {len(mirrored)} user(s) into 'coaches'.")
                except Exception as e:
                    notify("warning", f"Mirror to 'coaches' skipped: {e}")
        except Exception as e:
            notify("error", f"Could not sync {table}: {e}")
            total_errors += 1

    show_summary("Data Sync", synced=total_synced, skipped=total_skipped, errors=total_errors)


def pull_supabase_to_local():
    if not supabase:
        notify("error", "Supabase is not configured.")
        return

    # Tables to pull and target files
    TABLES = {
        "users": FILES["users"],
        "schools": FILES["schools"],
        "materials": FILES["materials"],
        "requests": FILES["requests"],
        "stock_kimonos": FILES["stock"],
    }

    allowed_fields = {
        "users": ["ps_number", "password", "credential", "name"],
        "schools": ["id", "nome", "city", "coaches"],
        "materials": ["category", "subcategory", "item"],
        "requests": ["id", "school_id", "category", "material", "quantity", "date", "ps_number", "status"],
        "stock_kimonos": ["id", "school_id", "project", "type", "size", "quantity"],
    }

    pulled = 0
    errors = 0
    for table, path in TABLES.items():
        try:
            # Pull up to 100k rows
            data = supabase.table(table).select("*").range(0, 100000).execute()
            rows = data.data or []
            # Shape rows to allowed fields only
            cols = set(allowed_fields.get(table, []))
            shaped = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                shaped.append({k: r.get(k) for k in cols})
            save_json(path, shaped)
            notify("success", f"Pulled {len(shaped)} rows from '{table}' to local JSON.")
            pulled += 1
        except Exception as e:
            notify("error", f"Could not pull '{table}': {e}")
            errors += 1
    show_summary("Pull Supabase → Local", saved=pulled, errors=errors)


# ------------------------------------------------------------
# 6) APP BODY
# ------------------------------------------------------------
user = require_login()

try:
    options = ["Submit Request", "Manage Requests", "Admin Schools"]
    if user["credential"] == "Admin":
        options += ["Admin Users", "Data Sync"]
    options.append("Kimono Stock")
    menu_selected = st.segmented_control(
        "Select a section:", options
    )
except Exception:
    options = ["Submit Request", "Manage Requests", "Admin Schools"]
    if user["credential"] == "Admin":
        options += ["Admin Users", "Data Sync"]
    options.append("Kimono Stock")
    menu_selected = st.radio("Select a section:", options, horizontal=True)

st.divider()

# ----------------------------
# Submit Request
# ----------------------------
if menu_selected == "Submit Request":
    st.header("Submit Request")

    schools = load_json(FILES["schools"])
    materials = load_json(FILES["materials"])

    visible_schools = list_user_schools(user, schools)
    school_label_map = [f"{s.get('nome','(no name)')} ({s.get('id','')})" for s in visible_schools]
    school_choice = st.selectbox("School", school_label_map) if visible_schools else None
    selected_school_id = None
    if school_choice:
        selected_school_id = school_choice.split("(")[-1].replace(")", "").strip()

    categories = sorted(set(m.get("category", "") for m in materials)) if materials else []
    category = st.selectbox("Category", categories) if categories else None
    filtered = materials_by_category(materials, category) if category else []
    sub_item_options = [f"{m.get('subcategory','')} {m.get('item','')}".strip() for m in filtered]
    material_choice = st.selectbox("Subcategory + Item", sub_item_options) if filtered else None
    qty = st.number_input("Quantity", min_value=1, value=1, step=1)

    if "pending_request" not in st.session_state:
        st.session_state["pending_request"] = []

    if st.button("Add Another Item", disabled=not (selected_school_id and material_choice)):
        new_item = {
            "id": str(uuid.uuid4()),
            "school_id": selected_school_id,
            "category": category,
            "material": material_choice,
            "quantity": int(qty),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ps_number": str(user["ps_number"]),
            "status": "Pending"
        }
        st.session_state["pending_request"].append(new_item)
        result = persist_requests([new_item])
        if UNSYNCED_REQUEST_SESSION_KEY not in st.session_state:
            st.session_state[UNSYNCED_REQUEST_SESSION_KEY] = set()
        if result["error"]:
            st.session_state[UNSYNCED_REQUEST_SESSION_KEY].add(new_item["id"])
            notify("warning", f"Item salvo localmente, mas não sincronizado com Supabase: {result['error']}")
        else:
            if new_item["id"] in st.session_state[UNSYNCED_REQUEST_SESSION_KEY]:
                st.session_state[UNSYNCED_REQUEST_SESSION_KEY].discard(new_item["id"])
            notify("success", "Item salvo e sincronizado com sucesso.")

    if st.session_state["pending_request"]:
        st.subheader("Current Batch")
        batch_df = pd.DataFrame(st.session_state["pending_request"]).drop(columns=["id"], errors="ignore")
        st.dataframe(batch_df, use_container_width=True)

        if st.button("Submit Request", type="primary"):
            # Validate items before persisting
            valid_school_ids = set(str(s.get("id")) for s in schools)
            errors = []
            for it in st.session_state["pending_request"]:
                sid = str(it.get("school_id", "")).strip()
                qty = it.get("quantity", 0)
                if not sid or sid not in valid_school_ids:
                    errors.append(f"Invalid school_id: {sid}")
                try:
                    if int(qty) <= 0:
                        errors.append(f"Invalid quantity for school {sid}: {qty}")
                except Exception:
                    errors.append(f"Non-numeric quantity for school {sid}: {qty}")

            if errors:
                notify("error", "Cannot submit: invalid items detected.")
                notify("warning", "; ".join(errors))
                show_summary("Submit Request", saved=0, synced=0, errors=len(errors))
                st.stop()

            result = persist_requests(st.session_state["pending_request"])
            if UNSYNCED_REQUEST_SESSION_KEY not in st.session_state:
                st.session_state[UNSYNCED_REQUEST_SESSION_KEY] = set()
            batch_ids = {str(item.get("id")) for item in st.session_state["pending_request"] if item.get("id")}
            if result["error"]:
                st.session_state[UNSYNCED_REQUEST_SESSION_KEY].update(batch_ids)
                notify("warning", f"As requisições foram salvas localmente, mas não sincronizaram com Supabase: {result['error']}")
            else:
                st.session_state[UNSYNCED_REQUEST_SESSION_KEY].difference_update(batch_ids)
                notify("success", "Requisições salvas e sincronizadas com sucesso.")
            show_summary(
                "Submit Request",
                saved=result["saved"],
                synced=result["synced"],
                errors=1 if result["error"] else 0
            )
            st.session_state["pending_request"] = []
            st.rerun()

# ----------------------------
# Manage Requests
# ----------------------------
elif menu_selected == "Manage Requests":
    st.header("Manage Requests")
    st.info("Only 'Pending' requests can be edited or deleted.")

    rows, data_source, load_error = load_requests_data()
    if load_error:
        notify("warning", f"Dados locais carregados. Erro ao consultar Supabase: {load_error}")
    elif data_source == "local" and supabase:
        st.caption("Dados carregados do arquivo local. Clique em Data Sync → Pull se quiser alinhar com o Supabase.")
    is_admin = user.get("credential") == "Admin"

    requester_lookup = {}
    if is_admin:
        try:
            users_rows = load_json(FILES["users"]) or []
            requester_lookup = {
                str(u.get("ps_number", "")).strip(): (u.get("name") or str(u.get("ps_number", "")).strip())
                for u in users_rows
                if str(u.get("ps_number", "")).strip()
            }
        except Exception:
            requester_lookup = {}
    def add_requester_columns(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if "ps_number" not in df.columns:
            df["PS Number"] = ""
            df["Requester"] = ""
            return df
        ps_series = df["ps_number"].apply(lambda x: str(x).strip() if pd.notnull(x) else "")
        df["PS Number"] = ps_series
        df["Requester"] = ps_series.map(lambda x: requester_lookup.get(x, "") if x else "")
        df["Requester"] = df["Requester"].fillna("")
        df.loc[df["Requester"].astype(str).str.strip() == "", "Requester"] = ps_series
        df = df.drop(columns=["ps_number"], errors="ignore")
        return df

    # Visibility:
    # - Admin sees all requests
    # - Coaches see all requests for their schools (even if created by another coach)
    if is_admin:
        visible = rows
    else:
        all_schools = load_json(FILES["schools"]) or []
        my_schools = list_user_schools(user, all_schools)
        my_school_ids = {str(s.get("id")) for s in my_schools if s.get("id")}
        visible = [r for r in rows if str(r.get("school_id", "")) in my_school_ids]

    # Optional school filter UI
    school_map = {str(s.get("id")): s.get("nome", "") for s in (load_json(FILES["schools"]) or []) if s.get("id")}

    if is_admin and rows:
        export_df = pd.DataFrame(rows)
        if not export_df.empty:
            export_df = export_df.copy()
            school_series = export_df["school_id"].astype(str) if "school_id" in export_df.columns else pd.Series([""] * len(export_df), index=export_df.index)
            ps_series = export_df["ps_number"].astype(str) if "ps_number" in export_df.columns else pd.Series([""] * len(export_df), index=export_df.index)
            def _clean_optional(value):
                if value is None:
                    return ""
                text = str(value).strip()
                return "" if not text or text.lower() == "nan" else text
            school_values = school_series.apply(_clean_optional)
            export_df["school_name"] = school_values.map(lambda x: school_map.get(x, x) if x else "")
            ps_values = ps_series.apply(_clean_optional)
            export_df["requester_name"] = ps_values.map(lambda x: requester_lookup.get(x, "") if x else "")
            preferred_cols = ["id", "school_id", "school_name", "category", "material", "quantity", "status", "date", "ps_number", "requester_name"]
            ordered_cols = [c for c in preferred_cols if c in export_df.columns] + [c for c in export_df.columns if c not in preferred_cols]
            export_df = export_df[ordered_cols]
            export_bytes = export_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Export All Requests (CSV)",
                export_bytes,
                file_name=f"requests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    visible_school_ids = sorted({str(r.get("school_id", "")) for r in visible if r.get("school_id")})
    if visible_school_ids:
        options = ["All schools"] + [f"{school_map.get(sid, '(unknown)')} ({sid})" for sid in visible_school_ids]
        selected_opt = st.selectbox("Filter by school", options)
        if selected_opt and selected_opt != "All schools":
            sel_id = selected_opt.split("(")[-1].replace(")", "").strip()
            visible = [r for r in visible if str(r.get("school_id", "")) == sel_id]

    if not visible:
        st.info("No requests found.")
    else:
        pending = [r for r in visible if str(r.get("status", "")).lower() == "pending"]
        finalized = [r for r in visible if str(r.get("status", "")).lower() != "pending"]

        # Pending (editable)
        st.subheader("Pending Requests (Editable)")
        if pending:
            dfp = pd.DataFrame(pending).drop(columns=["id"], errors="ignore")
            if is_admin:
                dfp = add_requester_columns(dfp)
            else:
                dfp = dfp.drop(columns=["ps_number"], errors="ignore")
            # Replace school_id with human-friendly School name
            try:
                dfp["School"] = dfp.get("school_id", "").astype(str).map(lambda x: school_map.get(x, x))
            except Exception:
                dfp["School"] = dfp.get("school_id", "")
            if "school_id" in dfp.columns:
                dfp = dfp.drop(columns=["school_id"], errors="ignore")
            # Allow everyone to mark Delete on their pending rows
            if is_admin:
                dfp["Select"] = False
            dfp["Delete"] = False
            preferred = ["School", "category", "material", "quantity", "status", "date"]
            if is_admin:
                preferred = ["School", "Requester", "PS Number", "category", "material", "quantity", "status", "date"]
            first_cols = []
            if is_admin:
                first_cols.append("Select")
            first_cols.append("Delete")
            ordered = [c for c in first_cols + preferred if c in dfp.columns] + [c for c in dfp.columns if c not in set(first_cols + preferred)]
            dfp = dfp[ordered]

            # Configure column behavior by role
            col_config = {
                "School": st.column_config.TextColumn("School"),
                "category": st.column_config.TextColumn("Category"),
                "material": st.column_config.TextColumn("Item"),
                "quantity": st.column_config.NumberColumn("Qty", min_value=1, step=1),
                # Admin pode alterar status; Coaches apenas visualizam
                "status": (
                    st.column_config.SelectboxColumn("Status", options=["Pending","Processed", "Approved", "Rejected"], default="Pending")
                    if is_admin else st.column_config.TextColumn("Status")
                ),
                # Data exibida mas tratada como somente-leitura ao salvar (mudanças são ignoradas)
                "date": st.column_config.TextColumn("Date"),
                "Delete": st.column_config.CheckboxColumn("Delete"),
            }
            if is_admin:
                col_config["Select"] = st.column_config.CheckboxColumn("Select")
                col_config["Requester"] = st.column_config.TextColumn("Requested By")
                col_config["PS Number"] = st.column_config.TextColumn("PS Number")
            if not is_admin:
                st.caption("Note: School and Date are read-only; Only Admin can change Status. Edits on these are ignored on save.")
            else:
                st.caption("Note: School and Date are read-only; edits are ignored on save.")

            edited_df = st.data_editor(dfp, use_container_width=True, hide_index=True, num_rows="fixed", column_config=col_config)

            if is_admin and not edited_df.empty:
                status_options = ["Pending", "Approved", "Rejected"]
                default_index = 1 if len(status_options) > 1 else 0
                new_status = st.selectbox(
                    "New status for selected requests",
                    status_options,
                    index=default_index,
                    key="batch_status_select"
                )
                selected_indices = []
                if "Select" in edited_df.columns:
                    try:
                        selected_series = edited_df["Select"].astype(bool)
                        selected_indices = selected_series[selected_series].index.tolist()
                    except Exception:
                        selected_indices = []
                apply_disabled = len(selected_indices) == 0
                if st.button(
                    "Update Status for Selected Requests",
                    type="primary",
                    disabled=apply_disabled,
                    key="batch_status_update_btn"
                ):
                    if not selected_indices:
                        notify("info", "Select at least one request to update.")
                    else:
                        by_id = {r.get("id"): r for r in rows if r.get("id")}
                        updated_ids = []
                        for idx in selected_indices:
                            if 0 <= idx < len(pending):
                                rid = pending[idx].get("id")
                                if rid and rid in by_id:
                                    by_id[rid]["status"] = new_status
                                    updated_ids.append(rid)
                        if not updated_ids:
                            notify("info", "No valid requests selected for batch update.")
                        else:
                            updated_rows = []
                            for r in rows:
                                rid = r.get("id")
                                if rid in by_id:
                                    updated_rows.append(by_id[rid])
                                else:
                                    updated_rows.append(r)
                            save_json(FILES["requests"], updated_rows)
                            synced_count = 0
                            if supabase:
                                try:
                                    allowed = {"id", "school_id", "category", "material", "quantity", "date", "ps_number", "status"}
                                    payload = []
                                    for rid in updated_ids:
                                        record = by_id.get(rid)
                                        if not record:
                                            continue
                                        shaped = {k: record.get(k) for k in allowed}
                                        if "quantity" in shaped and shaped["quantity"] is not None:
                                            try:
                                                shaped["quantity"] = int(shaped["quantity"])
                                            except Exception:
                                                pass
                                        payload.append(shaped)
                                    if payload:
                                        supabase.table("requests").upsert(payload, on_conflict="id").execute()
                                        synced_count = len(payload)
                                except Exception as e:
                                    notify("warning", f"Updated locally, but could not sync to Supabase: {e}")
                            notify("success", f"Updated status to '{new_status}' for {len(updated_ids)} request(s).")
                            show_summary("Manage Requests — Batch Status", updated=len(updated_ids), synced=synced_count)
                            st.session_state.pop("confirm_delete_requests", None)
                            st.rerun()
        else:
            edited_df = pd.DataFrame()
            st.info("No pending requests.")

        # Finalized (read-only)
        if finalized:
            st.subheader("Non-Pending Requests (Read-only)")
            dff = pd.DataFrame(finalized).drop(columns=["id"], errors="ignore")
            if is_admin:
                dff = add_requester_columns(dff)
            else:
                dff = dff.drop(columns=["ps_number"], errors="ignore")
            # Map school_id to School name for display
            try:
                dff["School"] = dff.get("school_id", "").astype(str).map(lambda x: school_map.get(x, x))
            except Exception:
                dff["School"] = dff.get("school_id", "")
            dff = dff.drop(columns=["school_id"], errors="ignore")
            dff = dff.rename(columns={
                "category": "Category",
                "material": "Item",
                "quantity": "Qty",
                "status": "Status",
                "date": "Date",
            })
            preferred_final = ["School", "Category", "Item", "Qty", "Status", "Date"]
            if is_admin:
                preferred_final = ["School", "Requester", "PS Number", "Category", "Item", "Qty", "Status", "Date"]
            ordered_final = [c for c in preferred_final if c in dff.columns] + [c for c in dff.columns if c not in set(preferred_final)]
            dff = dff[ordered_final]
            st.dataframe(dff, use_container_width=True)

        # Stage deletion with confirmation
        if st.button("Delete Selected Items"):
            to_delete_indices = edited_df.index[edited_df["Delete"] == True].tolist() if not edited_df.empty else []
            to_delete_ids = [pending[i]["id"] for i in to_delete_indices]
            if not to_delete_ids:
                notify("info", "No rows selected for deletion.")
            else:
                st.session_state["confirm_delete_requests"] = to_delete_ids
                notify("warning", f"Review and confirm deletion of {len(to_delete_ids)} request(s) below.")

        # Confirmation UI (persists across reruns via session_state)
        confirm_ids = st.session_state.get("confirm_delete_requests")
        if confirm_ids:
            with st.container(border=True):
                st.warning(f"Confirm deletion of {len(confirm_ids)} request(s)? This cannot be undone.")
                # Preview first 10 selected requests
                try:
                    current_rows, _, _ = load_requests_data()
                    idset = set(confirm_ids)
                    selected = [r for r in current_rows if r.get("id") in idset]
                except Exception:
                    selected = []
                if selected:
                    prev_df = pd.DataFrame([
                        {
                            "School": r.get("school_id", ""),
                            "Item": r.get("material", ""),
                            "Qty": r.get("quantity", ""),
                            "Date": r.get("date", ""),
                        }
                        for r in selected[:10]
                    ])
                    st.dataframe(prev_df, use_container_width=True)
                    if len(selected) > 10:
                        st.caption(f"…and {len(selected) - 10} more")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Confirm Delete", key="confirm_delete_requests_btn"):
                        # Reload latest rows and apply deletion
                        current_rows, _, _ = load_requests_data()
                        kept = [r for r in current_rows if r.get("id") not in set(confirm_ids)]
                        save_json(FILES["requests"], kept)
                        if supabase and confirm_ids:
                            try:
                                supabase.table("requests").delete().in_("id", confirm_ids).execute()
                            except Exception as e:
                                notify("warning", f"Could not delete from Supabase: {e}")
                        notify("success", f"Deleted {len(confirm_ids)} requests.")
                        show_summary("Manage Requests — Delete", deleted=len(confirm_ids))
                        st.session_state.pop("confirm_delete_requests", None)
                        st.rerun()
                with c2:
                    if st.button("Cancel", key="cancel_delete_requests_btn"):
                        st.session_state.pop("confirm_delete_requests", None)
                        notify("info", "Deletion canceled.")

        if st.button("Save Changes", type="primary"):
            by_id = {r["id"]: r for r in rows}
            updated_ids = set()
            for idx, er in (edited_df.iterrows() if not edited_df.empty else []):
                rid = pending[idx]["id"]
                if rid in by_id:
                    # Não permitir edição de 'date' (mantém valor original)
                    # Apenas Admin pode alterar 'status'
                    keys = ["school_id", "category", "material", "quantity"]
                    if user.get("credential") == "Admin":
                        keys.append("status")
                    for k in keys:
                        if k in er:
                            by_id[rid][k] = er[k]
                    updated_ids.add(rid)
            save_json(FILES["requests"], list(by_id.values()))
            # Sync updates to Supabase
            if supabase and updated_ids:
                try:
                    allowed = {"id", "school_id", "category", "material", "quantity", "date", "ps_number", "status"}
                    payload = []
                    for rid in updated_ids:
                        r = by_id[rid]
                        shaped = {k: v for k, v in r.items() if k in allowed}
                        if "quantity" in shaped:
                            try:
                                shaped["quantity"] = int(shaped["quantity"])
                            except Exception:
                                pass
                        payload.append(shaped)
                    if payload:
                        supabase.table("requests").upsert(payload, on_conflict="id").execute()
                except Exception as e:
                    notify("warning", f"Saved locally, but could not sync to Supabase: {e}")
            notify("success", "Changes saved successfully.")
            show_summary("Manage Requests — Save", updated=len(updated_ids), synced=len(updated_ids))
            st.rerun()

# ----------------------------
# Admin Schools
# ----------------------------
elif menu_selected == "Admin Schools":
    if user["credential"] != "Admin":
        st.warning("You do not have permission to access this section.")
        st.stop()

    st.header("Admin Schools")
    st.info("Edite as escolas abaixo e confirme clicando em 'Save Changes'. Nenhuma alteração é salva sem confirmar.")

    schools = load_json(FILES["schools"]) or []
    df = pd.DataFrame(schools) if schools else pd.DataFrame(columns=["id", "nome", "city", "coaches"])
    # Converter coluna 'coaches' para string (comma-separated) para edição amigável
    df_edit = df.copy()
    if "coaches" in df_edit.columns:
        df_edit["coaches"] = df_edit["coaches"].apply(lambda v: ",".join(v) if isinstance(v, list) else (v or ""))

    # Adiciona coluna de seleção para deleção
    df_edit["Delete"] = False
    # Ordena para colocar Delete primeiro
    preferred = ["id", "nome", "city", "coaches"]
    ordered = [c for c in ["Delete"] + preferred if c in df_edit.columns] + [c for c in df_edit.columns if c not in set(["Delete"] + preferred)]
    df_edit = df_edit[ordered]

    # Renomeia rótulos e adiciona dicas
    school_col_config = {
        "id": st.column_config.TextColumn("ID"),
        "nome": st.column_config.TextColumn("School Name"),
        "city": st.column_config.TextColumn("City"),
        "coaches": st.column_config.TextColumn("Coaches (comma-separated PS numbers)"),
        "Delete": st.column_config.CheckboxColumn("Delete"),
    }
    edited_df = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True, column_config=school_col_config)

    # Botão para excluir escolas selecionadas com confirmação
    if st.button("Delete Selected Schools"):
        to_delete = edited_df[edited_df.get("Delete", False) == True] if not edited_df.empty else pd.DataFrame()
        ids = [str(x).strip() for x in (to_delete.get("id", []) if not to_delete.empty else []) if str(x).strip()]
        if not ids:
            notify("info", "No schools selected for deletion.")
        else:
            st.session_state["confirm_delete_schools"] = ids
            notify("warning", f"Review and confirm deletion of {len(ids)} school(s) below.")

    confirm_schools = st.session_state.get("confirm_delete_schools")
    if confirm_schools:
        with st.container(border=True):
            st.warning(f"Confirm deletion of {len(confirm_schools)} school(s)? This cannot be undone.")
            # Preview até 10 escolas
            try:
                current = load_json(FILES["schools"]) or []
                idset = set(confirm_schools)
                selected = [r for r in current if str(r.get("id", "")).strip() in idset]
            except Exception:
                selected = []
            if selected:
                prev_df = pd.DataFrame([
                    {
                        "ID": r.get("id", ""),
                        "School Name": r.get("nome", ""),
                        "City": r.get("city", ""),
                        "Coaches": ",".join(r.get("coaches", [])) if isinstance(r.get("coaches"), list) else (r.get("coaches", "") or ""),
                    }
                    for r in selected[:10]
                ])
                st.dataframe(prev_df, use_container_width=True)
                if len(selected) > 10:
                    st.caption(f"…and {len(selected) - 10} more")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirm Delete", key="confirm_delete_schools_btn"):
                    current = load_json(FILES["schools"]) or []
                    kept = [r for r in current if str(r.get("id", "")).strip() not in set(confirm_schools)]
                    save_json(FILES["schools"], kept)
                    if supabase and confirm_schools:
                        try:
                            supabase.table("schools").delete().in_("id", confirm_schools).execute()
                        except Exception as e:
                            notify("warning", f"Could not delete from Supabase: {e}")
                    notify("success", f"Deleted {len(confirm_schools)} school(s).")
                    show_summary("Admin Schools — Delete", deleted=len(confirm_schools))
                    st.session_state.pop("confirm_delete_schools", None)
                    st.rerun()
            with c2:
                if st.button("Cancel", key="cancel_delete_schools_btn"):
                    st.session_state.pop("confirm_delete_schools", None)
                    notify("info", "School deletion canceled.")

    if st.button("Save Changes", type="primary"):
        # Normalize dataframe into records
        records = edited_df.fillna("").to_dict(orient="records")

        # Validate and convert
        invalid_id_rows = []
        warnings = []
        for idx, r in enumerate(records):
            # Ensure 'coaches' is a list from comma-separated string
            if isinstance(r.get("coaches"), str):
                coaches_list = [x.strip() for x in r["coaches"].split(",") if x.strip()]
                r["coaches"] = coaches_list
            elif isinstance(r.get("coaches"), list):
                r["coaches"] = [str(x).strip() for x in r["coaches"] if str(x).strip()]
            else:
                r["coaches"] = []

            # Block if missing ID
            sid = str(r.get("id", "")).strip()
            if not sid:
                invalid_id_rows.append(idx + 1)  # 1-based row index for UX
                continue

            # Validate PS numbers; normalize to uppercase and drop invalids
            raw_list = r.get("coaches", [])
            valid, invalid = [], []
            for ps in raw_list:
                ps_up = str(ps).strip().upper()
                if re.match(r"^PS\d+$", ps_up):
                    valid.append(ps_up)
                else:
                    invalid.append(ps)
            r["coaches"] = valid
            if invalid:
                warnings.append(f"School {sid}: removed invalid PS numbers {invalid}")

        # If any row missing ID, abort save and show error
        if invalid_id_rows:
            notify("error", f"Cannot save: rows missing ID → {invalid_id_rows}")
            show_summary("Admin Schools — Save", saved=0, errors=len(invalid_id_rows))
            st.stop()

        # Save locally after validation
        save_json(FILES["schools"], records)

        # Best-effort sync to Supabase with status message
        synced = 0
        if supabase and records:
            try:
                payload = []
                for r in records:
                    shaped = {k: r.get(k) for k in ["id", "nome", "city", "coaches"]}
                    payload.append(shaped)
                if payload:
                    supabase.table("schools").upsert(payload, on_conflict="id").execute()
                    synced = len(payload)
            except Exception as e:
                notify("warning", f"Saved locally, but could not sync to Supabase: {e}")

        # Surface PS warnings if any
        if warnings:
            notify("warning", "; ".join(warnings))

        notify("success", "Schools updated successfully.")
        show_summary("Admin Schools — Save", saved=len(records), synced=synced)
        st.rerun()

# ----------------------------
# Admin Users
# ----------------------------
elif menu_selected == "Admin Users":
    if user["credential"] != "Admin":
        st.warning("You do not have permission to access this section.")
        st.stop()

    st.header("Admin Users")

    users_rows = load_json(FILES["users"]) or []

    # Ensure columns
    df_cols = ["ps_number", "password", "credential", "name"]
    df = pd.DataFrame(users_rows)
    for c in df_cols:
        if c not in df.columns:
            df[c] = ""
    df = df[df_cols]
    df["Delete"] = False

    col_config = {
        "ps_number": st.column_config.TextColumn("PS Number"),
        "password": st.column_config.TextColumn("Password"),
        "credential": st.column_config.SelectboxColumn("Credential", options=["Coach", "Admin"], default="Coach"),
        "name": st.column_config.TextColumn("Name"),
        "Delete": st.column_config.CheckboxColumn("Delete"),
    }

    st.subheader("Manage user credentials")
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        column_config=col_config,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Delete Selected Users"):
            to_delete_indices = edited_df.index[edited_df["Delete"] == True].tolist()
            to_delete_ps = [edited_df.loc[i, "ps_number"] for i in to_delete_indices if str(edited_df.loc[i, "ps_number"]).strip()] if to_delete_indices else []
            if not to_delete_ps:
                notify("info", "No users selected for deletion.")
            else:
                st.session_state["confirm_delete_users"] = to_delete_ps
                notify("warning", f"Review and confirm deletion of {len(to_delete_ps)} user(s) below.")

    confirm_users = st.session_state.get("confirm_delete_users")
    if confirm_users:
        with st.container(border=True):
            st.warning(f"Confirm deletion of {len(confirm_users)} user(s)? This cannot be undone.")
            # List selected PS Numbers (limited preview)
            preview = confirm_users[:20]
            if preview:
                st.write("PS Numbers:", ", ".join(preview))
                if len(confirm_users) > 20:
                    st.caption(f"…and {len(confirm_users) - 20} more")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirm Delete", key="confirm_delete_users_btn"):
                    current_users = load_json(FILES["users"]) or []
                    kept = [r for r in current_users if r.get("ps_number") not in set(confirm_users)]
                    save_json(FILES["users"], kept)
                    if supabase and confirm_users:
                        try:
                            supabase.table("users").delete().in_("ps_number", confirm_users).execute()
                            supabase.table("coaches").delete().in_("ps_number", confirm_users).execute()
                        except Exception as e:
                            notify("warning", f"Could not delete from Supabase: {e}")
                    notify("success", f"Deleted {len(confirm_users)} user(s).")
                    show_summary("Admin Users — Delete", deleted=len(confirm_users))
                    st.session_state.pop("confirm_delete_users", None)
                    st.rerun()
            with c2:
                if st.button("Cancel", key="cancel_delete_users_btn"):
                    st.session_state.pop("confirm_delete_users", None)
                    notify("info", "User deletion canceled.")

    with col2:
        if st.button("Save User Changes", type="primary"):
            # Drop Delete column and normalize rows
            working = edited_df.drop(columns=["Delete"], errors="ignore").fillna("")
            rows = working.to_dict(orient="records")
            shaped = []
            invalid_rows = []
            duplicated = set()
            seen = set()
            for r in rows:
                raw_ps = str(r.get("ps_number", "")).strip().upper()
                if not raw_ps:
                    continue
                # Validate PS format
                if not re.match(r"^PS\d+$", raw_ps):
                    invalid_rows.append(raw_ps)
                    continue
                # Detect duplicates in the submitted grid
                if raw_ps in seen:
                    duplicated.add(raw_ps)
                    continue
                seen.add(raw_ps)
                cred = r.get("credential", "Coach") or "Coach"
                if cred not in ("Coach", "Admin"):
                    cred = "Coach"
                shaped.append({
                    "ps_number": raw_ps,
                    "password": str(r.get("password", "")),
                    "credential": cred,
                    "name": str(r.get("name", "")),
                })
            if invalid_rows or duplicated:
                if invalid_rows:
                    notify("error", f"Invalid PS Number format: {sorted(set(invalid_rows))}")
                if duplicated:
                    notify("error", f"Duplicated PS Number: {sorted(duplicated)}")
                show_summary("Admin Users — Save", saved=0, errors=len(invalid_rows) + len(duplicated))
                st.stop()
            save_json(FILES["users"], shaped)
            if supabase and shaped:
                try:
                    supabase.table("users").upsert(shaped, on_conflict="ps_number").execute()
                    # Mirror into 'coaches' table with reduced schema
                    mirrored = [
                        {"ps_number": r.get("ps_number"), "password": r.get("password"), "credential": r.get("credential", "Coach")}
                        for r in shaped if r.get("ps_number")
                    ]
                    try:
                        supabase.table("coaches").upsert(mirrored, on_conflict="ps_number").execute()
                    except Exception as me:
                        notify("warning", f"Mirror to 'coaches' skipped: {me}")
                    notify("success", f"Saved and synced {len(shaped)} user(s).")
                    show_summary("Admin Users — Save", saved=len(shaped), synced=len(shaped), mirrored=len(mirrored))
                except Exception as e:
                    notify("warning", f"Saved locally, but could not sync to Supabase: {e}")
                    show_summary("Admin Users — Save", saved=len(shaped), synced=0, errors=1)
            else:
                notify("success", f"Saved {len(shaped)} user(s) locally.")
                show_summary("Admin Users — Save", saved=len(shaped))
            st.rerun()

# ----------------------------
# Kimono Stock
# ----------------------------
elif menu_selected == "Kimono Stock":
    st.header("Kimono Stock — Estoque de Kimonos")

    schools = load_json(FILES["schools"]) or []
    stock_rows = load_json(FILES["stock"]) or []
    stock_rows = ensure_stock_id_and_defaults(stock_rows)

    visible_schools = list_user_schools(user, schools)
    school_label_map = [f"{s.get('nome','(no name)')} ({s.get('id','')})" for s in visible_schools]
    school_choice = st.selectbox("School", ["All schools"] + school_label_map) if visible_schools else None
    selected_school_id = None
    if school_choice and school_choice != "All schools":
        selected_school_id = school_choice.split("(")[-1].replace(")", "").strip()

    # Filter stock rows by visibility
    if user.get("credential") == "Admin":
        filtered_rows = stock_rows if not selected_school_id else [r for r in stock_rows if str(r.get("school_id")) == str(selected_school_id)]
    else:
        allowed_ids = {str(s.get("id")) for s in visible_schools}
        filtered_rows = [r for r in stock_rows if str(r.get("school_id")) in allowed_ids]
        if selected_school_id:
            filtered_rows = [r for r in filtered_rows if str(r.get("school_id")) == str(selected_school_id)]

    # Aggregate counts by project -> type -> size
    agg = {}
    for r in filtered_rows:
        proj = (r.get("project") or "").upper() or "UNKNOWN"
        typ = r.get("type") or r.get("item") or "UNKNOWN"
        size = r.get("size") or "UNKNOWN"
        qty = int(r.get("quantity") or 0)
        agg.setdefault(proj, {}).setdefault(typ, {}).setdefault(size, 0)
        agg[proj][typ][size] += qty

    st.subheader("Aggregated stock summary")
    if not agg:
        st.info("No stock rows found for the selected schools.")
    else:
        for proj, types in sorted(agg.items()):
            st.markdown(f"**Project: {proj}**")
            rows = []
            for typ, sizes in sorted(types.items()):
                for size, qty in sorted(sizes.items()):
                    rows.append({"Type": typ, "Size": size, "Quantity": qty})
            try:
                st.table(pd.DataFrame(rows))
            except Exception:
                st.write(rows)

    st.divider()
    st.subheader("Edit stock rows")
    # Show editable grid for filtered rows (Admin can edit any; coaches only their schools)
    df = pd.DataFrame(filtered_rows) if filtered_rows else pd.DataFrame(columns=["school_id", "project", "type", "size", "quantity"])
    # Friendly column labels
    col_cfg = {
        "school_id": st.column_config.TextColumn("School ID"),
        "project": st.column_config.SelectboxColumn("Project", options=["MOE", "ESE", "OTHER"], default="MOE"),
        "type": st.column_config.TextColumn("Type"),
        "size": st.column_config.TextColumn("Size"),
        "quantity": st.column_config.NumberColumn("Quantity", min_value=0, step=1),
    }
    edited = st.data_editor(df, use_container_width=True, hide_index=True, column_config=col_cfg)

    if st.button("Save Stock Changes", type="primary"):
        # Normalize and validate
        recs = edited.fillna("").to_dict(orient="records")
        invalid = []
        for i, r in enumerate(recs):
            if not str(r.get("school_id", "")).strip():
                invalid.append(f"row {i+1}: missing school_id")
            try:
                r["quantity"] = int(r.get("quantity") or 0)
            except Exception:
                invalid.append(f"row {i+1}: invalid quantity")
            r["project"] = str(r.get("project") or "").upper()
        if invalid:
            notify("error", "; ".join(invalid))
            st.stop()

        # Merge back into full list: replace rows that match by id, otherwise append
        existing = load_json(FILES["stock"]) or []
        by_id = {r.get("id"): r for r in existing if r.get("id")}
        for r in recs:
            if r.get("id") and r.get("id") in by_id:
                by_id[r.get("id")].update(r)
            else:
                # ensure id
                if not r.get("id"):
                    r["id"] = str(uuid.uuid4())
                by_id[r["id"]] = r

        out = list(by_id.values())
        save_json(FILES["stock"], out)
        notify("success", f"Saved {len(recs)} stock rows.")
        st.rerun()

# ----------------------------
# Data Sync (Admin Only)
# ----------------------------
elif menu_selected == "Data Sync" and user["credential"] == "Admin":
    st.header("Data Sync")
    st.write("Push all local JSON data to Supabase tables.")

    force = st.checkbox("Force upsert all (ignore existing data)")
    replace = False
    if force:
        replace = st.checkbox("Replace remote with local (delete then upsert) — dangerous")

    col_a, col_b, col_c = st.columns([1,1,2])
    with col_a:
        if st.button("Sync Local JSONs → Supabase", type="primary"):
            sync_local_to_supabase(force=force, replace=replace)
    with col_b:
        if st.button("Force Upsert All", type="secondary"):
            sync_local_to_supabase(force=True, replace=False)
    with col_c:
        if st.button("Replace Remote With Local", type="secondary"):
            sync_local_to_supabase(force=True, replace=True)

    st.divider()
    st.subheader("Pull Supabase → Local JSONs")
    if st.button("Pull From Supabase → Local", type="primary"):
        pull_supabase_to_local()
