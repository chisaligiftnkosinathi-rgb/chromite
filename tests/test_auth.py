import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError, AuthRetryableError

from app.core.auth import AuthenticatedUser, get_auth_client, get_current_user

USER_ID = "aaaaaaaa-0000-4000-8000-000000000001"
TOKEN = "header.payload-synthetic-test-token.signature"


class FakeAuth:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def get_user(self, token):
        self.calls.append(token)
        result = self.behaviour
        if isinstance(result, Exception):
            raise result
        return result


def build(behaviour):
    fake = SimpleNamespace(auth=FakeAuth(behaviour))
    app = FastAPI()

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(get_current_user)):
        return {"user_id": str(user.user_id), "email": user.email}

    app.dependency_overrides[get_auth_client] = lambda: fake
    return TestClient(app), fake


def ok_user():
    return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email="test.user@example.invalid"))


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer   ", "Basic abc", "Token abc", "Bearer a b", "bearer"],
)
def test_missing_or_malformed_header_is_401(header):
    client, fake = build(ok_user())
    headers = {} if header is None else {"Authorization": header}
    r = client.get("/me", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert fake.auth.calls == []


def test_oversized_token_is_401():
    client, fake = build(ok_user())
    r = client.get("/me", headers={"Authorization": "Bearer " + "a" * 9000})
    assert r.status_code == 401
    assert fake.auth.calls == []


def test_valid_token_returns_user():
    client, fake = build(ok_user())
    r = client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json() == {"user_id": USER_ID, "email": "test.user@example.invalid"}
    assert fake.auth.calls == [TOKEN]


def test_scheme_is_case_insensitive():
    client, _ = build(ok_user())
    assert client.get("/me", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_rejected_token_is_401_not_500():
    client, _ = build(AuthApiError("invalid JWT", 401, None))
    assert client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401


def test_no_user_in_response_is_401():
    client, _ = build(SimpleNamespace(user=None))
    assert client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401


def test_none_response_is_401():
    client, _ = build(None)
    assert client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401


def test_non_uuid_user_id_is_401():
    client, _ = build(SimpleNamespace(user=SimpleNamespace(id="not-a-uuid", email=None)))
    assert client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401


@pytest.mark.parametrize(
    "error",
    [
        AuthRetryableError("upstream unavailable", 503),
        httpx.ConnectError("connection refused"),
        RuntimeError("unexpected"),
    ],
)
def test_auth_service_failure_is_503(error):
    client, _ = build(error)
    r = client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 503
    assert "unexpected" not in r.text and "refused" not in r.text


def test_token_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    client, _ = build(RuntimeError(f"failure while handling {TOKEN}"))
    client.get("/me", headers={"Authorization": f"Bearer {TOKEN}"})
    assert caplog.records, "expected an error log entry"
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert not record.exc_info


def test_user_repr_hides_token():
    user = AuthenticatedUser(user_id=USER_ID, access_token=TOKEN)
    assert TOKEN not in repr(user)
