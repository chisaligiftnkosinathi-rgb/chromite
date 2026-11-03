-- ============================================================
-- CHROMITE — self-checking probe for a LOCAL Supabase stack
-- (or the local replay cluster). Run as supabase_admin AFTER
-- migrations 1, 2 and the proposed consolidated migration.
-- Raises an exception on the first failed check. Everything is
-- rolled back at the end; only synthetic test data is used.
-- NEVER run against the hosted project.
-- ============================================================
\set ON_ERROR_STOP on
BEGIN;

CREATE FUNCTION pg_temp.run_as(p_role TEXT, p_sub TEXT, p_sql TEXT)
RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE v TEXT;
BEGIN
    BEGIN
        PERFORM set_config('request.jwt.claim.sub', coalesce(p_sub, ''), true);
        PERFORM set_config('role', p_role, true);
        EXECUTE p_sql INTO v;
        PERFORM set_config('role', 'none', true);
        RETURN coalesce(v, 'ok');
    EXCEPTION WHEN OTHERS THEN
        RETURN 'ERR:' || SQLSTATE;
    END;
END $$;

CREATE FUNCTION pg_temp.check(p_label TEXT, p_actual TEXT, p_expected TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF p_actual IS DISTINCT FROM p_expected THEN
        RAISE EXCEPTION 'FAIL: % (expected %, got %)', p_label, p_expected, p_actual;
    END IF;
    RAISE NOTICE 'PASS: %', p_label;
END $$;

INSERT INTO auth.users (id) VALUES
  ('a1111111-1111-4111-8111-111111111111'),
  ('a2222222-2222-4222-8222-222222222222');

DO $probe$
DECLARE
    u1 CONSTANT TEXT := 'a1111111-1111-4111-8111-111111111111';
    u2 CONSTANT TEXT := 'a2222222-2222-4222-8222-222222222222';
    v_org TEXT;
    v TEXT;
BEGIN
    -- Public directory
    FOREACH v IN ARRAY ARRAY['public_mines','public_mine_production','public_laboratories',
                             'public_lab_accreditation_scopes','public_sampling_providers',
                             'public_sampling_services'] LOOP
        PERFORM pg_temp.check('anon reads ' || v,
            (pg_temp.run_as('anon', NULL, format('SELECT count(*)::text FROM public.%I', v))
                NOT LIKE 'ERR:%')::text, 'true');
    END LOOP;
    PERFORM pg_temp.check('anon denied laboratories.contact_email',
        pg_temp.run_as('anon', NULL, 'SELECT contact_email FROM public.laboratories LIMIT 1'), 'ERR:42501');
    PERFORM pg_temp.check('anon denied mine_legal_rights',
        pg_temp.run_as('anon', NULL, 'SELECT count(*) FROM public.mine_legal_rights'), 'ERR:42501');
    PERFORM pg_temp.check('authenticated denied platform_staff',
        pg_temp.run_as('authenticated', u1, 'SELECT count(*) FROM public.platform_staff'), 'ERR:42501');

    -- Onboarding and isolation
    v_org := pg_temp.run_as('authenticated', u1, format(
        $q$INSERT INTO public.organizations (organization_name, organization_type, created_by)
           VALUES ('SYNTHETIC PROBE ORG', 'customer', %L) RETURNING id::text$q$, u1));
    PERFORM pg_temp.check('user creates organisation', (v_org NOT LIKE 'ERR:%')::text, 'true');
    PERFORM pg_temp.check('creator adds own owner membership',
        pg_temp.run_as('authenticated', u1, format(
            $q$INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)
               VALUES (%L, %L, 'owner') RETURNING 'ok'$q$, v_org, u1)), 'ok');
    PERFORM pg_temp.check('creator sees own org',
        pg_temp.run_as('authenticated', u1, 'SELECT count(*)::text FROM public.organizations'), '1');
    PERFORM pg_temp.check('other user sees no orgs',
        pg_temp.run_as('authenticated', u2, 'SELECT count(*)::text FROM public.organizations'), '0');
    PERFORM pg_temp.check('other user cannot join',
        pg_temp.run_as('authenticated', u2, format(
            $q$INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)
               VALUES (%L, %L, 'owner')$q$, v_org, u2)), 'ERR:42501');
    PERFORM pg_temp.check('owner cannot change organization_type',
        pg_temp.run_as('authenticated', u1,
            $q$UPDATE public.organizations SET organization_type = 'laboratory'$q$), 'ERR:42501');
    PERFORM pg_temp.check('anon cannot call private helper',
        pg_temp.run_as('anon', NULL, 'SELECT private.is_org_member(gen_random_uuid())::text'), 'ERR:42501');

    -- Helper function properties
    PERFORM pg_temp.check('private helpers: secdef, empty search_path, owner postgres',
        (SELECT count(*)::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
          WHERE n.nspname = 'private'
            AND p.proname IN ('is_org_member','is_org_owner','is_org_creator','audit_log_guard')
            AND p.prosecdef AND p.proconfig = ARRAY['search_path=""']
            AND pg_get_userbyid(p.proowner) = 'postgres'), '4');

    -- Audit log
    PERFORM pg_temp.check('service_role inserts audit',
        pg_temp.run_as('service_role', NULL, format(
            $q$INSERT INTO public.platform_audit_logs (action, outcome, actor_user_id, metadata)
               VALUES ('probe.synthetic_event', 'success', %L, '{"test_data": true}') RETURNING 'ok'$q$, u2)), 'ok');
    PERFORM pg_temp.check('service_role cannot update audit',
        pg_temp.run_as('service_role', NULL, $q$UPDATE public.platform_audit_logs SET action = 'x'$q$), 'ERR:42501');
    PERFORM pg_temp.check('table owner blocked by guard (update)',
        pg_temp.run_as('postgres', NULL, $q$UPDATE public.platform_audit_logs SET action = 'x'$q$), 'ERR:42501');
    PERFORM pg_temp.check('table owner blocked by guard (delete)',
        pg_temp.run_as('postgres', NULL, 'DELETE FROM public.platform_audit_logs'), 'ERR:42501');
    PERFORM pg_temp.check('manual actor nullification rejected while user exists',
        pg_temp.run_as('postgres', NULL, 'UPDATE public.platform_audit_logs SET actor_user_id = NULL'), 'ERR:42501');
    PERFORM pg_temp.check('auth user deletion succeeds',
        pg_temp.run_as('supabase_auth_admin', NULL, format(
            'DELETE FROM auth.users WHERE id = %L RETURNING %L', u2, 'ok')), 'ok');
    PERFORM pg_temp.check('audit row kept with actor nulled',
        (SELECT count(*)::text FROM public.platform_audit_logs
          WHERE action = 'probe.synthetic_event' AND actor_user_id IS NULL), '1');
END
$probe$;

\echo 'ALL PROBES PASSED (rolling back synthetic data)'
ROLLBACK;
