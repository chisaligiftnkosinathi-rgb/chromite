-- ============================================================
-- CHROMITE — Atomic organisation creation
-- File: 20261104100000_create_organization_with_owner.sql
-- Status: PROPOSED. Not in supabase/migrations/. Not applied to hosted.
-- Requires: 20261104090000_consolidated_grants_rls_superadmin_audit.
--
-- Creates the organisation, the caller's owner membership and the audit event
-- in ONE transaction: all three are written or none are. Replaces the API's
-- two-request flow and its after-the-fact audit write.
--
-- Security
--   * SECURITY DEFINER with an empty search_path; every name fully qualified.
--   * The acting user is always auth.uid(); there is no user parameter, so a
--     caller can only ever create an organisation for themselves.
--   * Provider types (laboratory, sampling_provider) cannot be chosen.
--   * At most 10 owned organisations per user.
--   * EXECUTE granted to authenticated only.
-- Rollback: 20261104100000_create_organization_with_owner.ROLLBACK.sql
-- ============================================================
BEGIN;

DO $preflight$
BEGIN
    IF to_regclass('public.platform_audit_logs') IS NULL THEN
        RAISE EXCEPTION 'Preflight: apply 20261104090000_consolidated_grants_rls_superadmin_audit first';
    END IF;
    IF to_regprocedure('public.create_organization_with_owner(text,text,text,text)') IS NOT NULL THEN
        RAISE EXCEPTION 'Preflight: public.create_organization_with_owner already exists';
    END IF;
END
$preflight$;

CREATE FUNCTION public.create_organization_with_owner(
    p_organization_name TEXT,
    p_organization_type TEXT DEFAULT 'customer',
    p_registration_number TEXT DEFAULT NULL,
    p_request_id TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_uid   UUID := auth.uid();
    v_name  TEXT := pg_catalog.btrim(p_organization_name);
    v_owned INTEGER;
    v_org   public.organizations;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = '42501';
    END IF;
    IF v_name IS NULL OR pg_catalog.length(v_name) < 2 OR pg_catalog.length(v_name) > 200
       OR v_name ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid organisation name' USING ERRCODE = '22023';
    END IF;
    IF p_organization_type IS NULL OR p_organization_type NOT IN
       ('customer', 'mine_owner', 'mine_operator', 'trader', 'other') THEN
        RAISE EXCEPTION 'organisation type not allowed' USING ERRCODE = '22023';
    END IF;
    IF p_registration_number IS NOT NULL AND pg_catalog.length(p_registration_number) > 50 THEN
        RAISE EXCEPTION 'registration number too long' USING ERRCODE = '22023';
    END IF;
    IF p_request_id IS NOT NULL AND p_request_id !~ '^[A-Za-z0-9._-]{8,64}$' THEN
        p_request_id := NULL;
    END IF;

    -- Serialise per user so two parallel requests cannot both pass the cap.
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_uid::TEXT, 7310));
    SELECT pg_catalog.count(*) INTO v_owned
    FROM public.organization_memberships m
    WHERE m.user_id = v_uid AND m.membership_role = 'owner';
    IF v_owned >= 10 THEN
        RAISE EXCEPTION 'owner limit reached' USING ERRCODE = 'P0001', HINT = 'owner_limit';
    END IF;

    INSERT INTO public.organizations (organization_name, organization_type, registration_number,
                                      country_code, created_by)
    VALUES (v_name, p_organization_type, NULLIF(pg_catalog.btrim(p_registration_number), ''),
            'ZA', v_uid)
    RETURNING * INTO v_org;

    INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)
    VALUES (v_org.id, v_uid, 'owner');

    INSERT INTO public.platform_audit_logs (actor_user_id, actor_role, action, resource_type,
                                            resource_id, outcome, request_id, metadata)
    VALUES (v_uid, 'owner', 'organization.create', 'organization', v_org.id::TEXT, 'success',
            p_request_id, pg_catalog.jsonb_build_object('organization_type', p_organization_type));

    RETURN pg_catalog.jsonb_build_object(
        'id', v_org.id,
        'organization_name', v_org.organization_name,
        'organization_type', v_org.organization_type,
        'registration_number', v_org.registration_number,
        'country_code', v_org.country_code,
        'created_at', v_org.created_at
    );
END;
$$;

REVOKE ALL ON FUNCTION public.create_organization_with_owner(TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.create_organization_with_owner(TEXT, TEXT, TEXT, TEXT)
    TO authenticated;

COMMENT ON FUNCTION public.create_organization_with_owner(TEXT, TEXT, TEXT, TEXT) IS
'Atomically creates an organisation, the caller''s owner membership and its audit event.';

DO $postflight$
DECLARE v RECORD;
BEGIN
    SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) AS owner, p.oid INTO v
    FROM pg_proc p WHERE p.oid = 'public.create_organization_with_owner(text,text,text,text)'::regprocedure;
    IF NOT v.prosecdef OR v.proconfig IS DISTINCT FROM ARRAY['search_path=""'] OR v.owner <> current_user THEN
        RAISE EXCEPTION 'Postflight: function security settings wrong';
    END IF;
    IF has_function_privilege('anon', v.oid, 'EXECUTE') OR has_function_privilege('service_role', v.oid, 'EXECUTE')
       OR NOT has_function_privilege('authenticated', v.oid, 'EXECUTE') THEN
        RAISE EXCEPTION 'Postflight: function EXECUTE privileges wrong';
    END IF;
END
$postflight$;

COMMIT;
