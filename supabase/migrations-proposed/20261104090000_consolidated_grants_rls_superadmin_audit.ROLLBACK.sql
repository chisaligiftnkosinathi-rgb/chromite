-- ============================================================
-- CHROMITE — ROLLBACK for 20261104090000_consolidated_grants_rls_superadmin_audit
-- Restores the exact pre-migration state (i.e. the state after
-- 20261103170000). NOTE: that state has the known permission defects
-- (public views and onboarding fail). Use only to back out the migration.
--
-- Safety guards:
--   * Refuses if platform_audit_logs has rows, unless the session sets
--     SET chromite.rollback_discard_audit = 'yes';  (export rows first)
--   * Refuses if platform_staff uses superadmin/finance_officer roles.
--   * The audit guard trigger blocks TRUNCATE/DELETE, so the table is
--     dropped (DROP is not blocked by row/statement triggers).
-- ============================================================
BEGIN;

DO $guard$
BEGIN
    IF to_regclass('public.platform_audit_logs') IS NULL THEN
        RAISE EXCEPTION 'Rollback: migration does not appear to be applied';
    END IF;
    IF EXISTS (SELECT 1 FROM public.platform_audit_logs)
       AND coalesce(current_setting('chromite.rollback_discard_audit', true), '') <> 'yes' THEN
        RAISE EXCEPTION 'Rollback: platform_audit_logs contains rows; export them and set chromite.rollback_discard_audit = ''yes''';
    END IF;
    IF EXISTS (SELECT 1 FROM public.platform_staff
               WHERE staff_role IN ('superadmin', 'finance_officer')) THEN
        RAISE EXCEPTION 'Rollback: platform_staff uses roles introduced by this migration';
    END IF;
END
$guard$;

-- 5. Audit log
DROP TABLE public.platform_audit_logs;
DROP FUNCTION private.audit_log_guard();

-- 4. Staff constraint back to original values
ALTER TABLE public.platform_staff DROP CONSTRAINT platform_staff_staff_role_check;
ALTER TABLE public.platform_staff ADD CONSTRAINT platform_staff_staff_role_check
    CHECK (staff_role IN ('administrator', 'verification_officer', 'operations'));
COMMENT ON COLUMN public.platform_staff.staff_role IS NULL;

-- 3. Original policies, verbatim from the initial schema
DROP POLICY membership_creator_join ON public.organization_memberships;
CREATE POLICY membership_creator_join ON public.organization_memberships
FOR INSERT TO authenticated
WITH CHECK (
    user_id = (SELECT auth.uid())
    AND membership_role IN ('owner', 'member')
    AND EXISTS (SELECT 1 FROM public.organizations AS o
                WHERE o.id = organization_memberships.organization_id
                  AND o.created_by = (SELECT auth.uid()))
);
DROP POLICY organization_owner_update ON public.organizations;
CREATE POLICY organization_owner_update ON public.organizations
FOR UPDATE TO authenticated
USING (EXISTS (SELECT 1 FROM public.organization_memberships AS m
               WHERE m.organization_id = organizations.id
                 AND m.user_id = (SELECT auth.uid())
                 AND m.membership_role = 'owner'))
WITH CHECK (EXISTS (SELECT 1 FROM public.organization_memberships AS m
               WHERE m.organization_id = organizations.id
                 AND m.user_id = (SELECT auth.uid())
                 AND m.membership_role = 'owner'));
DROP POLICY organization_member_read ON public.organizations;
CREATE POLICY organization_member_read ON public.organizations
FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM public.organization_memberships AS m
               WHERE m.organization_id = organizations.id
                 AND m.user_id = (SELECT auth.uid())));

DROP FUNCTION private.is_org_member(UUID);
DROP FUNCTION private.is_org_owner(UUID);
DROP FUNCTION private.is_org_creator(UUID);
REVOKE USAGE ON SCHEMA private FROM authenticated;

-- 1–2. Remove restored column grants (back to post-20261103170000 state)
REVOKE SELECT, INSERT, UPDATE ON public.organizations FROM authenticated;
REVOKE SELECT, INSERT ON public.organization_memberships FROM authenticated;
REVOKE SELECT ON public.mines, public.mine_production_records, public.laboratories,
                 public.lab_accreditation_scopes, public.sampling_providers,
                 public.sampling_provider_services
    FROM anon, authenticated;

COMMIT;
