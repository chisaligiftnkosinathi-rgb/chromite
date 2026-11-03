
-- ============================================================
-- CHROMITE
-- Migration 1: Core directory, organisations and providers
--
-- LOCAL DEVELOPMENT ONLY.
-- Do not apply to production without review and approval.
--
-- Security model:
--   Public: published directory information only.
--   Customers: their own organisations and memberships.
--   Operations: authorised FastAPI backend workflows.
--   Verification: authorised verification workflows.
--
-- The service-role key must NEVER be exposed to a browser.
-- ============================================================

BEGIN;

-- ============================================================
-- 0. POSTGIS
-- ============================================================

CREATE SCHEMA IF NOT EXISTS extensions;

CREATE EXTENSION IF NOT EXISTS postgis
WITH SCHEMA extensions;

-- ============================================================
-- 1. PRIVATE SCHEMA AND TRIGGER FUNCTIONS
-- ============================================================

CREATE SCHEMA IF NOT EXISTS private;

REVOKE ALL ON SCHEMA private FROM PUBLIC;
REVOKE ALL ON SCHEMA private FROM anon, authenticated;

CREATE OR REPLACE FUNCTION private.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := pg_catalog.now();
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION private.set_updated_at()
FROM PUBLIC, anon, authenticated;

-- Derive the PostGIS point from the source coordinates.
-- Longitude is the first coordinate; latitude is the second.

CREATE OR REPLACE FUNCTION private.set_mine_location()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF NEW.latitude IS NULL OR NEW.longitude IS NULL THEN
        NEW.location := NULL;
    ELSE
        NEW.location :=
            extensions.ST_SetSRID(
                extensions.ST_MakePoint(
                    NEW.longitude,
                    NEW.latitude
                ),
                4326
            )::extensions.geography;
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION private.set_mine_location()
FROM PUBLIC, anon, authenticated;

-- ============================================================
-- 2. ORGANISATIONS
-- ============================================================

