from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ALLOWED = "http://localhost:3000"
EVIL = "https://evil.example"


def preflight(origin):
    return client.options(
        "/api/v1/mines/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_preflight_from_allowed_origin_succeeds():
    r = preflight(ALLOWED)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ALLOWED
    assert r.headers["access-control-allow-credentials"] == "true"


def test_preflight_from_unlisted_origin_is_rejected():
    r = preflight(EVIL)
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_simple_request_from_unlisted_origin_gets_no_cors_headers():
    r = client.get("/", headers={"Origin": EVIL, "Cookie": "session=x"})
    assert "access-control-allow-origin" not in r.headers


def test_wildcard_is_never_returned():
    r = client.get("/", headers={"Origin": ALLOWED})
    assert r.headers.get("access-control-allow-origin") == ALLOWED
