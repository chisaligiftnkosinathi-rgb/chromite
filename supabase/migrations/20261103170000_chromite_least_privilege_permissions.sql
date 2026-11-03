
BEGIN;

-- ============================================================
-- CHROMITE
-- Least-privilege permissions correction
--
-- Existing objects are owned by postgres.
-- This migration preserves tables, views, records and RLS.
-- ============================================================

-- 1. Schema access
GRANT USAGE ON SCHEMA public
TO anon, authenticated, service_role;

-- 2. Remove broad table-level privileges from existing objects.
-- Separate column-level grants are retained.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
FROM anon, authenticated, PUBLIC, service_role;

-- 3. Public directory views: SELECT only.
GRANT SELECT ON TABLE
    public.public_mines,
    public.public_mine_production,
    public.public_laboratories,
    public.public_lab_accreditation_scopes,
    public.public_sampling_providers,
    public.public_sampling_services
TO anon, authenticated, service_role;

-- 4. Backend service role: CRUD on application tables only.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.mines,
    public.mine_production_records,
    public.mine_legal_rights,
    public.mine_verification_evidence,
    public.laboratories,
    public.lab_accreditation_scopes,
    public.sampling_providers,
    public.sampling_provider_services,
    public.organizations,
    public.organization_memberships,
    public.platform_staff
TO service_role;

-- 5. Preserve existing narrow column-level permissions.
-- No broad table privileges are granted to anon or authenticated.
-- RLS policies continue to control row access.

-- 6. Tighten existing sequence permissions.
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
FROM anon, authenticated, PUBLIC, service_role;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
TO service_role;

-- ============================================================
-- FUTURE OBJECT DEFAULTS
-- Application objects are owned by postgres.
-- ============================================================

-- 7. Future tables
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
IN SCHEMA public
REVOKE ALL PRIVILEGES ON TABLES
FROM anon, authenticated, service_role, PUBLIC;

-- 8. Future sequences
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
IN SCHEMA public
REVOKE ALL PRIVILEGES ON SEQUENCES
FROM anon, authenticated, service_role, PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres
IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES
TO service_role;

-- 9. Future functions
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS
FROM anon, authenticated, service_role;

-- Remove PostgreSQL's implicit PUBLIC execute default
-- for functions created by postgres.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
REVOKE EXECUTE ON FUNCTIONS
FROM PUBLIC;

COMMIT;