CREATE TABLE public.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_name TEXT NOT NULL
        CHECK (length(trim(organization_name)) > 0),

    organization_type TEXT NOT NULL
        CHECK (
            organization_type IN (
                'mine_owner',
                'mine_operator',
                'laboratory',
                'sampling_provider',
                'trader',
                'customer',
                'other'
            )
        ),

    registration_number TEXT,
    country_code CHAR(2) NOT NULL DEFAULT 'ZA',

    created_by UUID NOT NULL REFERENCES auth.users(id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_organizations_created_by
    ON public.organizations(created_by);

CREATE INDEX idx_organizations_type
    ON public.organizations(organization_type);

CREATE TRIGGER organizations_updated_at
BEFORE UPDATE ON public.organizations
FOR EACH ROW
EXECUTE FUNCTION private.set_updated_at();

-- ============================================================
-- 3. ORGANISATION MEMBERSHIPS
-- ============================================================

CREATE TABLE public.organization_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL
        REFERENCES public.organizations(id) ON DELETE CASCADE,

    user_id UUID NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,

    membership_role TEXT NOT NULL DEFAULT 'member'
        CHECK (
            membership_role IN ('owner', 'admin', 'member')
        ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (organization_id, user_id)
);

CREATE INDEX idx_org_memberships_user
    ON public.organization_memberships(user_id);

CREATE INDEX idx_org_memberships_org
    ON public.organization_memberships(organization_id);

-- ============================================================
-- 4. PLATFORM STAFF
-- ============================================================

CREATE TABLE public.platform_staff (
    user_id UUID PRIMARY KEY
        REFERENCES auth.users(id) ON DELETE CASCADE,

    staff_role TEXT NOT NULL
        CHECK (
            staff_role IN (
                'administrator',
                'verification_officer',
                'operations'
            )
        ),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.platform_staff IS
'Privileged staff registry. Provision through a trusted administrator process only.';

-- ============================================================
-- 5. CHROME MINE DIRECTORY
-- ============================================================

CREATE TABLE public.mines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    mine_name TEXT NOT NULL
        CHECK (length(trim(mine_name)) > 0),

    slug TEXT NOT NULL UNIQUE
        CHECK (length(trim(slug)) > 0),

    commodity TEXT NOT NULL DEFAULT 'chrome'
        CHECK (commodity = 'chrome'),

    province TEXT NOT NULL,
    district TEXT,
    nearest_town TEXT,

    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    location extensions.geography(Point, 4326),

    mine_type TEXT,

    operating_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (
            operating_status IN (
                'operating',
                'care_and_maintenance',
                'temporarily_closed',
                'closed',
                'under_development',
                'unknown'
            )
        ),

    owner_organization_id UUID
        REFERENCES public.organizations(id),

    operator_organization_id UUID
        REFERENCES public.organizations(id),

    publication_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (
            publication_status IN (
                'draft',
                'published',
                'archived'
            )
        ),

    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (
            verification_status IN (
                'unverified',
                'pending',
                'verified',
                'rejected',
                'expired'
            )
        ),

    public_description TEXT,

    source_name TEXT,
    source_url TEXT,
    source_reference TEXT,
    source_checked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (
        latitude IS NULL
        OR latitude BETWEEN -90 AND 90
    ),

    CHECK (
        longitude IS NULL
        OR longitude BETWEEN -180 AND 180
    ),

    CHECK (
        (latitude IS NULL AND longitude IS NULL)
        OR
        (latitude IS NOT NULL AND longitude IS NOT NULL)
    )
);

CREATE INDEX idx_mines_province
    ON public.mines(province);

CREATE INDEX idx_mines_district
    ON public.mines(district);

CREATE INDEX idx_mines_operating_status
    ON public.mines(operating_status);

CREATE INDEX idx_mines_publication_status
    ON public.mines(publication_status);

CREATE INDEX idx_mines_verification_status
    ON public.mines(verification_status);

CREATE INDEX idx_mines_location
    ON public.mines USING GIST(location);

CREATE INDEX idx_mines_owner
    ON public.mines(owner_organization_id);

CREATE INDEX idx_mines_operator
    ON public.mines(operator_organization_id);

CREATE TRIGGER mines_set_location
BEFORE INSERT OR UPDATE OF latitude, longitude
ON public.mines
FOR EACH ROW
EXECUTE FUNCTION private.set_mine_location();

CREATE TRIGGER mines_updated_at
BEFORE UPDATE ON public.mines
FOR EACH ROW
EXECUTE FUNCTION private.set_updated_at();

COMMENT ON COLUMN public.mines.location IS
'PostGIS geography point derived from latitude and longitude by trigger.';

COMMENT ON COLUMN public.mines.verification_status IS
'Directory-record verification status; not proof of a valid mining right.';

COMMENT ON COLUMN public.mines.publication_status IS
'Controls directory visibility and does not imply legal-right verification.';

-- ============================================================
-- 6. MINE LEGAL RIGHTS
-- ============================================================

CREATE TABLE public.mine_legal_rights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    mine_id UUID NOT NULL
        REFERENCES public.mines(id) ON DELETE CASCADE,

    right_reference TEXT NOT NULL,
    right_type TEXT NOT NULL,

    commodity TEXT NOT NULL DEFAULT 'chrome'
        CHECK (commodity = 'chrome'),

    holder_name TEXT,
    issuing_authority TEXT,

    right_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (
            right_status IN (
                'active',
                'suspended',
                'expired',
                'cancelled',
                'pending',
                'unknown'
            )
        ),

    effective_date DATE,
    expiry_date DATE,

    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (
            verification_status IN (
                'unverified',
                'pending',
                'verified',
                'rejected',
                'expired'
            )
        ),

    verification_notes TEXT,

    verified_by UUID REFERENCES auth.users(id),
    verified_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,

    source_name TEXT,
    source_url TEXT,
    source_reference TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (mine_id, right_reference),
    UNIQUE (id, mine_id),

    CHECK (
        expiry_date IS NULL
        OR effective_date IS NULL
        OR expiry_date >= effective_date
    )
);

