# Copilot instructions for SJJP Requests Portal

These notes help AI coding agents become productive quickly in this repository.
Focus on discoverable patterns and concrete places to change.

- Project entry: `app.py` — a Streamlit app that drives almost all UX and business logic.
- Local canonical storage: `data/*.json` (users.json, schools.json, materials.json, requests.json).
  - The app reads/writes these files with `load_json` / `save_json` helpers.
  - Treat these JSON files as the primary local data model when making changes.

- Supabase integration:
  - Connection via `st.secrets['SUPABASE_URL']` and `st.secrets['SUPABASE_KEY']` in `app.py`.
  - Best-effort sync: `sync_local_to_supabase()` and `pull_supabase_to_local()` implement upsert/pull.
  - `supa.py` and `bootstrap_app.py` contain helper scripts: DB-creation SQL and a scripted upsert utility.
  - WARNING: `supa.py` currently includes a hard-coded service role key — avoid committing secrets and prefer `st.secrets` or env vars.

- Key data shapes and constraints (examples):
  - users.json: [{"ps_number":"PS1724","password":"PS1724","credential":"Admin","name":"..."}]
  - schools.json: [{"id":"1565","nome":"School Name","city":"...","coaches":["PS2443"]}]
  - materials.json: list of {category, subcategory, item}
  - requests.json: [{"id":"<uuid>","school_id":"1565","category":"...","material":"...","quantity":1,"date":"...","ps_number":"PS1724","status":"Pending"}]

- Conventions and safety checks:
  - PS numbers are normalized to uppercase and validated with regex ^PS\d+$ in `app.py` (Admin user flows enforce this).
  - When adding/removing fields in JSON models, update `allowed_fields` and `conflict_targets` mappings inside `app.py` and in `data/supa_sync` helpers to avoid Supabase schema mismatches.
  - `migrate_coaches_into_users()` is a one-off migration in `app.py` — be aware of it when adding coach-related files.

- UI and interaction patterns:
  - Streamlit `st.session_state` is used for short-lived UI state (e.g., `pending_request`, confirmation ids). Persisted data must go to `data/*.json`.
  - `st.data_editor` and `st.column_config.*` are used heavily for admin grids — edits are validated then saved with `save_json` and optionally upserted to Supabase.

- Developer workflows and commands (discovered in repo):
  - Run the app locally: `streamlit run app.py` (ensure Streamlit and dependencies from `requirements.txt` are installed).
  - Environment / secret setup: provide `SUPABASE_URL` and `SUPABASE_KEY` via Streamlit secrets (`.streamlit/secrets.toml`) or environment variables.
  - Quick environment check: `python check.py` prints python path and confirms `supabase-py` availability.
  - Create DB schema (one-time): `python bootstrap_app.py` (this executes SQL via Supabase RPC in `bootstrap_app.py`).

- When changing data model or adding tables:
  - Update the `allowed_fields` mapping and `conflict_targets` in `app.py` (both sync_local_to_supabase and pull_supabase_to_local use them).
  - Update `bootstrap_app.py` and `supa.py` to reflect DDL and seed rows if needed.
  - Add clear conversion logic for columns that are arrays (e.g., `coaches` is a list of PS numbers) — `app.py` expects `coaches` as a list.

- Cross-cutting notes for edits and PRs:
  - Avoid committing secrets. Replace hard-coded keys in `supa.py` with env-based retrieval.
  - Preserve UX behavior: admin-only sections gate via `user['credential'] == 'Admin'` — do not bypass without migrating permission checks.
  - Keep local JSONs human-editable: editors often rely on CSV export/import (`data/csv.py`) and simple list-of-dicts layout.

- Where to look for examples in the codebase:
  - `app.py` — full request lifecycle, validation, sync logic, and admin flows.
  - `bootstrap_app.py` — schema creation SQL and recommended service-role usage (but replace secrets before using).
  - `supa.py` — scripted upsert utility and shape/allowed-fields examples.
  - `data/csv.py` — JSON → CSV exporter for schools.

If anything in these notes is unclear or you want the Copilot instructions to include extra sections (tests, CI, or local dev container tips), tell me which area and I will iterate.
