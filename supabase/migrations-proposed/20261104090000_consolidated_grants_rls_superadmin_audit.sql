-- ============================================================
-- CHROMITE — Consolidated corrective migration
-- File: 20261104090000_consolidated_grants_rls_superadmin_audit.sql
-- Status: PROPOSED. Not in supabase/migrations/. Not applied to hosted.
-- Supersedes held drafts 20261103173000, 20261103180000, 20261103190000
-- (those files are left untouched).
--
-- Fixes:
--  1. Migration 20261103170000 ran REVOKE ALL ON ALL TABLES, which in
--     PostgreSQL also revokes column privileges. Public directory views
--     and organisation onboarding fail with "permission denied".
--  2. Original organisation/membership RLS policies reference each other
--     and raise "infinite recursion detected in policy" when a creator
--     inserts their owner membership (present since the initial schema).
--  3. Owners could change organization_type (self-labelling as a provider).
--  4. Adds superadmin and finance_officer staff roles.
--  5. Adds an append-only platform audit log.
--
-- Immutability statement: the audit log is append-only for every
-- application role (anon, authenticated, service_role) through grants,
-- and a guard trigger additionally blocks UPDATE/DELETE/TRUNCATE by the
-- table owner. Database owners and superusers can still disable triggers
-- (ALTER TABLE ... DISABLE TRIGGER, session_replication_role = replica)
-- or drop the table. This is NOT absolute immutability against them;
-- off-database export of audit events is required for that (later phase).
--
-- Rollback: see 20261104090000_consolidated_..._ROLLBACK.sql (tested).
-- ============================================================
BEGIN;

-- ------------------------------------------------------------
-- 0. PREFLIGHT — fail safely if the database is not in the state
--    this migration was written and tested against.
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS private;   -- created by the initial schema; idempotent safety

DO $preflight$
DECLARE
    v_bad_roles TEXT;
    v_rec RECORD;
BEGIN
    -- 0.1 private schema must be owned by the migrating role and not
    --     granted to PUBLIC/anon (it is not exposed via the Data API).
    IF NOT EXISTS (SELECT 1 FROM pg_namespace n
                   WHERE n.nspname = 'private'
                     AND n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)) THEN
        RAISE EXCEPTION 'Preflight: schema private is not owned by %', current_user;
    END IF;
    IF has_schema_privilege('anon', 'private', 'USAGE') THEN
        RAISE EXCEPTION 'Preflight: anon unexpectedly has USAGE on schema private';
    END IF;

    -- 0.2 Original policies must exist exactly as in the initial schema.
    FOR v_rec IN
        SELECT * FROM (VALUES
            ('organizations', 'organization_creator_insert', 'INSERT', NULL::TEXT,
                 '(created_by = ( SELECT auth.uid() AS uid))'),
            ('organizations', 'organization_creator_read', 'SELECT',
                 '(created_by = ( SELECT auth.uid() AS uid))', NULL),
            ('organizations', 'organization_member_read', 'SELECT', NULL, NULL),
            ('organizations', 'organization_owner_update', 'UPDATE', NULL, NULL),
            ('organization_memberships', 'membership_read_own', 'SELECT',
                 '(user_id = ( SELECT auth.uid() AS uid))', NULL),
            ('organization_memberships', 'membership_creator_join', 'INSERT', NULL, NULL)
        ) AS t(tbl, pol, cmd, qual, chk)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies p
            WHERE p.schemaname = 'public' AND p.tablename = v_rec.tbl
              AND p.policyname = v_rec.pol AND p.cmd = v_rec.cmd
              AND p.roles = '{authenticated}'
              AND (v_rec.qual IS NULL OR p.qual = v_rec.qual)
              AND (v_rec.chk  IS NULL OR p.with_check = v_rec.chk)
        ) THEN
            RAISE EXCEPTION 'Preflight: policy %.% is missing or differs from the initial schema',
                v_rec.tbl, v_rec.pol;
        END IF;
    END LOOP;
    IF (SELECT count(*) FROM pg_policies WHERE schemaname = 'public'
          AND tablename IN ('organizations', 'organization_memberships')) <> 6 THEN
        RAISE EXCEPTION 'Preflight: unexpected extra policies on organisation tables';
    END IF;

    -- 0.3 Existing platform_staff role values must fit the new constraint.
    SELECT string_agg(DISTINCT staff_role, ', ') INTO v_bad_roles
    FROM public.platform_staff
    WHERE staff_role NOT IN ('superadmin', 'administrator', 'verification_officer',
                             'operations', 'finance_officer');
    IF v_bad_roles IS NOT NULL THEN
        RAISE EXCEPTION 'Preflight: platform_staff contains unsupported roles: %', v_bad_roles;
    END IF;
    RAISE NOTICE 'Preflight: platform_staff rows by role: %',
        (SELECT coalesce(jsonb_object_agg(staff_role, n), '{}'::jsonb)
         FROM (SELECT staff_role, count(*) n FROM public.platform_staff GROUP BY 1) s);
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'platform_staff_staff_role_check'
                     AND conrelid = 'public.platform_staff'::regclass) THEN
        RAISE EXCEPTION 'Preflight: constraint platform_staff_staff_role_check not found';
    END IF;

    -- 0.4 SECURITY DEFINER helpers rely on the function owner owning the
    --     tables they read (owners bypass RLS unless FORCE RLS is set).
    IF EXISTS (SELECT 1 FROM pg_class c
               WHERE c.oid IN ('public.organizations'::regclass,
                               'public.organization_memberships'::regclass)
                 AND (c.relforcerowsecurity
                      OR c.relowner <> (SELECT oid FROM pg_roles WHERE rolname = current_user))) THEN
        RAISE EXCEPTION 'Preflight: organisation tables are FORCE RLS or not owned by %', current_user;
    END IF;

    -- 0.5 Audit table must not exist yet.
    IF to_regclass('public.platform_audit_logs') IS NOT NULL THEN
        RAISE EXCEPTION 'Preflight: public.platform_audit_logs already exists';
    END IF;