CREATE INDEX idx_mine_rights_mine
    ON public.mine_legal_rights(mine_id);

CREATE INDEX idx_mine_rights_verification
    ON public.mine_legal_rights(verification_status);

CREATE INDEX idx_mine_rights_status
    ON public.mine_legal_rights(right_status);

CREATE TRIGGER mine_legal_rights_updated_at
BEFORE UPDATE ON public.mine_legal_rights
FOR EACH ROW
EXECUTE FUNCTION private.set_updated_at();

-- ============================================================
-- 7. MINE VERIFICATION EVIDENCE
-- ============================================================

CREATE TABLE public.mine_verification_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    mine_id UUID NOT NULL
        REFERENCES public.mines(id) ON DELETE CASCADE,

    legal_right_id UUID,

    evidence_type TEXT NOT NULL,
    document_name TEXT,

    storage_bucket TEXT NOT NULL DEFAULT 'mine-evidence',
    storage_path TEXT NOT NULL,

    source_name TEXT,
    source_url TEXT,
    document_reference TEXT,

    uploaded_by UUID REFERENCES auth.users(id),
    reviewed_by UUID REFERENCES auth.users(id),
    reviewed_at TIMESTAMPTZ,

    verification_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            verification_status IN (
                'pending',
                'accepted',
                'rejected',
                'superseded'
            )
        ),

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT evidence_right_belongs_to_mine
        FOREIGN KEY (legal_right_id, mine_id)
        REFERENCES public.mine_legal_rights(id, mine_id)
        ON DELETE SET NULL (legal_right_id)
);

CREATE INDEX idx_mine_evidence_mine
    ON public.mine_verification_evidence(mine_id);

CREATE INDEX idx_mine_evidence_right
    ON public.mine_verification_evidence(legal_right_id);

-- ============================================================
-- 8. MINE PRODUCTION RECORDS
-- ============================================================

CREATE TABLE public.mine_production_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    mine_id UUID NOT NULL
        REFERENCES public.mines(id) ON DELETE CASCADE,

    reporting_period_start DATE NOT NULL,
    reporting_period_end DATE NOT NULL,

    production_tonnes NUMERIC(18, 3) NOT NULL
        CHECK (production_tonnes >= 0),

    production_category TEXT NOT NULL DEFAULT 'chrome_ore'
        CHECK (
            production_category IN (
                'chrome_ore',
                'chrome_concentrate',
                'other'
            )
        ),

    production_stage TEXT NOT NULL DEFAULT 'unknown'
        CHECK (
            production_stage IN (
                'run_of_mine',
                'concentrate',
                'saleable_product',
                'unknown'
            )
        ),

    data_status TEXT NOT NULL DEFAULT 'reported'
        CHECK (
            data_status IN (
                'reported',
                'verified',
                'disputed',
                'estimated'
            )
        ),

    publication_status TEXT NOT NULL DEFAULT 'private'
        CHECK (
            publication_status IN ('private', 'published')
        ),

    source_name TEXT NOT NULL,
    source_url TEXT,
    source_reference TEXT,
    source_published_at TIMESTAMPTZ,

    verified_by UUID REFERENCES auth.users(id),
    verified_at TIMESTAMPTZ,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (
        reporting_period_end >= reporting_period_start
    )
);

CREATE INDEX idx_production_mine
    ON public.mine_production_records(mine_id);

CREATE INDEX idx_production_period
    ON public.mine_production_records(
        reporting_period_start,
        reporting_period_end
    );

CREATE INDEX idx_production_publication
    ON public.mine_production_records(publication_status);

CREATE INDEX idx_production_verification
    ON public.mine_production_records(data_status);

-- ============================================================
-- 9. LABORATORIES
-- ============================================================

