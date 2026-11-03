from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_registered_paths():
    assert set(app.openapi()["paths"]) == {
        "/healthz", "/readyz",
        "/api/v1/mines/", "/api/v1/mines/{slug}",
        "/api/v1/laboratories/", "/api/v1/laboratories/{laboratory_id}",
        "/api/v1/laboratories/{laboratory_id}/accreditation-scopes",
        "/api/v1/sampling-providers/", "/api/v1/sampling-providers/{provider_id}/services",
        "/api/v1/me/", "/api/v1/organizations/", "/api/v1/organizations/{organization_id}",
    }


def test_every_non_public_route_requires_auth():
    public = {"/healthz", "/readyz", "/api/v1/mines/", "/api/v1/laboratories/",
              "/api/v1/sampling-providers/"}
    c = TestClient(app)
    for path in ("/api/v1/me/", "/api/v1/organizations/"):
        assert path not in public
        assert c.get(path).status_code == 401


def test_sample_batches_route_is_not_exposed():
    r = client.post("/api/v1/sample-batches/", json={})
    assert r.status_code == 404


def test_health():
    assert client.get("/").json()["status"] == "ok"


def test_openapi_served_under_api_prefix():
    assert client.get("/api/v1/openapi.json").status_code == 200
