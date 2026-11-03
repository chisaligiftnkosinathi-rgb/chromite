"""Atomic organisation creation (proposed migration 20261104100000), local replay only."""

from pathlib import Path

import pytest
from psycopg import errors

from tests.db.test_migration_replay import ADMIN_DSN, FWD, M1, M2, ROOT, U1, U2, Replay

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="CHROMITE_REPLAY_ADMIN_DSN not set")

RPC = ROOT / "supabase/migrations-proposed/20261104100000_create_organization_with_owner.sql"
RPC_RB = ROOT / "supabase/migrations-proposed/20261104100000_create_organization_with_owner.ROLLBACK.sql"
CALL = "SELECT public.create_organization_with_owner(%s, %s, %s, %s)"


@pytest.fixture
def db():
    replay = Replay([M1, M2, FWD, RPC])
    yield replay
    replay.drop()


def _create(db, sub, name="SYNTHETIC RPC ORG", org_type="customer", reg=None, rid="req-12345678"):
    with db.as_role("authenticated", sub) as c:
        row = c.execute(CALL, (name, org_type, reg, rid)).fetchone()[0]
        c.commit()
    return row


def test_creates_org_membership_and_audit_together(db):
    org = _create(db, U1)
    with db.owner() as c:
        assert c.execute("SELECT created_by::text FROM public.organizations WHERE id = %s",
                         (org["id"],)).fetchone()[0] == U1
        assert c.execute("SELECT membership_role FROM public.organization_memberships"
                         " WHERE organization_id = %s AND user_id = %s",
                         (org["id"], U1)).fetchone()[0] == "owner"
        audit = c.execute("SELECT actor_user_id::text, outcome, request_id FROM public.platform_audit_logs"
                          " WHERE resource_id = %s", (org["id"],)).fetchone()
    assert audit == (U1, "success", "req-12345678")


def test_caller_sees_it_and_others_do_not(db):
    _create(db, U1)
    with db.as_role("authenticated", U1) as c:
        assert c.execute("SELECT count(*) FROM public.organizations").fetchone()[0] == 1
    with db.as_role("authenticated", U2) as c:
        assert c.execute("SELECT count(*) FROM public.organizations").fetchone()[0] == 0


def test_failure_after_org_insert_leaves_nothing(db):
    """Atomicity: force the membership insert to fail; no organisation or audit row may remain."""
    with db.owner() as c:
        c.execute("CREATE FUNCTION pg_temp_fail() RETURNS trigger LANGUAGE plpgsql AS"
                  " $$ BEGIN RAISE EXCEPTION 'forced failure'; END $$")
        c.execute("CREATE TRIGGER force_fail BEFORE INSERT ON public.organization_memberships"
                  " FOR EACH ROW EXECUTE FUNCTION pg_temp_fail()")
    with pytest.raises(errors.RaiseException, match="forced failure"):
        _create(db, U1)
    with db.owner() as c:
        assert c.execute("SELECT count(*) FROM public.organizations").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM public.platform_audit_logs").fetchone()[0] == 0


@pytest.mark.parametrize("org_type", ["laboratory", "sampling_provider", None, "x"])
def test_provider_and_unknown_types_rejected(db, org_type):
    with pytest.raises(errors.InvalidParameterValue):
        _create(db, U1, org_type=org_type)


@pytest.mark.parametrize("name", [None, "", " x ", "a" * 201, "bad\x01name"])
def test_invalid_names_rejected(db, name):
    with pytest.raises(errors.InvalidParameterValue):
        _create(db, U1, name=name)


def test_unsafe_request_id_is_dropped(db):
    org = _create(db, U1, rid="bad id; drop")
    with db.owner() as c:
        assert c.execute("SELECT request_id FROM public.platform_audit_logs WHERE resource_id = %s",
                         (org["id"],)).fetchone()[0] is None


def test_owner_limit(db):
    for i in range(10):
        _create(db, U1, name=f"SYNTHETIC ORG {i}")
    with pytest.raises(errors.RaiseException, match="owner limit"):
        _create(db, U1, name="SYNTHETIC ORG 11")


def test_anon_and_service_role_cannot_execute(db):
    for role in ("anon", "service_role"):
        with db.as_role(role) as c, pytest.raises(errors.InsufficientPrivilege):
            c.execute(CALL, ("X Org", "customer", None, None))


def test_unauthenticated_call_refused(db):
    with db.as_role("authenticated", None) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute(CALL, ("X Org", "customer", None, None))


def test_rollback_removes_function_only(db):
    org = _create(db, U1)
    db.apply(RPC_RB)
    with db.owner() as c:
        assert c.execute("SELECT to_regprocedure('public.create_organization_with_owner(text,text,text,text)')").fetchone()[0] is None
        assert c.execute("SELECT count(*) FROM public.organizations WHERE id = %s", (org["id"],)).fetchone()[0] == 1


def test_requires_consolidated_migration_first():
    replay = Replay([M1, M2])
    try:
        with pytest.raises(errors.RaiseException, match="apply 20261104090000"):
            replay.apply(RPC)
    finally:
        replay.drop()