CREATE TABLE public.laboratories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID
        REFERENCES public.organizations(id),

    laboratory_name TEXT NOT NULL
        CHECK (length(trim(laboratory_name)) > 0),

    country_code CHAR(2) NOT NULL DEFAULT 'ZA',

    province TEXT,
    city TEXT,
    physical_address TEXT,

    -- Private by default. Excluded from public views and client grants.
    contact_email TEXT,
    contact_phone TEXT,
    website_url TEXT,

    publication_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (
            publication_status IN ('draft', 'published', 'archived')
        ),

    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (
            verification_status IN (
                'unverified',
                'pending',
                'verified',
                'rejected'
            )
        ),

    source_name TEXT,
    source_url TEXT,
    source_checked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_laboratories_publication
    ON public.laboratories(publication_status);

CREATE INDEX idx_laboratories_province
    ON public.laboratories(province);

CREATE INDEX idx_laboratories_organization
    ON public.laboratories(organization_id);

CREATE TRIGGER laboratories_updated_at
BEFORE UPDATE ON public.laboratories
FOR EACH ROW
EXECUTE FUNCTION private.set_updated_at();

-- ============================================================
-- 10. LABORATORY ACCREDITATION SCOPES
-- ============================================================

CREATE TABLE public.lab_accreditation_scopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    laboratory_id UUID NOT NULL
        REFERENCES public.laboratories(id) ON DELETE CASCADE,

    accreditation_body TEXT NOT NULL,
    accreditation_number TEXT NOT NULL,
    certificate_reference TEXT,

    standard TEXT NOT NULL DEFAULT 'ISO/IEC 17025:2017',

    scope_title TEXT NOT NULL,
    material_matrix TEXT NOT NULL,
    analyte_or_parameter TEXT NOT NULL,
    test_method TEXT NOT NULL,

    scope_valid_from DATE,
    scope_valid_until DATE,

    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (
            verification_status IN (
                'unverified',
                'pending',
                'verified',
                'rejected',
                'expired'
            )
        ),

    source_name TEXT,
    source_url TEXT,
    source_reference TEXT,
    last_checked_at TIMESTAMPTZ,

    verified_by UUID REFERENCES auth.users(id),
    verified_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (
        scope_valid_until IS NULL
        OR scope_valid_from IS NULL
        OR scope_valid_until >= scope_valid_from
    )
);

CREATE INDEX idx_lab_scopes_lab
    ON public.lab_accreditation_scopes(laboratory_id);

CREATE INDEX idx_lab_scopes_parameter
    ON public.lab_accreditation_scopes(analyte_or_parameter);

CREATE INDEX idx_lab_scopes_verification
    ON public.lab_accreditation_scopes(verification_status);

CREATE INDEX idx_lab_scopes_accreditation_number
    ON public.lab_accreditation_scopes(accreditation_number);

-- ============================================================
-- 11. SAMPLING PROVIDERS
-- ============================================================

CREATE TABLE public.sampling_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID
        REFERENCES public.organizations(id),

    provider_name TEXT NOT NULL
        CHECK (length(trim(provider_name)) > 0),

    country_code CHAR(2) NOT NULL DEFAULT 'ZA',

    province TEXT,
    city TEXT,
    physical_address TEXT,

    -- Private by default.
    contact_email TEXT,
    contact_phone TEXT,
    website_url TEXT,

    service_description TEXT,

    publication_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (
            publication_status IN ('draft', 'published', 'archived')
        ),

    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (
            verification_status IN (
                'unverified',
                'pending',
                'verified',
                'rejected'
            )
        ),

    source_name TEXT,
    source_url TEXT,
    source_checked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sampling_providers_publication
    ON public.sampling_providers(publication_status);

CREATE INDEX idx_sampling_providers_province
    ON public.sampling_providers(province);

CREATE INDEX idx_sampling_providers_organization
    ON public.sampling_providers(organization_id);

CREATE TRIGGER sampling_providers_updated_at
BEFORE UPDATE ON public.sampling_providers
FOR EACH ROW
EXECUTE FUNCTION private.set_updated_at();