END
$preflight$;

-- ------------------------------------------------------------
-- 1. Organisation column grants (held 173000) — without UPDATE on
--    organization_type.
-- ------------------------------------------------------------
GRANT SELECT (id, organization_name, organization_type, registration_number,
              country_code, created_by, created_at, updated_at)
    ON public.organizations TO authenticated;
GRANT INSERT (organization_name, organization_type, registration_number,
              country_code, created_by)
    ON public.organizations TO authenticated;
GRANT UPDATE (organization_name, registration_number, country_code)
    ON public.organizations TO authenticated;
GRANT SELECT (id, organization_id, user_id, membership_role, created_at)
    ON public.organization_memberships TO authenticated;
GRANT INSERT (organization_id, user_id, membership_role)
    ON public.organization_memberships TO authenticated;

-- ------------------------------------------------------------
-- 2. Public-view underlying column grants (held 180000).
--    Identical to the initial schema's column lists. No table-level SELECT.
-- ------------------------------------------------------------
GRANT SELECT (id, mine_name, slug, commodity, province, district, nearest_town,
              latitude, longitude, mine_type, operating_status, publication_status,
              verification_status, public_description, source_name, source_url,
              source_checked_at)
    ON public.mines TO anon, authenticated;
GRANT SELECT (id, mine_id, reporting_period_start, reporting_period_end,
              production_tonnes, production_category, production_stage, data_status,
              publication_status, source_name, source_url, source_published_at)
    ON public.mine_production_records TO anon, authenticated;
GRANT SELECT (id, laboratory_name, country_code, province, city, physical_address,
              website_url, publication_status, verification_status)
    ON public.laboratories TO anon, authenticated;
GRANT SELECT (id, laboratory_id, accreditation_body, accreditation_number,
              certificate_reference, standard, scope_title, material_matrix,
              analyte_or_parameter, test_method, scope_valid_from, scope_valid_until,
              verification_status)
    ON public.lab_accreditation_scopes TO anon, authenticated;
GRANT SELECT (id, provider_name, country_code, province, city, physical_address,
              website_url, service_description, publication_status, verification_status)
    ON public.sampling_providers TO anon, authenticated;
