# Chromite — Implementation Log

## 2026-11-03 — Phase 1: Repository audit
Read-only audit. Full report: Chromite project doc `claude/phase-1-repository-audit.md`.

## 2026-11-03 — Phase 1b: Consolidated migration review (read-only)
- Held drafts reviewed (left untouched in `..\chromite-migrations-held`).
- Local replay proved: hosted state (M1+M2) denies all 6 public views and organisation
  creation; the initial schema has an RLS recursion bug in owner-membership creation.
- Consolidated replacement drafted in `supabase/migrations-proposed/` with preflight,
  postflight, corrected audit guard (FK-deletion-only NULL), finance_officer role, and a
  tested rollback. Replay: 110/110 passed.
- Hosted `/mines` could not be called (network allowlist); evidence is the local replay.

## 2026-11-03 — Phase 0: Repository hygiene
- Added `.gitignore`, `.gitattributes`, `.githooks/pre-commit`.
- Config: `CORS_ORIGINS` accepts comma-separated or JSON; wildcard + credentials rejected;
  `CHROMITE_ENV_FILE` override for tests.
- `main.py`: CORS from settings with explicit methods/headers; logging configured;
  sample-batches router unregistered (table never existed). `batches.py` kept unchanged.
- `app/core/auth.py`: bearer-token dependency (401 for bad credentials, 503 for outage).
- `app/core/logging.py`: redaction of keys, bearer tokens, JWTs and DB passwords,
  including tracebacks.
- `mines.py`: `province` restricted to letters/space/hyphen/apostrophe (no wildcards);
  `operating_status` validated against the DB enum.
- Dependencies pinned to the `.venv` versions; `requirements-dev.txt` added.
- Tests: config, CORS, auth, logging, mines, routes, env isolation, repo hygiene;
  DB replay suite under `tests/db`.
- Tools: `tools/db/local-supabase-stack-test.ps1` (+ probe SQL),
  `tools/git/phase0-commit.ps1` (owner runs Git from PowerShell).
- Backups, ZIP and `chromite_structure.txt` preserved in place, git-ignored.
- Hosted Supabase: **not changed**.

## 2026-11-03 — Chrome seed pilot (local only)
- `seed_data/chrome/`: 9 candidate mines (5 importable, 4 held back for missing province) and
  8 candidate laboratories, every record citing a source checked on 3 Nov 2026.
- No laboratory is marked accredited; 5 accreditation claims are queued as unverified (3 say
  accredited: T0974, T0658 lead, AHK Richards Bay; 2 say accreditation is being pursued). No accreditation scope or mining-right rows are created.
- `app/seeding/`: validated models and an importer that refuses non-local databases, dry-runs by
  default, imports drafts only, never overwrites reviewed records, and writes an audit event.
- Tests at first commit: 26 model + 6 database tests; 198 passed with the replay cluster,
  85 passed / 116 skipped on Windows without it.
- Hosted Supabase: not changed.

## 2026-11-03 — Seed pilot review fixes
- Importer is now insert-only: existing records are never modified, so reviewer edits survive
  re-runs (the previous upsert overwrote edits that left statuses unchanged; reproduced, then fixed).
- DSN hardening: explicit local host required; `service=`, `servicefile=`, `hostaddr=` and
  PGHOSTADDR/PGSERVICE/PGSERVICEFILE refused; the connected address is re-checked after connecting.
- Claims carry `claim_type` (`states_accredited` / `pursuing_accreditation`).
- Local Supabase stack test now also runs the importer (dry run, apply, re-run) and checks the result.
- Tests: 214 passed with the replay cluster; 97 passed / 120 skipped without it (outside Git).
