"""Permissions, /me and organisation registration."""

from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_admin_client_optional, get_user_client
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.permissions import Membership, Principal
from app.main import app
from tests.fakes import FakeClient, api_error

client = TestClient(app)
USER = AuthenticatedUser(user_id=UUID("aaaaaaaa-0000-4000-8000-000000000001"),
                         email="synthetic.user@example.invalid", access_token="test-token")
ORG_A = "bbbbbbbb-0000-4000-8000-00000000000a"
ORG_B = "bbbbbbbb-0000-4000-8000-00000000000b"
ORG_ROW = {"id": ORG_A, "organization_name": "SYNTHETIC ORG", "organization_type": "customer",
           "registration_number": None, "country_code": "ZA", "created_at": "2026-11-03T12:00:00+00:00"}


class World:
    def __init__(self):
        self.memberships = []
        self.staff = []
        self.org_insert_error = None
        self.membership_insert_error = None
        self.orgs = [ORG_ROW]
        self.user_db = FakeClient(self._user)
        self.admin_db = FakeClient(self._admin)

    def _user(self, q):
        if q.table == "organization_memberships" and q.op == "select":
            return self.memberships
        if q.table == "organization_memberships" and q.op == "insert":
            return self.membership_insert_error or []
        if q.table == "organizations" and q.op == "insert":
            return self.org_insert_error or [{**ORG_ROW, **q.payload, "id": ORG_A}]
        if q.table == "organizations" and q.op == "select":
            return self.orgs
        raise AssertionError(f"unexpected user query {q.table} {q.op}")

    def _admin(self, q):
        if q.table == "platform_staff":
            return self.staff
        if q.table in ("platform_audit_logs", "organizations"):
            return []
        raise AssertionError(f"unexpected admin query {q.table}")


@pytest.fixture
def world():
    w = World()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_user_client] = lambda: w.user_db
    app.dependency_overrides[get_admin_client_optional] = lambda: w.admin_db
    yield w
    app.dependency_overrides.clear()


AUTH = {"Authorization": "Bearer test-token"}


# ---- Principal rules (no HTTP) ------------------------------------------------

def test_non_member_gets_404_not_403():
    p = Principal(user=USER, memberships=(Membership(UUID(ORG_A), "member"),))
    with pytest.raises(HTTPException) as exc:
        p.require_org_role(UUID(ORG_B))
    assert exc.value.status_code == 404


def test_member_without_required_role_gets_403():
    p = Principal(user=USER, memberships=(Membership(UUID(ORG_A), "member"),))
    with pytest.raises(HTTPException) as exc:
        p.require_org_role(UUID(ORG_A), "owner", "admin")
    assert exc.value.status_code == 403
    assert p.require_org_role(UUID(ORG_A)) == "member"


def test_staff_required():
    with pytest.raises(HTTPException) as exc:
        Principal(user=USER).require_staff()
    assert exc.value.status_code == 403
    p = Principal(user=USER, staff_role="verification_officer")
    assert p.require_staff("verification_officer") == "verification_officer"
    with pytest.raises(HTTPException):
        p.require_staff("finance_officer")


# ---- /me ----------------------------------------------------------------------

def test_me_requires_authentication():
    assert TestClient(app).get("/api/v1/me/").status_code == 401


def test_me_returns_memberships_and_staff_role(world):
    world.memberships = [{"organization_id": ORG_A, "membership_role": "owner"},
                         {"organization_id": ORG_B, "membership_role": "superuser"}]  # invalid role dropped
    world.staff = [{"staff_role": "operations", "is_active": True}]
    r = client.get("/api/v1/me/", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["memberships"] == [{"organization_id": ORG_A, "role": "owner"}]
    assert r.json()["staff_role"] == "operations"
    assert r.headers["cache-control"] == "no-store"


def test_inactive_staff_is_not_staff(world):
    world.staff = [{"staff_role": "superadmin", "is_active": False}]
    assert client.get("/api/v1/me/", headers=AUTH).json()["staff_role"] is None


def test_no_admin_client_means_no_staff_role(world):
    app.dependency_overrides[get_admin_client_optional] = lambda: None
    world.staff = [{"staff_role": "superadmin", "is_active": True}]
    assert client.get("/api/v1/me/", headers=AUTH).json()["staff_role"] is None


def test_membership_lookup_denied_is_403(world):
    world.memberships = api_error("42501")
    assert client.get("/api/v1/me/", headers=AUTH).status_code == 403


# ---- organisations --------------------------------------------------------------

def test_create_organisation_makes_caller_owner(world):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "SYNTHETIC ORG", "organization_type": "customer"})
    assert r.status_code == 201 and r.json()["my_role"] == "owner"
    org_insert = world.user_db.ops("organizations", "insert")[0]
    assert org_insert.payload["created_by"] == str(USER.user_id)
    member_insert = world.user_db.ops("organization_memberships", "insert")[0]
    assert member_insert.payload == {"organization_id": ORG_A, "user_id": str(USER.user_id),
                                     "membership_role": "owner"}
    audit = world.admin_db.ops("platform_audit_logs", "insert")[0].payload
    assert audit["action"] == "organization.create" and audit["outcome"] == "success"
    assert "test-token" not in str(audit)


