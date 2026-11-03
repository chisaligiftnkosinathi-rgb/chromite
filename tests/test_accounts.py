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
        self.rpc_error = None
        self.orgs = [ORG_ROW]
        self.user_db = FakeClient(self._user)
        self.admin_db = FakeClient(self._admin)

    def _user(self, q):
        if q.table == "organization_memberships" and q.op == "select":
            return self.memberships
        if q.table == "create_organization_with_owner" and q.op == "rpc":
            if self.rpc_error:
                return self.rpc_error
            return {**ORG_ROW, "organization_name": q.payload["p_organization_name"],
                    "organization_type": q.payload["p_organization_type"]}
        if q.table == "organizations" and q.op == "select":
            return self.orgs
        raise AssertionError(f"unexpected user query {q.table} {q.op}")

    def _admin(self, q):
        if q.table == "platform_staff":
            return self.staff
        if q.table == "platform_audit_logs":
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

def test_create_uses_single_atomic_function(world):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "SYNTHETIC ORG", "organization_type": "customer"})
    assert r.status_code == 201 and r.json()["my_role"] == "owner"
    calls = world.user_db.ops("create_organization_with_owner", "rpc")
    assert len(calls) == 1
    params = calls[0].payload
    assert params["p_organization_name"] == "SYNTHETIC ORG"
    assert params["p_request_id"] == r.headers["x-request-id"]
    # No separate table writes, and no user id is sent: the database uses auth.uid().
    assert not world.user_db.ops("organizations", "insert")
    assert not world.user_db.ops("organization_memberships", "insert")
    assert all("user" not in k for k in params)
    # Success is audited inside the transaction, not by the API.
    assert not world.admin_db.ops("platform_audit_logs", "insert")


def test_personal_account_is_single_member_customer_org(world):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "Synthetic Person (personal)"})
    assert r.status_code == 201
    assert world.user_db.ops("create_organization_with_owner", "rpc")[0].payload["p_organization_type"] == "customer"


@pytest.mark.parametrize("org_type", ["laboratory", "sampling_provider", "platform"])
def test_provider_types_cannot_be_self_declared(world, org_type):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "X Labs", "organization_type": org_type})
    assert r.status_code == 422
    assert not world.user_db.log or not world.user_db.ops("create_organization_with_owner")


@pytest.mark.parametrize("extra", [{"created_by": "someone-else"}, {"id": ORG_B}])
def test_client_cannot_set_server_fields(world, extra):
    r = client.post("/api/v1/organizations/", headers=AUTH,
                    json={"organization_name": "SYNTHETIC ORG", **extra})
    assert r.status_code == 422


@pytest.mark.parametrize("name", ["", "x", "a" * 201, "bad\u0000name"])
def test_invalid_names_rejected(world, name):
    assert client.post("/api/v1/organizations/", headers=AUTH,
                       json={"organization_name": name}).status_code == 422


@pytest.mark.parametrize("code,hint,expected", [
    ("42501", None, 403),
    ("22023", None, 422),
    ("P0001", "owner_limit", 409),
    ("PGRST202", None, 503),   # function missing (migration not applied)
])
def test_database_refusals_mapped_and_audited(world, code, hint, expected):
    err = api_error(code, "internal database message")
    err.hint = hint
    world.rpc_error = err
    r = client.post("/api/v1/organizations/", headers=AUTH, json={"organization_name": "SYNTHETIC ORG"})
    assert r.status_code == expected and "internal database message" not in r.text
    denied = world.admin_db.ops("platform_audit_logs", "insert")[0].payload
    assert denied["outcome"] == "denied" and denied["metadata"]["code"] == code


def test_unexpected_function_result_is_503(world):
    world.rpc_error = None
    world.user_db.handler = lambda q: [] if q.op == "select" else None
    r = client.post("/api/v1/organizations/", headers=AUTH, json={"organization_name": "SYNTHETIC ORG"})
    assert r.status_code == 503


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
