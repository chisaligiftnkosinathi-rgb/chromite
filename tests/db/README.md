# Database replay tests (local only)

`test_migration_replay.py` replays the migrations on a throwaway PostgreSQL cluster
that imitates Supabase roles (`postgres` as a non-superuser owner, `anon`,
`authenticated`, `service_role`, `supabase_auth_admin` owning `auth.users`).
It never contacts hosted Supabase. All data is synthetic.

Each test creates and drops its own database. Tests run twice: with and without
`BYPASSRLS` on `postgres`.

## Running (Linux / WSL example)
```bash
initdb -U supabase_admin -D /tmp/chromite-pg -A trust
pg_ctl -D /tmp/chromite-pg -o "-p 5434 -k /tmp" start      # PostGIS must be installed
export CHROMITE_REPLAY_ADMIN_DSN="host=/tmp port=5434 user=supabase_admin dbname=postgres"
python -m pytest tests/db
```
Without `CHROMITE_REPLAY_ADMIN_DSN` the suite is skipped.

This is not a substitute for the real local Supabase stack test
(`tools/db/local-supabase-stack-test.ps1`).
