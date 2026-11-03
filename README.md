# CHROMITE Backend Platform
Industry intelligence and sample-testing coordination for South African chrome ore.

## System architecture
- **Backend framework:** FastAPI (Python)
- **Database:** Supabase PostgreSQL with PostGIS
- **Security:** Row Level Security (RLS) multi-tenant isolation; service-role key on the backend only

See `docs/ARCHITECTURE.md` (target architecture), `docs/SECURITY_NOTES.md` and
`docs/IMPLEMENTATION_LOG.md`.

## Setup (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env   # then fill in values; never commit .env
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Tests
```powershell
.\.venv\Scripts\python -m pytest
```
Tests never contact Supabase and never read your `.env`. The database replay suite in
`tests/db/` is skipped unless `CHROMITE_REPLAY_ADMIN_DSN` points to a throwaway local
PostgreSQL cluster (see `tests/db/README.md`).

## Database migrations — rules
- `supabase/migrations/` holds migrations already applied to the hosted project.
- `supabase/migrations-proposed/` holds reviewed drafts that are **not active**.
  Moving a file into `migrations/` and applying it to the hosted project each need
  explicit owner approval.
- Never run `supabase db push`, `db reset`, `migration repair` or remote SQL without approval.

## Current API
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | none | health |
| GET | `/api/v1/mines/` | none | published chrome mines; filters `province`, `operating_status`, `limit`, `offset` |

The early `/api/v1/sample-batches/` endpoint is disabled (its table never existed);
it is replaced by the booking/sample lifecycle in Phase 7.
