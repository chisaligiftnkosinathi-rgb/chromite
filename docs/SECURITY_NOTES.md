# Chromite — Security Notes

## Credential handling rules
- `SUPABASE_KEY` = **publishable** key (`sb_publishable_…`). Subject to RLS.
- `SUPABASE_SERVICE_ROLE_KEY` = **secret** key (`sb_secret_…`). Bypasses RLS. Backend only,
  loaded only by `app.core.supabase.get_supabase_admin()`, never sent to a browser,
  never logged (see `app/core/logging.py` redaction).
- `.env` is git-ignored; `.githooks/pre-commit` blocks `.env*` (except `.env.example`),
  ZIPs, backups, `supabase/.temp`, local data and secret-looking strings.
- Tests point `CHROMITE_ENV_FILE` at a non-existent file and never read `.env`.

## Incident record — live secret key inside `chromite-backend-review.zip`

| Item | Finding |
|---|---|
| File | `chromite-backend-review.zip` (4,587 bytes, 18 entries) in the repository root; created 2026-11-03 (entries dated 14:25–15:35) |
| Content | An older `.env.example` (352 bytes) holding the **real** project URL, the publishable key and the **`sb_secret_` service-role key**. All three are identical to the current `.env` (compared programmatically; values never printed). |
| Current `.env.example` | Placeholders only (clean). |
| Git exposure | None: no Git repository existed; the ZIP is now git-ignored (`*.zip`) and blocked by the pre-commit hook. |
| Known transfers | 2026-11-03, Phase 1 audit: the ZIP was copied into this AI session's private cloud workspace and its file list read (`unzip -l`). The secret value was not displayed. That copy was deleted on 2026-11-03 at about 20:10 SAST. |
| Uploaded / emailed / shared elsewhere? | **Unknown — to be confirmed by the owner.** The file name suggests it was prepared for an external review. *Owner to record here:* `______` |
| Recommended action | Rotate the secret key in the Supabase dashboard (Project Settings → API Keys): create a new secret key, update `.env`, confirm the backend works, revoke the old key. **Owner action** — not performed by the assistant. |
| ZIP disposition | Kept in place, git-ignored, pending the owner's decision. To delete after rotation: `Remove-Item .\chromite-backend-review.zip` |
| Status | **OPEN** until rotation is confirmed or the owner records that the file never left the machine *and* accepts the cloud-workspace copy above. |

## Known outstanding risks (Phase 0 exit)
1. Hosted database permission defects (public views, onboarding) — fix drafted in
   `supabase/migrations-proposed/`, pending local-stack test and approval.
2. No authorisation layer beyond token verification yet (Phase 2+).
3. No rate limiting (planned with auth workflows).
4. No private Storage buckets / signed URLs yet (Phase 4/8).
5. Audit log not immutable against database owners/superusers; off-database export planned.
6. Self-declared organisation types must never grant provider rights (enforced from Phase 5).
