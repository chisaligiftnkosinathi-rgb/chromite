"""Health probes, request IDs, security headers, safe errors and rate limiting."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_public_client
from app.api.health import get_readiness_checks
from app.core import middleware
from app.core.rate_limit import SlidingWindowLimiter, client_key, rate_limited
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


def _ready_with(**results):
    def make(outcome):
        def check():
            if outcome != "ok":
                raise RuntimeError("down: internal detail")
        return check
    app.dependency_overrides[get_readiness_checks] = lambda: {k: make(v) for k, v in results.items()}


def test_readyz_ok():
    _ready_with(database="ok", auth="ok", privileged="ok")
    try:
        r = client.get("/readyz")
    finally:
        app.dependency_overrides.pop(get_readiness_checks, None)
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "auth": "ok", "privileged": "ok"}}


@pytest.mark.parametrize("failing", ["database", "auth", "privileged"])
def test_readyz_fails_if_any_dependency_fails(failing):
    results = {"database": "ok", "auth": "ok", "privileged": "ok", failing: "down"}
    _ready_with(**results)
    try:
        r = client.get("/readyz")
    finally:
        app.dependency_overrides.pop(get_readiness_checks, None)
    assert r.status_code == 503
    assert r.json()["checks"][failing] == "unavailable"
    assert "internal detail" not in r.text


def test_readyz_default_checks_cover_auth_dependencies():
    assert set(get_readiness_checks()) == {"database", "auth", "privileged"}


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


def test_limiter_memory_is_bounded_under_key_churn():
    limiter = SlidingWindowLimiter(5, 60, max_keys=100)
    for i in range(5_000):
        limiter.check(f"client-{i}")
    assert limiter.tracked_keys() == 100


def test_limiter_evicts_least_recently_seen():
    limiter = SlidingWindowLimiter(1, 60, max_keys=2)
    limiter.check("a"); limiter.check("b"); limiter.check("a")  # a refreshed, b oldest
    limiter.check("c")  # evicts b
    assert limiter.check("a") is not None  # a still tracked and over its limit
    assert limiter.check("b") is None      # b was evicted, so starts fresh


class _Req:
    def __init__(self, peer, xff=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


def test_forwarded_header_ignored_without_trusted_proxies():
    assert client_key(_Req("203.0.113.9", "1.2.3.4"), trusted_proxies=[]) == "203.0.113.9"


def test_forwarded_header_ignored_from_untrusted_peer():
    assert client_key(_Req("203.0.113.9", "1.2.3.4"), trusted_proxies=["10.0.0.0/8"]) == "203.0.113.9"


def test_rightmost_untrusted_hop_used_behind_trusted_proxy():
    # A client tries to spoof "6.6.6.6"; the proxy appended the real client 198.51.100.7.
    req = _Req("10.0.0.5", "6.6.6.6, 198.51.100.7")
    assert client_key(req, trusted_proxies=["10.0.0.0/8"]) == "198.51.100.7"


def test_malformed_forwarded_header_falls_back_to_peer():
    assert client_key(_Req("10.0.0.5", "not-an-ip"), trusted_proxies=["10.0.0.0/8"]) == "10.0.0.5"
