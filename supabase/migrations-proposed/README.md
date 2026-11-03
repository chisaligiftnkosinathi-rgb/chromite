# Proposed migrations — NOT ACTIVE

Files here are **not** picked up by `supabase db push` or `supabase start` in this
repository. They require owner approval before being moved to `supabase/migrations/`,
and separate approval before any hosted application.

## 20261104090000_consolidated_grants_rls_superadmin_audit
Supersedes the held drafts in `..\chromite-migrations-held` (left untouched).

| Fix | Detail |
|---|---|
| Column grants | Restores what `20261103170000` unintentionally revoked (public views, organisations) |
| RLS recursion | Replaces mutually-referencing organisation/membership policies with `SECURITY DEFINER` helpers in `private` |
| Organisation type | Owners can no longer change `organization_type` |
| Staff roles | Adds `superadmin`, `finance_officer` |
| Audit log | `platform_audit_logs`, append-only for app roles + owner guard trigger |

Preflight aborts without changes if the database differs from the expected state
(policies, staff roles, ownership, FORCE RLS, existing audit table). Postflight verifies
helper ownership, `search_path` and EXECUTE privileges.

**Limitation:** database owners and superusers can disable triggers or drop the table.
The audit log is not immutable against them; off-database export is planned.

## 20261104100000_create_organization_with_owner
One database function that creates an organisation, the caller's owner membership and its
audit event in a single transaction (all or nothing). `SECURITY DEFINER`, empty `search_path`,
the acting user is always `auth.uid()`, provider types refused, at most 10 owned organisations
(serialised per user), `EXECUTE` for `authenticated` only. Requires the consolidated migration.
Replay: 18 tests (`tests/db/test_org_rpc.py`), including a forced mid-transaction failure that
leaves no organisation or audit row. Rollback drops the function only.

## Rollback
`...ROLLBACK.sql` restores the exact pre-migration schema (verified by schema-dump
comparison). It refuses to run if audit rows exist (unless
`SET chromite.rollback_discard_audit = 'yes'` after exporting them) or if the new
staff roles are in use.

## Verification status
- Local PostgreSQL 16 + PostGIS replay with a Supabase role stand-in: **110/110 passed** (`tests/db`).
- Real local Supabase stack: consolidated migration **passed** (3 Nov 2026); the organisation
  function is exercised by the stack test's API smoke test.
- Hosted: **not applied**.