GRANT SELECT (id, provider_id, service_name, material_type, service_description,
              service_status, publication_status)
    ON public.sampling_provider_services TO anon, authenticated;

-- ------------------------------------------------------------
-- 3. RLS recursion fix. SECURITY DEFINER helpers in the non-API
--    private schema, owned by the migrating role (table owner),
--    empty search_path, fully-qualified names, boolean result about
--    the calling user only. organization_creator_insert and
--    organization_creator_read are NOT changed.
-- ------------------------------------------------------------
CREATE FUNCTION private.is_org_member(p_org UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.organization_memberships m
                   WHERE m.organization_id = p_org
                     AND m.user_id = (SELECT auth.uid()));
$$;
CREATE FUNCTION private.is_org_owner(p_org UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.organization_memberships m
                   WHERE m.organization_id = p_org
                     AND m.user_id = (SELECT auth.uid())
                     AND m.membership_role = 'owner');
$$;
CREATE FUNCTION private.is_org_creator(p_org UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.organizations o
                   WHERE o.id = p_org
                     AND o.created_by = (SELECT auth.uid()));
$$;
REVOKE ALL ON FUNCTION private.is_org_member(UUID), private.is_org_owner(UUID),
                       private.is_org_creator(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA private TO authenticated;
GRANT EXECUTE ON FUNCTION private.is_org_member(UUID), private.is_org_owner(UUID),
                          private.is_org_creator(UUID) TO authenticated;

DROP POLICY organization_member_read ON public.organizations;
CREATE POLICY organization_member_read ON public.organizations
    FOR SELECT TO authenticated
    USING ((SELECT private.is_org_member(organizations.id)));

DROP POLICY organization_owner_update ON public.organizations;
CREATE POLICY organization_owner_update ON public.organizations
    FOR UPDATE TO authenticated
    USING ((SELECT private.is_org_owner(organizations.id)))
    WITH CHECK ((SELECT private.is_org_owner(organizations.id)));

-- Creator may add only their own first membership, as owner.
-- Additional members are added by the backend invite workflow.
DROP POLICY membership_creator_join ON public.organization_memberships;
CREATE POLICY membership_creator_join ON public.organization_memberships
    FOR INSERT TO authenticated
    WITH CHECK (
        user_id = (SELECT auth.uid())
        AND membership_role = 'owner'
        AND (SELECT private.is_org_creator(organization_memberships.organization_id))
    );

-- ------------------------------------------------------------
-- 4. Staff roles (held 190000 + finance_officer).
-- ------------------------------------------------------------
ALTER TABLE public.platform_staff DROP CONSTRAINT platform_staff_staff_role_check;
ALTER TABLE public.platform_staff ADD CONSTRAINT platform_staff_staff_role_check
    CHECK (staff_role IN ('superadmin', 'administrator', 'verification_officer',
                          'operations', 'finance_officer'));
COMMENT ON COLUMN public.platform_staff.staff_role IS
'Platform-level role. Superadmin is distinct from administrator and organisation roles.';
REVOKE ALL PRIVILEGES ON TABLE public.platform_staff FROM PUBLIC, anon, authenticated;

-- ------------------------------------------------------------
-- 5. Append-only audit log.
-- ------------------------------------------------------------
CREATE TABLE public.platform_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    actor_role TEXT,
    action TEXT NOT NULL CHECK (length(trim(action)) > 0),
    resource_type TEXT,
    resource_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
    request_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (actor_role IS NULL OR length(trim(actor_role)) > 0),
    CHECK (resource_type IS NULL OR length(trim(resource_type)) > 0)
);
COMMENT ON TABLE public.platform_audit_logs IS
'Append-only for application roles; guard trigger also blocks owner edits. Owners/superusers can still disable triggers — not absolute immutability.';
COMMENT ON COLUMN public.platform_audit_logs.actor_role IS
'Role snapshot at event time; retained independently of later role changes.';
COMMENT ON COLUMN public.platform_audit_logs.metadata IS
'Non-sensitive event context only. Never store passwords, tokens, secrets or private keys.';

