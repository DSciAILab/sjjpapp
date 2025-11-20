from data.supabase import create_client

# ⚠️ USE AQUI A SERVICE ROLE KEY (privada)
SUPABASE_URL = "https://fuynmwpwcekkyfkiaunu.supabase.co"  # substitua pelo seu
SUPABASE_KEY = "sb_secret_dvhoQn3T9HXcWThT25VjoA_5xv8i3gL"  # service role key

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

sql_script = """
create table if not exists users (
  ps_number text primary key,
  password text not null,
  credential text default 'Coach',
  name text
);
insert into users (ps_number, password, credential, name)
values ('PS1724', 'PS1724', 'Admin', 'Administrator')
on conflict (ps_number) do nothing;

create table if not exists coaches (
  ps_number text primary key,
  name text
);

create table if not exists schools (
  id text primary key,
  nome text,
  city text,
  coaches text[] default array[]::text[]
);

create table if not exists materials (
  category text,
  subcategory text,
  item text
);

create table if not exists requests (
  id uuid primary key default gen_random_uuid(),
  school_id text,
  category text,
  material text,
  quantity int,
  date timestamp with time zone default now(),
  ps_number text,
  status text default 'Pending'
);

create table if not exists stock_kimonos (
  id uuid primary key default gen_random_uuid(),
  school_id text,
  project text,
  type text,
  size text,
  quantity int default 0
);
"""

# Executa o SQL diretamente
supabase.rpc("sql", {"query": sql_script}).execute()
print("✅ All tables created successfully in Supabase!")