def test_personal_account_is_single_member_customer_org(world):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "Synthetic Person (personal)"})
    assert r.status_code == 201
    assert world.user_db.ops("organizations", "insert")[0].payload["organization_type"] == "customer"


@pytest.mark.parametrize("org_type", ["laboratory", "sampling_provider", "platform"])
def test_provider_types_cannot_be_self_declared(world, org_type):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "X Labs", "organization_type": org_type})
    assert r.status_code == 422
    assert not world.user_db.ops("organizations", "insert")


@pytest.mark.parametrize("extra", [{"created_by": "someone-else"}, {"id": ORG_B}])
def test_client_cannot_set_server_fields(world, extra):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "SYNTHETIC ORG", **extra})
    assert r.status_code == 422


@pytest.mark.parametrize("name", ["", "x", "a" * 201, "bad\u0000name"])
def test_invalid_names_rejected(world, name):
    assert client.post("/api/v1/organizations/", headers=AUTH,
                       json={"organization_name": name}).status_code == 422


def test_rls_refusal_on_create_is_403_and_audited(world):
    world.org_insert_error = api_error("42501", "new row violates row-level security policy")
    r = client.post("/api/v1/organizations/", headers=AUTH, json={"organization_name": "SYNTHETIC ORG"})
    assert r.status_code == 403 and "row-level" not in r.text
    assert world.admin_db.ops("platform_audit_logs", "insert")[0].payload["outcome"] == "denied"


def test_failed_owner_membership_removes_orphan_and_audits(world):
    world.membership_insert_error = api_error("42P17", "infinite recursion detected in policy")
    r = client.post("/api/v1/organizations/", headers=AUTH, json={"organization_name": "SYNTHETIC ORG"})
    assert r.status_code == 503 and "recursion" not in r.text
    deletes = world.admin_db.ops("organizations", "delete")
    assert len(deletes) == 1 and ("eq", "id", ORG_A) in deletes[0].calls
    audit = world.admin_db.ops("platform_audit_logs", "insert")[0].payload
    assert audit["outcome"] == "failure" and audit["metadata"]["orphan_removed"] is True


def test_owner_cap_enforced(world):
    world.memberships = [{"organization_id": f"bbbbbbbb-0000-4000-8000-{i:012d}", "membership_role": "owner"}
                         for i in range(10)]
    r = client.post("/api/v1/organizations/", headers=AUTH, json={"organization_name": "One too many"})
    assert r.status_code == 409


def test_create_is_rate_limited(world, monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.write_limiter, "limit", 2)
    codes = [client.post("/api/v1/organizations/", headers=AUTH,
                         json={"organization_name": "SYNTHETIC ORG"}).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_list_attaches_my_role(world):
    world.memberships = [{"organization_id": ORG_A, "membership_role": "admin"}]
    r = client.get("/api/v1/organizations/", headers=AUTH)
    assert r.status_code == 200 and r.json()[0]["my_role"] == "admin"


def test_get_organisation_requires_membership(world):
    assert client.get(f"/api/v1/organizations/{ORG_A}", headers=AUTH).status_code == 404
    world.memberships = [{"organization_id": ORG_A, "membership_role": "member"}]
    r = client.get(f"/api/v1/organizations/{ORG_A}", headers=AUTH)
    assert r.status_code == 200 and r.json()["my_role"] == "member"


def test_organisations_require_authentication():
    c = TestClient(app)
    assert c.get("/api/v1/organizations/").status_code == 401
    assert c.post("/api/v1/organizations/", json={"organization_name": "X Org"}).status_code == 401
