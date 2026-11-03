"""
Local PostgreSQL replay tests for Chromite migrations.

These tests NEVER contact hosted Supabase. They need a throwaway local
PostgreSQL 15+ cluster with PostGIS whose superuser is named
``supabase_admin``, supplied through:

    CHROMITE_REPLAY_ADMIN_DSN="host=/tmp port=5434 user=supabase_admin dbname=postgres"

Without that variable every test here is skipped.

The stand-in reproduces Supabase's roles (postgres as a NON-superuser
table owner, anon/authenticated/service_role, supabase_auth_admin owning
auth.users) and auth.uid(). It is not a full Supabase stack; the
real local-stack test (tools/db/local-supabase-stack-test.ps1) is still
required before any hosted application.

All data inserted is synthetic and labelled as test data.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import errors  # noqa: E402

ADMIN_DSN = os.environ.get("CHROMITE_REPLAY_ADMIN_DSN")
pytestmark = pytest.mark.skipif(
    not ADMIN_DSN, reason="CHROMITE_REPLAY_ADMIN_DSN not set (local replay cluster)"
)

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = Path(__file__).resolve().parent / "sql"
M1 = ROOT / "supabase/migrations/20261103142214_initial_chromite_schema.sql"
M2 = ROOT / "supabase/migrations/20261103170000_chromite_least_privilege_permissions.sql"
FWD = ROOT / "supabase/migrations-proposed/20261104090000_consolidated_grants_rls_superadmin_audit.sql"
RB = ROOT / "supabase/migrations-proposed/20261104090000_consolidated_grants_rls_superadmin_audit.ROLLBACK.sql"

U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"
U3 = "33333333-3333-3333-3333-333333333333"

PUBLIC_VIEWS = [
    "public_mines",
    "public_mine_production",
    "public_laboratories",
    "public_lab_accreditation_scopes",
    "public_sampling_providers",
    "public_sampling_services",
]


# ----------------------------------------------------------------- helpers

def _dsn(dbname: str, user: str) -> str:
    parts = dict(p.split("=", 1) for p in ADMIN_DSN.split())
    parts.update(dbname=dbname, user=user)
    return " ".join(f"{k}={v}" for k, v in parts.items())


def _exec_file(conn, path: Path) -> None:
    conn.execute(path.read_text(encoding="utf-8"))


class Replay:
    """A fresh database built from a chosen list of migrations."""

    def __init__(self, migrations: list[Path], postgres_bypassrls: bool = True):
        self.name = f"replay_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            _exec_file(admin, SQL_DIR / "stand_in_cluster.sql")
            admin.execute(
                f"ALTER ROLE postgres {'BYPASSRLS' if postgres_bypassrls else 'NOBYPASSRLS'}"
            )
            admin.execute(f'CREATE DATABASE "{self.name}" OWNER postgres')
        with psycopg.connect(_dsn(self.name, "supabase_admin"), autocommit=True) as c:
            _exec_file(c, SQL_DIR / "stand_in_database.sql")
            c.execute("SET ROLE supabase_auth_admin")
            for u in (U1, U2, U3):
                c.execute("INSERT INTO auth.users VALUES (%s)", (u,))
        for m in migrations:
            self.apply(m)
        self._seed()

    def apply(self, path: Path) -> None:
        # Applied as the non-superuser 'postgres' role, as on hosted Supabase.
        with psycopg.connect(_dsn(self.name, "postgres"), autocommit=True) as c:
            _exec_file(c, path)

    def _seed(self) -> None:
        with self.owner() as c:
            c.execute(
                """
                INSERT INTO public.mines (mine_name, slug, province, latitude, longitude,
                                          publication_status, source_name)
                VALUES ('SYNTHETIC TEST MINE A', 'test-a', 'Limpopo', -24.5, 30.1,
                        'published', 'TEST DATA'),
                       ('SYNTHETIC TEST MINE B (draft)', 'test-b', 'North West', -25.6, 27.3,
                        'draft', 'TEST DATA');
                INSERT INTO public.laboratories (laboratory_name, publication_status, contact_email)
                VALUES ('SYNTHETIC TEST LAB', 'published', 'private@test.invalid');
                """
            )

    def owner(self):
        return psycopg.connect(_dsn(self.name, "postgres"), autocommit=True)

    def auth_admin(self):
        return psycopg.connect(_dsn(self.name, "supabase_auth_admin"), autocommit=True)

    def as_role(self, role: str, sub: str | None = None):
        """Connection whose next transaction runs as an API role."""
        conn = psycopg.connect(_dsn(self.name, "postgres"))
        conn.execute(f"SET ROLE {role}")
        if sub:
            conn.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (sub,))
        return conn

    def dump_schema(self) -> str:
        parts = dict(p.split("=", 1) for p in ADMIN_DSN.split())
        cmd = ["pg_dump", "-s", "-n", "public", "-n", "private",
               "-h", parts.get("host", "localhost"), "-p", parts.get("port", "5432"),
               "-U", "supabase_admin", self.name]
        out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
        # pg_dump >= 17.6/16.10 emits a random \\restrict token per dump; ignore it.
        return "\n".join(l for l in out.splitlines()
                         if not l.startswith(("\\restrict", "\\unrestrict")))

    def drop(self) -> None:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')


def _create_org(db: Replay, sub: str, name: str = "SYNTHETIC ORG") -> str:
    with db.as_role("authenticated", sub) as c:
        org_id = c.execute(
            "INSERT INTO public.organizations (organization_name, organization_type, created_by)"
            " VALUES (%s, 'customer', %s) RETURNING id",
            (name, sub),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)"
            " VALUES (%s, %s, 'owner')",
            (org_id, sub),
        )
        c.commit()
    return str(org_id)


@pytest.fixture(params=[True, False], ids=["postgres_bypassrls", "postgres_nobypassrls"])
def migrated(request):
    db = Replay([M1, M2, FWD], postgres_bypassrls=request.param)
    yield db
    db.drop()


@pytest.fixture
def hosted_today():
    db = Replay([M1, M2])
    yield db
    db.drop()


# ------------------------------------------- state today (M1 + M2): defects

@pytest.mark.parametrize("view", PUBLIC_VIEWS)
def test_hosted_state_public_views_are_denied(hosted_today, view):
    with hosted_today.as_role("anon") as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(f"SELECT count(*) FROM public.{view}")


def test_hosted_state_org_creation_is_denied(hosted_today):
    with hosted_today.as_role("authenticated", U1) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(
            "INSERT INTO public.organizations (organization_name, organization_type, created_by)"
            " VALUES ('X', 'customer', %s)", (U1,)
        )


def test_initial_schema_has_rls_recursion_bug():
    db = Replay([M1])
    try:
        with db.as_role("authenticated", U1) as c:
            org = c.execute(
                "INSERT INTO public.organizations (organization_name, organization_type, created_by)"
                " VALUES ('X', 'customer', %s) RETURNING id", (U1,)
            ).fetchone()[0]
            with pytest.raises(errors.InvalidObjectDefinition, match="infinite recursion"):
                c.execute(
                    "INSERT INTO public.organization_memberships"
                    " (organization_id, user_id, membership_role) VALUES (%s, %s, 'owner')",
                    (org, U1),
                )
    finally:
        db.drop()


# --------------------------------------------- after consolidated migration

@pytest.mark.parametrize("view", PUBLIC_VIEWS)
def test_public_views_readable_by_anon(migrated, view):
    with migrated.as_role("anon") as c:
        c.execute(f"SELECT * FROM public.{view}")


def test_public_mines_hides_drafts(migrated):
    with migrated.as_role("anon") as c:
        names = [r[0] for r in c.execute("SELECT mine_name FROM public.public_mines")]
    assert names == ["SYNTHETIC TEST MINE A"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT contact_email FROM public.laboratories",
        "SELECT owner_organization_id FROM public.mines",
        "SELECT * FROM public.mine_legal_rights",
        "SELECT * FROM public.mine_verification_evidence",
        "SELECT * FROM public.platform_staff",
        "SELECT * FROM public.platform_audit_logs",
    ],
)
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_private_data_denied(migrated, role, sql):
    with migrated.as_role(role, U1) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(sql)


def test_onboarding_creates_org_and_owner_membership(migrated):
    org = _create_org(migrated, U1)
    with migrated.as_role("authenticated", U1) as c:
        assert c.execute("SELECT count(*) FROM public.organizations").fetchone()[0] == 1
        role = c.execute(
            "SELECT membership_role FROM public.organization_memberships WHERE organization_id = %s",
            (org,),
        ).fetchone()[0]
    assert role == "owner"


def test_org_isolation_between_users(migrated):
    _create_org(migrated, U1)
    with migrated.as_role("authenticated", U2) as c:
        assert c.execute("SELECT count(*) FROM public.organizations").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM public.organization_memberships").fetchone()[0] == 0


def test_non_creator_cannot_join_org(migrated):
    org = _create_org(migrated, U1)
    with migrated.as_role("authenticated", U2) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(
            "INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)"
            " VALUES (%s, %s, 'owner')", (org, U2)
        )


def test_creator_cannot_add_other_users_directly(migrated):
    org = _create_org(migrated, U1)
    with migrated.as_role("authenticated", U1) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(
            "INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)"
            " VALUES (%s, %s, 'member')", (org, U3)
        )


def test_creator_cannot_add_self_twice_or_as_member(migrated):
    org = _create_org(migrated, U1)
    with migrated.as_role("authenticated", U1) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(
            "INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)"
            " VALUES (%s, %s, 'member')", (org, U1)
        )


def test_member_reads_org_but_cannot_rename(migrated):
    org = _create_org(migrated, U1)
    with migrated.owner() as c:  # backend invite workflow stand-in
        c.execute(
            "INSERT INTO public.organization_memberships (organization_id, user_id, membership_role)"
            " VALUES (%s, %s, 'member')", (org, U2)
        )
    with migrated.as_role("authenticated", U2) as c:
        assert c.execute("SELECT count(*) FROM public.organizations").fetchone()[0] == 1
        cur = c.execute("UPDATE public.organizations SET organization_name = 'HACKED'")
        assert cur.rowcount == 0


def test_owner_can_rename(migrated):
    _create_org(migrated, U1)
    with migrated.as_role("authenticated", U1) as c:
        cur = c.execute("UPDATE public.organizations SET organization_name = 'SYNTHETIC RENAMED'")
        assert cur.rowcount == 1


def test_owner_cannot_change_organization_type(migrated):
    _create_org(migrated, U1)
    with migrated.as_role("authenticated", U1) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute("UPDATE public.organizations SET organization_type = 'laboratory'")


def test_creator_insert_policy_unchanged(hosted_today, migrated):
    q = ("SELECT policyname, cmd, roles::text, qual, with_check FROM pg_policies"
         " WHERE schemaname='public' AND policyname IN"
         " ('organization_creator_insert','organization_creator_read','membership_read_own')"
         " ORDER BY 1")
    with hosted_today.owner() as a, migrated.owner() as b:
        assert a.execute(q).fetchall() == b.execute(q).fetchall()


# --------------------------------------------------- helper function checks

def test_helper_function_properties(migrated):
    with migrated.owner() as c:
        rows = c.execute(
            """
            SELECT p.proname, p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner),
                   has_function_privilege('anon', p.oid, 'EXECUTE'),
                   has_function_privilege('authenticated', p.oid, 'EXECUTE'),
                   has_function_privilege('service_role', p.oid, 'EXECUTE')
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'private' ORDER BY 1
            """
        ).fetchall()
    by_name = {r[0]: r for r in rows}
    for fn in ("is_org_member", "is_org_owner", "is_org_creator"):
        _, secdef, cfg, owner, anon_x, auth_x, svc_x = by_name[fn]
        assert secdef and cfg == ['search_path=""'] and owner == "postgres"
        assert (anon_x, auth_x, svc_x) == (False, True, False)
    _, secdef, cfg, owner, anon_x, auth_x, svc_x = by_name["audit_log_guard"]
    assert secdef and cfg == ['search_path=""'] and owner == "postgres"
    assert (anon_x, auth_x, svc_x) == (False, False, False)


def test_private_schema_owner_and_usage(migrated):
    with migrated.owner() as c:
        owner, anon_u, auth_u = c.execute(
            "SELECT pg_get_userbyid(nspowner), has_schema_privilege('anon', oid, 'USAGE'),"
            " has_schema_privilege('authenticated', oid, 'USAGE')"
            " FROM pg_namespace WHERE nspname = 'private'"
        ).fetchone()
    assert (owner, anon_u, auth_u) == ("postgres", False, True)


def test_anon_cannot_call_helpers(migrated):
    with migrated.as_role("anon") as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute("SELECT private.is_org_member(gen_random_uuid())")


def test_helpers_only_describe_the_caller(migrated):
    org = _create_org(migrated, U1)
    with migrated.as_role("authenticated", U2) as c:
        assert c.execute("SELECT private.is_org_member(%s)", (org,)).fetchone()[0] is False
    with migrated.as_role("authenticated", U1) as c:
        assert c.execute("SELECT private.is_org_owner(%s)", (org,)).fetchone()[0] is True


# --------------------------------------------------------- staff + preflight

def test_staff_roles_constraint(migrated):
    with migrated.owner() as c:
        c.execute("INSERT INTO public.platform_staff (user_id, staff_role) VALUES (%s, 'finance_officer')", (U1,))
        c.execute("INSERT INTO public.platform_staff (user_id, staff_role) VALUES (%s, 'superadmin')", (U2,))
        with pytest.raises(errors.CheckViolation):
            c.execute("INSERT INTO public.platform_staff (user_id, staff_role) VALUES (%s, 'god')", (U3,))


def test_preflight_rejects_unexpected_staff_role():
    db = Replay([M1, M2])
    try:
        with db.owner() as c:
            c.execute("ALTER TABLE public.platform_staff DROP CONSTRAINT platform_staff_staff_role_check")
            c.execute("INSERT INTO public.platform_staff VALUES (%s, 'legacy_role')", (U1,))
            c.execute("ALTER TABLE public.platform_staff ADD CONSTRAINT platform_staff_staff_role_check"
                      " CHECK (staff_role IS NOT NULL)")
        with pytest.raises(errors.RaiseException, match="unsupported roles"):
            db.apply(FWD)
        with db.owner() as c:  # nothing partially applied
            assert c.execute("SELECT to_regclass('public.platform_audit_logs')").fetchone()[0] is None
    finally:
        db.drop()


def test_preflight_rejects_policy_drift():
    db = Replay([M1, M2])
    try:
        with db.owner() as c:
            c.execute("DROP POLICY organization_creator_insert ON public.organizations")
            c.execute("CREATE POLICY organization_creator_insert ON public.organizations"
                      " FOR INSERT TO authenticated WITH CHECK (true)")
        with pytest.raises(errors.RaiseException, match="organization_creator_insert"):
            db.apply(FWD)
    finally:
        db.drop()


def test_migration_is_not_reappliable(migrated):
    with pytest.raises(errors.RaiseException, match="Preflight"):
        migrated.apply(FWD)


# ---------------------------------------------------------------- audit log

def _audit(db: Replay, actor: str | None = U2) -> None:
    with db.as_role("service_role") as c:
        c.execute(
            "INSERT INTO public.platform_audit_logs (action, outcome, actor_user_id, metadata)"
            " VALUES ('test.synthetic_event', 'success', %s, '{\"test_data\": true}')", (actor,)
        )
        c.commit()


def test_service_role_can_insert_and_read_audit(migrated):
    _audit(migrated)
    with migrated.as_role("service_role") as c:
        assert c.execute("SELECT count(*) FROM public.platform_audit_logs").fetchone()[0] == 1


@pytest.mark.parametrize("sql", [
    "UPDATE public.platform_audit_logs SET action = 'tampered'",
    "DELETE FROM public.platform_audit_logs",
    "TRUNCATE public.platform_audit_logs",
])
def test_service_role_cannot_modify_audit(migrated, sql):
    _audit(migrated)
    with migrated.as_role("service_role") as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(sql)


@pytest.mark.parametrize("sql", [
    "UPDATE public.platform_audit_logs SET action = 'tampered'",
    "DELETE FROM public.platform_audit_logs",
    "TRUNCATE public.platform_audit_logs",
])
def test_owner_blocked_by_guard_trigger(migrated, sql):
    _audit(migrated)
    with migrated.owner() as c, pytest.raises(errors.InsufficientPrivilege, match="append-only"):
        c.execute(sql)


def test_manual_actor_nullification_rejected_while_user_exists(migrated):
    _audit(migrated, U2)
    with migrated.owner() as c, pytest.raises(errors.InsufficientPrivilege, match="append-only"):
        c.execute("UPDATE public.platform_audit_logs SET actor_user_id = NULL")


def test_manual_nullification_with_other_changes_rejected(migrated):
    _audit(migrated, U2)
    with migrated.owner() as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute("UPDATE public.platform_audit_logs SET actor_user_id = NULL, action = 'x'")


def test_actor_reassignment_rejected(migrated):
    _audit(migrated, U2)
    with migrated.owner() as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute("UPDATE public.platform_audit_logs SET actor_user_id = %s", (U3,))


def test_auth_user_deletion_preserves_audit_rows(migrated):
    _audit(migrated, U2)
    _audit(migrated, U2)
    _audit(migrated, U3)
    with migrated.auth_admin() as c:  # Supabase Auth deletes users as supabase_auth_admin
        c.execute("DELETE FROM auth.users WHERE id = %s", (U2,))
    with migrated.as_role("service_role") as c:
        rows = c.execute(
            "SELECT actor_user_id::text, action FROM public.platform_audit_logs ORDER BY actor_user_id NULLS FIRST"
        ).fetchall()
    assert [r[0] for r in rows] == [None, None, U3]
    assert all(r[1] == "test.synthetic_event" for r in rows)


def test_documented_limitation_owner_can_disable_trigger(migrated):
    """Not a guarantee against owners/superusers — documented in the migration."""
    _audit(migrated)
    with migrated.owner() as c:
        c.execute("BEGIN")
        c.execute("ALTER TABLE public.platform_audit_logs DISABLE TRIGGER platform_audit_logs_append_only")
        assert c.execute("DELETE FROM public.platform_audit_logs").rowcount == 1
        c.execute("ROLLBACK")


# ----------------------------------------------------------------- rollback

def test_rollback_restores_exact_pre_migration_schema():
    before = Replay([M1, M2])
    after = Replay([M1, M2, FWD])
    try:
        after.apply(RB)
        assert after.dump_schema() == before.dump_schema()
    finally:
        before.drop()
        after.drop()


def test_rollback_refuses_when_audit_rows_exist(migrated):
    _audit(migrated)
    with pytest.raises(errors.RaiseException, match="contains rows"):
        migrated.apply(RB)
    with migrated.owner() as c:
        assert c.execute("SELECT to_regclass('public.platform_audit_logs')").fetchone()[0] is not None


def test_rollback_with_explicit_discard(migrated):
    _audit(migrated)
    with migrated.owner() as c:
        c.execute("SET chromite.rollback_discard_audit = 'yes'")
        _exec_file(c, RB)
        assert c.execute("SELECT to_regclass('public.platform_audit_logs')").fetchone()[0] is None


def test_rollback_refuses_when_new_staff_roles_used(migrated):
    with migrated.owner() as c:
        c.execute("INSERT INTO public.platform_staff VALUES (%s, 'superadmin')", (U1,))
    with pytest.raises(errors.RaiseException, match="roles introduced"):
        migrated.apply(RB)


def test_forward_after_rollback_succeeds():
    db = Replay([M1, M2, FWD])
    try:
        db.apply(RB)
        db.apply(FWD)
        _create_org(db, U1)
    finally:
        db.drop()
