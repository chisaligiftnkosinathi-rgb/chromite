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
| GET | `/healthz` | none | liveness |
| GET | `/readyz` | none | readiness: database answers a public query (503 if not) |
| GET | `/api/v1/mines/` · `/api/v1/mines/{slug}` | none | published chrome mines |
| GET | `/api/v1/laboratories/` · `/{id}` | none | published laboratories (directory status, not accreditation) |
| GET | `/api/v1/laboratories/{id}/accreditation-scopes` | none | verified, currently valid scope entries only |
| GET | `/api/v1/sampling-providers/` · `/{id}/services` | none | published providers; verified services only |
| GET | `/api/v1/me/` | bearer | user, organisation memberships, staff role |
| GET | `/api/v1/organizations/` · `/{id}` | bearer | your organisations only (404 for others) |
| POST | `/api/v1/organizations/` | bearer | create an organisation; you become owner. Provider types cannot be self-declared |

Every response carries `X-Request-ID` and security headers. Public endpoints are rate-limited
per client (`RATE_LIMIT_PUBLIC_PER_MINUTE`), writes more strictly (`RATE_LIMIT_WRITE_PER_MINUTE`);
the limiter is in-memory per process, so use a shared store before running several instances.
Interactive docs are off in production unless `DOCS_ENABLED=true`.

**Hosted note:** organisation sign-up depends on the consolidated migration in
`supabase/migrations-proposed/`. Until it is approved and applied, the hosted project refuses it.

The early `/api/v1/sample-batches/` endpoint is disabled (its table never existed);
it is replaced by the booking/sample lifecycle in Phase 7.
