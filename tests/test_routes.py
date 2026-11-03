from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_registered_paths():
    assert set(app.openapi()["paths"]) == {"/", "/api/v1/mines/"}


def test_sample_batches_route_is_not_exposed():
    r = client.post("/api/v1/sample-batches/", json={})
    assert r.status_code == 404


def test_health():
    assert client.get("/").json()["status"] == "ok"


def test_openapi_served_under_api_prefix():
    assert client.get("/api/v1/openapi.json").status_code == 200
