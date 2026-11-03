"""Health probes, request IDs, security headers, safe errors and rate limiting."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_public_client
from app.core import middleware
from app.core.rate_limit import SlidingWindowLimiter, rate_limited
from app.main import app
from tests.fakes import FakeClient

client = TestClient(app)


@pytest.fixture
def public_db():
    fake = FakeClient()
    app.dependency_overrides[get_public_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_public_client, None)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_readyz_ok(public_db):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert public_db.ops("public_mines")


def test_readyz_unavailable(public_db):
    public_db.handler = lambda q: RuntimeError("db down")
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}


def test_security_headers_present():
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in r.headers  # only in production


def test_request_id_generated_and_echoed():
    generated = client.get("/healthz").headers["x-request-id"]
    assert len(generated) == 32
    assert client.get("/healthz", headers={"X-Request-ID": "trace-abc12345"}).headers["x-request-id"] == "trace-abc12345"


def test_unsafe_request_id_replaced():
    rid = client.get("/healthz", headers={"X-Request-ID": "bad id\r\nInjected: 1"}).headers["x-request-id"]
    assert rid != "bad id" and " " not in rid and len(rid) == 32


def test_authenticated_responses_not_cached():
    r = client.get("/healthz", headers={"Authorization": "Bearer x"})
    assert r.headers["cache-control"] == "no-store"


def test_unhandled_error_is_generic_500_with_request_id():
    mini = FastAPI()
    middleware.install(mini)

    @mini.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    r = TestClient(mini, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json()["detail"] == "Internal server error."
    assert r.json()["request_id"] == r.headers["x-request-id"]
    assert "secret internal detail" not in r.text


def test_root_hidden_from_schema():
    assert "/" not in app.openapi()["paths"]


def test_limiter_allows_then_blocks_then_recovers():
    now = [0.0]
    limiter = SlidingWindowLimiter(3, 60, clock=lambda: now[0])
    assert [limiter.check("k") for _ in range(3)] == [None, None, None]
    wait = limiter.check("k")
    assert wait is not None and 0 < wait <= 60
    assert limiter.check("other") is None  # keys are independent
    now[0] = 60.5
    assert limiter.check("k") is None


def test_rate_limit_dependency_returns_429_with_retry_after():
    mini = FastAPI()
    dep = rate_limited(SlidingWindowLimiter(2, 60), "t")

    @mini.get("/x", dependencies=[Depends(dep)])
    def x():
        return {}

    c = TestClient(mini)
    assert [c.get("/x").status_code for _ in range(3)] == [200, 200, 429]
    r = c.get("/x")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_public_directory_is_rate_limited(public_db, monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.public_limiter, "limit", 2)
    codes = [client.get("/api/v1/laboratories/").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