-- ============================================================
-- 12. SAMPLING PROVIDER SERVICES
-- ============================================================

CREATE TABLE public.sampling_provider_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    provider_id UUID NOT NULL
        REFERENCES public.sampling_providers(id) ON DELETE CASCADE,

    service_name TEXT NOT NULL,
    material_type TEXT NOT NULL DEFAULT 'chrome_ore',
    service_description TEXT,

    service_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (
            service_status IN (
                'unverified',
                'verified',
                'unavailable'
            )
        ),

    publication_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (
            publication_status IN ('draft', 'published', 'archived')
        ),

    source_name TEXT,
    source_url TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_provider_services_provider
    ON public.sampling_provider_services(provider_id);

CREATE INDEX idx_provider_services_publication
    ON public.sampling_provider_services(publication_status);

-- ============================================================
-- 13. ENABLE RLS
-- ============================================================

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mine_legal_rights ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mine_verification_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mine_production_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.laboratories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lab_accreditation_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sampling_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sampling_provider_services ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 14. ORGANISATION POLICIES
-- ============================================================

CREATE POLICY organization_member_read
ON public.organizations
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.organization_memberships AS m
        WHERE m.organization_id = organizations.id
          AND m.user_id = (SELECT auth.uid())
    )
);

CREATE POLICY organization_creator_read
ON public.organizations
FOR SELECT
TO authenticated
USING (created_by = (SELECT auth.uid()));

CREATE POLICY organization_creator_insert
ON public.organizations
FOR INSERT
TO authenticated
WITH CHECK (created_by = (SELECT auth.uid()));

CREATE POLICY organization_owner_update
ON public.organizations
FOR UPDATE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.organization_memberships AS m
        WHERE m.organization_id = organizations.id
          AND m.user_id = (SELECT auth.uid())
          AND m.membership_role = 'owner'
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.organization_memberships AS m
        WHERE m.organization_id = organizations.id
          AND m.user_id = (SELECT auth.uid())
          AND m.membership_role = 'owner'
    )
);

CREATE POLICY membership_read_own
ON public.organization_memberships
FOR SELECT
TO authenticated
USING (user_id = (SELECT auth.uid()));

CREATE POLICY membership_creator_join
ON public.organization_memberships
FOR INSERT
TO authenticated
WITH CHECK (
    user_id = (SELECT auth.uid())
    AND membership_role IN ('owner', 'member')
    AND EXISTS (
        SELECT 1
        FROM public.organizations AS o
        WHERE o.id = organization_memberships.organization_id
          AND o.created_by = (SELECT auth.uid())
    )
);

-- No client-side membership update/delete policies.

-- ============================================================
-- 15. PUBLIC DIRECTORY POLICIES
-- ============================================================

CREATE POLICY mines_public_read
ON public.mines
FOR SELECT
TO anon, authenticated
USING (publication_status = 'published');

CREATE POLICY production_public_read
ON public.mine_production_records
FOR SELECT
TO anon, authenticated
USING (
    publication_status = 'published'
    AND data_status = 'verified'
    AND EXISTS (
        SELECT 1
        FROM public.mines AS m
        WHERE m.id = mine_production_records.mine_id
          AND m.publication_status = 'published'
    )
);

CREATE POLICY laboratories_public_read
ON public.laboratories
FOR SELECT
TO anon, authenticated
USING (publication_status = 'published');

CREATE POLICY lab_scopes_public_read
ON public.lab_accreditation_scopes
FOR SELECT
TO anon, authenticated
USING (
    verification_status = 'verified'
    AND (
        scope_valid_from IS NULL
        OR scope_valid_from <= CURRENT_DATE
    )
    AND (
        scope_valid_until IS NULL
        OR scope_valid_until >= CURRENT_DATE
    )
    AND EXISTS (
        SELECT 1
        FROM public.laboratories AS l
        WHERE l.id = lab_accreditation_scopes.laboratory_id
          AND l.publication_status = 'published'
    )
);

