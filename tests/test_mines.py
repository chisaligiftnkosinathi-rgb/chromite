from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.v1.mines as mines_module
from app.main import app

client = TestClient(app)

ROW = {
    "id": "bbbbbbbb-0000-4000-8000-000000000001",
    "mine_name": "SYNTHETIC TEST MINE",
    "slug": "synthetic-test-mine",
    "commodity": "chrome",
    "province": "Limpopo",
    "district": None,
    "nearest_town": None,
    "latitude": -24.5,
    "longitude": 30.1,
    "mine_type": None,
    "operating_status": "unknown",
    "verification_status": "unverified",
    "public_description": "Synthetic test data",
    "source_name": "TEST DATA",
    "source_url": None,
    "source_checked_at": None,
}


class FakeQuery:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.calls = rows or [], error, []

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def __getattr__(self, name):
        def method(*args):
            self.calls.append((name, *args))
            return self

        return method

    def execute(self):
        if self.error:
            raise self.error
        return type("R", (), {"data": self.rows})()


def use(monkeypatch, fake):
    monkeypatch.setattr(mines_module, "get_supabase_client", lambda: fake)
    return fake


def test_returns_published_mines_from_public_view(monkeypatch):
    fake = use(monkeypatch, FakeQuery([ROW]))
    r = client.get("/api/v1/mines/")
    assert r.status_code == 200
    assert r.json()[0]["mine_name"] == "SYNTHETIC TEST MINE"
    assert ("table", "public_mines") in fake.calls
    assert ("range", 0, 49) in fake.calls


def test_filters_and_pagination(monkeypatch):
    fake = use(monkeypatch, FakeQuery([]))
    r = client.get("/api/v1/mines/?province=KwaZulu-Natal&operating_status=operating&limit=10&offset=20")
    assert r.status_code == 200
    assert ("ilike", "province", "KwaZulu-Natal") in fake.calls
    assert ("eq", "operating_status", "operating") in fake.calls
    assert ("range", 20, 29) in fake.calls


def test_province_with_wildcards_rejected(monkeypatch):
    use(monkeypatch, FakeQuery([]))
    for bad in ["%", "Lim%", "L_mpopo", "Lim*", "a", "x" * 51, "Limpopo;drop"]:
        assert client.get("/api/v1/mines/", params={"province": bad}).status_code == 422, bad


def test_unknown_operating_status_rejected(monkeypatch):
    use(monkeypatch, FakeQuery([]))
    assert client.get("/api/v1/mines/?operating_status=active").status_code == 422


def test_limit_bounds(monkeypatch):
    use(monkeypatch, FakeQuery([]))
    assert client.get("/api/v1/mines/?limit=0").status_code == 422
    assert client.get("/api/v1/mines/?limit=101").status_code == 422
    assert client.get("/api/v1/mines/?offset=-1").status_code == 422


def test_database_permission_error_is_generic_503(monkeypatch):
    err = APIError({"code": "42501", "message": "permission denied for table mines",
                    "details": None, "hint": None})
    use(monkeypatch, FakeQuery(error=err))
    r = client.get("/api/v1/mines/")
    assert r.status_code == 503
    assert r.json() == {"detail": "Mine directory is temporarily unavailable."}


def test_unexpected_error_is_generic_503(monkeypatch):
    use(monkeypatch, FakeQuery(error=RuntimeError("boom internal")))
    r = client.get("/api/v1/mines/")
    assert r.status_code == 503 and "boom" not in r.text
