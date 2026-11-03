import pytest
from fastapi.testclient import TestClient

import app.api.v1.mines as mines_module
from app.api.deps import get_public_client
from app.main import app
from tests.fakes import FakeClient, api_error

client = TestClient(app)
LAB_ID = "cccccccc-0000-4000-8000-000000000001"
LAB = {"id": LAB_ID, "laboratory_name": "SYNTHETIC TEST LAB", "country_code": "ZA",
       "province": "North West", "city": "Rustenburg", "physical_address": None,
       "website_url": None, "verification_status": "verified"}
SCOPE = {"id": "dddddddd-0000-4000-8000-000000000001", "laboratory_id": LAB_ID,
         "accreditation_body": "SANAS", "accreditation_number": "T9999 (TEST)",
         "certificate_reference": None, "standard": "ISO/IEC 17025:2017",
         "scope_title": "SYNTHETIC TEST SCOPE", "material_matrix": "Chromite ore",
         "analyte_or_parameter": "Cr2O3", "test_method": "TEST-METHOD-1",
         "scope_valid_from": "2026-01-01", "scope_valid_until": "2027-01-01",
         "verification_status": "verified"}


@pytest.fixture
def db():
    fake = FakeClient()
    app.dependency_overrides[get_public_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_public_client, None)


def test_list_laboratories_reads_public_view(db):
    db.handler = lambda q: [LAB]
    r = client.get("/api/v1/laboratories/?limit=10&offset=10&province=North West")
    assert r.status_code == 200 and r.json()[0]["laboratory_name"] == "SYNTHETIC TEST LAB"
    q = db.ops("public_laboratories")[0]
    assert ("ilike", "province", "North West") in q.calls and ("range", 10, 19) in q.calls


def test_laboratory_never_reads_base_table(db):
    client.get("/api/v1/laboratories/")
    client.get(f"/api/v1/laboratories/{LAB_ID}")
    assert {q.table for q in db.log} == {"public_laboratories"}


@pytest.mark.parametrize("bad", ["%", "a", "x_y", "Lim*"])
def test_laboratory_province_wildcards_rejected(db, bad):
    assert client.get("/api/v1/laboratories/", params={"province": bad}).status_code == 422


def test_get_laboratory_404(db):
    assert client.get(f"/api/v1/laboratories/{LAB_ID}").status_code == 404


def test_get_laboratory_bad_uuid(db):
    assert client.get("/api/v1/laboratories/not-a-uuid").status_code == 422


def test_scopes_come_from_verified_public_view(db):
    db.handler = lambda q: [SCOPE]
    r = client.get(f"/api/v1/laboratories/{LAB_ID}/accreditation-scopes")
    assert r.status_code == 200 and r.json()[0]["analyte_or_parameter"] == "Cr2O3"
    q = db.ops("public_lab_accreditation_scopes")[0]
    assert ("eq", "laboratory_id", LAB_ID) in q.calls


def test_directory_error_is_generic_503(db):
    db.handler = lambda q: api_error("42501", "permission denied for table laboratories")
    r = client.get("/api/v1/laboratories/")
    assert r.status_code == 503 and "permission" not in r.text


def test_sampling_providers_and_services(db):
    db.handler = lambda q: []
    assert client.get("/api/v1/sampling-providers/").status_code == 200
    assert client.get(f"/api/v1/sampling-providers/{LAB_ID}/services").status_code == 200
    assert {q.table for q in db.log} == {"public_sampling_providers", "public_sampling_services"}


class _MineDB(FakeClient):
    pass


def test_get_mine_by_slug(monkeypatch):
    row = {"id": LAB_ID, "mine_name": "SYNTHETIC TEST MINE", "slug": "synthetic-test-mine",
           "commodity": "chrome", "province": "Limpopo", "operating_status": "unknown",
           "verification_status": "unverified"}
    fake = FakeClient(lambda q: [row])
    monkeypatch.setattr(mines_module, "get_supabase_client", lambda: fake)
    assert client.get("/api/v1/mines/synthetic-test-mine").json()["mine_name"] == "SYNTHETIC TEST MINE"
    fake.handler = lambda q: []
    assert client.get("/api/v1/mines/missing-mine").status_code == 404
    assert client.get("/api/v1/mines/Bad_Slug").status_code == 422