CREATE POLICY sampling_providers_public_read
ON public.sampling_providers
FOR SELECT
TO anon, authenticated
USING (publication_status = 'published');

CREATE POLICY sampling_services_public_read
ON public.sampling_provider_services
FOR SELECT
TO anon, authenticated
USING (
    publication_status = 'published'
    AND service_status = 'verified'
    AND EXISTS (
        SELECT 1
        FROM public.sampling_providers AS p
        WHERE p.id = sampling_provider_services.provider_id
          AND p.publication_status = 'published'
    )
);

-- No direct anon/authenticated policies on legal rights, evidence,
-- or private operational records.

-- ============================================================
-- 16. PUBLIC DIRECTORY VIEWS
-- ============================================================

CREATE VIEW public.public_mines
WITH (security_invoker = true)
AS
SELECT
    id,
    mine_name,
    slug,
    commodity,
    province,
    district,
    nearest_town,
    latitude,
    longitude,
    mine_type,
    operating_status,
    verification_status,
    public_description,
    source_name,
    source_url,
    source_checked_at
FROM public.mines
WHERE publication_status = 'published';

CREATE VIEW public.public_mine_production
WITH (security_invoker = true)
AS
SELECT
    p.id,
    p.mine_id,
    p.reporting_period_start,
    p.reporting_period_end,
    p.production_tonnes,
    p.production_category,
    p.production_stage,
    p.data_status,
    p.source_name,
    p.source_url,
    p.source_published_at
FROM public.mine_production_records AS p
JOIN public.mines AS m
    ON m.id = p.mine_id
WHERE p.publication_status = 'published'
  AND p.data_status = 'verified'
  AND m.publication_status = 'published';

CREATE VIEW public.public_laboratories
WITH (security_invoker = true)
AS
SELECT
    id,
    laboratory_name,
    country_code,
    province,
    city,
    physical_address,
    website_url,
    verification_status
FROM public.laboratories
WHERE publication_status = 'published';

CREATE VIEW public.public_lab_accreditation_scopes
WITH (security_invoker = true)
AS
SELECT
    s.id,
    s.laboratory_id,
    s.accreditation_body,
    s.accreditation_number,
    s.certificate_reference,
    s.standard,
    s.scope_title,
    s.material_matrix,
    s.analyte_or_parameter,
    s.test_method,
    s.scope_valid_from,
    s.scope_valid_until,
    s.verification_status
FROM public.lab_accreditation_scopes AS s
JOIN public.laboratories AS l
    ON l.id = s.laboratory_id
WHERE s.verification_status = 'verified'
  AND (
      s.scope_valid_from IS NULL
      OR s.scope_valid_from <= CURRENT_DATE
  )
  AND (
      s.scope_valid_until IS NULL
      OR s.scope_valid_until >= CURRENT_DATE
  )
  AND l.publication_status = 'published';

CREATE VIEW public.public_sampling_providers
WITH (security_invoker = true)
AS
SELECT
    id,
    provider_name,
    country_code,
    province,
    city,
    physical_address,
    website_url,
    service_description,
    verification_status
FROM public.sampling_providers
WHERE publication_status = 'published';

CREATE VIEW public.public_sampling_services
WITH (security_invoker = true)
AS
SELECT
    s.id,
    s.provider_id,
    s.service_name,
    s.material_type,
    s.service_description,
    s.service_status
FROM public.sampling_provider_services AS s
JOIN public.sampling_providers AS p
    ON p.id = s.provider_id
WHERE s.publication_status = 'published'
  AND s.service_status = 'verified'
  AND p.publication_status = 'published';

-- ============================================================
-- 17. SCHEMA USAGE
-- ============================================================

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- Only the trusted backend needs PostGIS schema access for
-- privileged mine writes and spatial queries.
GRANT USAGE ON SCHEMA extensions TO service_role;

-- ============================================================
-- 18. ORGANISATION CLIENT PRIVILEGES
-- ============================================================