CREATE INDEX idx_platform_audit_actor_created    ON public.platform_audit_logs (actor_user_id, created_at DESC);
CREATE INDEX idx_platform_audit_resource_created ON public.platform_audit_logs (resource_type, resource_id, created_at DESC);
CREATE INDEX idx_platform_audit_action_created   ON public.platform_audit_logs (action, created_at DESC);
CREATE INDEX idx_platform_audit_outcome_created  ON public.platform_audit_logs (outcome, created_at DESC);

-- Guard: the only permitted UPDATE is the FK action ON DELETE SET NULL,
-- recognised by (a) only actor_user_id changing, (b) to NULL, and
-- (c) the referenced auth.users row no longer existing. A manual
-- "UPDATE ... SET actor_user_id = NULL" while the user exists is rejected.
-- SECURITY DEFINER so the auth.users existence check works regardless of
-- which role performs the user deletion (e.g. supabase_auth_admin).
CREATE FUNCTION private.audit_log_guard()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.actor_user_id IS NOT NULL
       AND NEW.actor_user_id IS NULL
       AND (pg_catalog.to_jsonb(NEW) OPERATOR(pg_catalog.-) 'actor_user_id')
           OPERATOR(pg_catalog.=) (pg_catalog.to_jsonb(OLD) OPERATOR(pg_catalog.-) 'actor_user_id')
       AND NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = OLD.actor_user_id)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'platform_audit_logs is append-only (% blocked)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
REVOKE ALL ON FUNCTION private.audit_log_guard() FROM PUBLIC, anon, authenticated, service_role;

CREATE TRIGGER platform_audit_logs_append_only
    BEFORE UPDATE OR DELETE ON public.platform_audit_logs
    FOR EACH ROW EXECUTE FUNCTION private.audit_log_guard();
CREATE TRIGGER platform_audit_logs_no_truncate
    BEFORE TRUNCATE ON public.platform_audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION private.audit_log_guard();

ALTER TABLE public.platform_audit_logs ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.platform_audit_logs
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON TABLE public.platform_audit_logs TO service_role;

-- ------------------------------------------------------------
-- 6. POSTFLIGHT — verify helper ownership, search_path and EXECUTE.
-- ------------------------------------------------------------
DO $postflight$
DECLARE v_rec RECORD;
BEGIN
    FOR v_rec IN
        SELECT p.oid, p.proname, p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) AS owner
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'private'
          AND p.proname IN ('is_org_member', 'is_org_owner', 'is_org_creator', 'audit_log_guard')
    LOOP
        IF NOT v_rec.prosecdef THEN
            RAISE EXCEPTION 'Postflight: %.prosecdef is false', v_rec.proname; END IF;
        IF v_rec.proconfig IS DISTINCT FROM ARRAY['search_path=""'] THEN
            RAISE EXCEPTION 'Postflight: % search_path is %', v_rec.proname, v_rec.proconfig; END IF;
        IF v_rec.owner <> current_user THEN
            RAISE EXCEPTION 'Postflight: % owned by %', v_rec.proname, v_rec.owner; END IF;
        IF has_function_privilege('anon', v_rec.oid, 'EXECUTE')
           OR has_function_privilege('service_role', v_rec.oid, 'EXECUTE') THEN
            RAISE EXCEPTION 'Postflight: % executable by anon/service_role', v_rec.proname; END IF;
        IF v_rec.proname <> 'audit_log_guard'
           AND NOT has_function_privilege('authenticated', v_rec.oid, 'EXECUTE') THEN
            RAISE EXCEPTION 'Postflight: authenticated cannot execute %', v_rec.proname; END IF;
        IF v_rec.proname = 'audit_log_guard'
           AND has_function_privilege('authenticated', v_rec.oid, 'EXECUTE') THEN
            RAISE EXCEPTION 'Postflight: authenticated can execute audit_log_guard'; END IF;
    END LOOP;
    IF (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'private'
          AND p.proname IN ('is_org_member', 'is_org_owner', 'is_org_creator', 'audit_log_guard')) <> 4 THEN
        RAISE EXCEPTION 'Postflight: expected 4 private functions';
    END IF;
END
$postflight$;

COMMIT;