GRANT SELECT (
    id,
    organization_name,
    organization_type,
    registration_number,
    country_code,
    created_by,
    created_at,
    updated_at
)
ON public.organizations TO authenticated;

GRANT INSERT (
    organization_name,
    organization_type,
    registration_number,
    country_code,
    created_by
)
ON public.organizations TO authenticated;

GRANT UPDATE (
    organization_name,
    organization_type,
    registration_number,
    country_code
)
ON public.organizations TO authenticated;

GRANT SELECT (
    id,
    organization_id,
    user_id,
    membership_role,
    created_at
)
ON public.organization_memberships TO authenticated;

GRANT INSERT (
    organization_id,
    user_id,
    membership_role
)
ON public.organization_memberships TO authenticated;

-- ============================================================
-- 19. MINIMUM DIRECTORY COLUMN PRIVILEGES
-- ============================================================

GRANT SELECT (
    id,
    mine_name,
    slug,
    commodity,
    province,
    district,
    nearest_town,
    latitude,
    longitude,
    mine_type,
    operating_status,
    publication_status,
    verification_status,
    public_description,
    source_name,
    source_url,
    source_checked_at
)
ON public.mines TO anon, authenticated;

GRANT SELECT (
    id,
    mine_id,
    reporting_period_start,
    reporting_period_end,
    production_tonnes,
    production_category,
    production_stage,
    data_status,
    publication_status,
    source_name,
    source_url,
    source_published_at
)
ON public.mine_production_records TO anon, authenticated;

-- Required by the production view join and RLS predicate.
GRANT SELECT (id, publication_status)
ON public.mines TO anon, authenticated;

GRANT SELECT (
    id,
    laboratory_name,
    country_code,
    province,
    city,
    physical_address,
    website_url,
    publication_status,
    verification_status
)
ON public.laboratories TO anon, authenticated;

GRANT SELECT (
    id,
    laboratory_id,
    accreditation_body,
    accreditation_number,
    certificate_reference,
    standard,
    scope_title,
    material_matrix,
    analyte_or_parameter,
    test_method,
    scope_valid_from,
    scope_valid_until,
    verification_status
)
ON public.lab_accreditation_scopes TO anon, authenticated;

GRANT SELECT (
    id,
    provider_name,
    country_code,
    province,
    city,
    physical_address,
    website_url,
    service_description,
    publication_status,
    verification_status
)
ON public.sampling_providers TO anon, authenticated;

GRANT SELECT (
    id,
    provider_id,
    service_name,
    material_type,
    service_description,
    service_status,
    publication_status
)
ON public.sampling_provider_services TO anon, authenticated;

-- ============================================================
-- 20. PUBLIC VIEW PRIVILEGES
-- ============================================================

GRANT SELECT ON
    public.public_mines,
    public.public_mine_production,
    public.public_laboratories,
    public.public_lab_accreditation_scopes,
    public.public_sampling_providers,
    public.public_sampling_services
TO anon, authenticated;

-- ============================================================
-- 21. TRUSTED BACKEND PRIVILEGES
--
-- service_role bypasses RLS. FastAPI must validate the user's
-- JWT and role before using privileged operations.
-- Never expose the service-role key to clients.
-- ============================================================

GRANT ALL PRIVILEGES ON
    public.organizations,
    public.organization_memberships,
    public.platform_staff,
    public.mines,
    public.mine_legal_rights,
    public.mine_verification_evidence,
    public.mine_production_records,
    public.laboratories,
    public.lab_accreditation_scopes,
    public.sampling_providers,
    public.sampling_provider_services
TO service_role;

GRANT SELECT ON
    public.public_mines,
    public.public_mine_production,
    public.public_laboratories,
    public.public_lab_accreditation_scopes,
    public.public_sampling_providers,
    public.public_sampling_services
TO service_role;

COMMIT;

-- ============================================================
-- END OF CHROMITE MIGRATION 1
-- ============================================================
