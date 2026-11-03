"""Seed datasets and models: every record sourced, nothing pre-verified."""

import copy
import json

import pytest
from pydantic import ValidationError

from app.seeding.importer import (
    DEFAULT_LABS,
    DEFAULT_MINES,
    UnsafeTargetError,
    assert_connected_locally,
    assert_local_dsn,
    load_datasets,
)
from app.seeding.models import LaboratoryDataset, MineDataset


def raw(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_shipped_datasets_validate():
    mines, labs = load_datasets()
    assert len(mines.records) == 9
    assert len(labs.records) == 8


def test_every_record_cites_an_https_source_checked_on_a_date():
    mines, labs = load_datasets()
    for record in [*mines.records, *labs.records]:
        assert record.source.url.scheme == "https"
        assert record.source.checked_at is not None


def test_no_accreditation_claim_is_marked_verified():
    _, labs = load_datasets()
    claims = [c for lab in labs.records for c in lab.accreditation_claims]
    assert claims, "expected at least one claim queued for verification"
    assert {c.status for c in claims} == {"unverified"}


def test_seed_cannot_assert_verified_claim():
    data = raw(DEFAULT_LABS)
    data["records"][0]["accreditation_claims"][0]["status"] = "verified"
    with pytest.raises(ValidationError):
        LaboratoryDataset.model_validate(data)


@pytest.mark.parametrize("field,value", [
    ("publication_status", "published"),
    ("verification_status", "verified"),
])
def test_seed_cannot_set_publication_or_verification(field, value):
    data = raw(DEFAULT_MINES)
    data["records"][0][field] = value
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


def test_missing_source_rejected():
    data = raw(DEFAULT_MINES)
    del data["records"][0]["source"]
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


def test_http_source_rejected():
    data = raw(DEFAULT_MINES)
    data["records"][0]["source"]["url"] = "http://example.com/page"
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


def test_published_after_checked_rejected():
    data = raw(DEFAULT_MINES)
    data["records"][1]["source"]["published"] = "2030-01-01"
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


@pytest.mark.parametrize("lat,lon", [(-24.5, None), (51.5, -0.1), (-24.5, 45.0)])
def test_bad_coordinates_rejected(lat, lon):
    data = raw(DEFAULT_MINES)
    data["records"][0]["latitude"] = lat
    data["records"][0]["longitude"] = lon
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


def test_unknown_province_rejected():
    data = raw(DEFAULT_MINES)
    data["records"][0]["province"] = "Bushveld"
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


def test_duplicate_slug_rejected():
    data = raw(DEFAULT_MINES)
    data["records"].append(copy.deepcopy(data["records"][0]))
    with pytest.raises(ValidationError):
        MineDataset.model_validate(data)


def test_records_without_province_are_held_back():
    mines, _ = load_datasets()
    held = sorted(m.slug for m in mines.records if m.missing_required)
    assert held == ["kroondal-chrome-mine", "samancor-lannex",
                    "samancor-tweefontein", "samancor-winterveld"]


def test_accreditation_number_format():
    data = raw(DEFAULT_LABS)
    data["records"][0]["accreditation_claims"][0]["accreditation_number_claimed"] = "974"
    with pytest.raises(ValidationError):
        LaboratoryDataset.model_validate(data)


@pytest.mark.parametrize("dsn", [
    "host=127.0.0.1 port=55322 user=postgres dbname=postgres",
    "host=localhost dbname=postgres",
    "host=/tmp port=5434 user=supabase_admin dbname=postgres",
])
def test_local_dsn_allowed(dsn):
    assert_local_dsn(dsn, environ={})


@pytest.mark.parametrize("dsn", [
    "host=db.abcdefghijklmnop.supabase.co port=5432 user=postgres dbname=postgres",
    "host=aws-0-eu-west-1.pooler.supabase.com port=6543 user=postgres.ref dbname=postgres",
    "host=10.0.0.5 dbname=postgres",
    "host=127.0.0.1,db.example.com dbname=postgres",
    "hostaddr=8.8.8.8 dbname=postgres",
    "host=127.0.0.1 hostaddr=8.8.8.8 dbname=postgres",
    "service=chromite",
    "host=127.0.0.1 service=chromite dbname=postgres",
    "host=127.0.0.1 servicefile=/tmp/x dbname=postgres",
    "dbname=postgres",
    "postgresql:///postgres",
    "not a dsn ===",
])
def test_remote_or_implicit_dsn_refused(dsn):
    with pytest.raises(UnsafeTargetError):
        assert_local_dsn(dsn, environ={})


@pytest.mark.parametrize("var", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_redirecting_environment_refused(var):
    with pytest.raises(UnsafeTargetError, match=var):
        assert_local_dsn("host=127.0.0.1 dbname=postgres", environ={var: "x"})


class _Info:
    def __init__(self, host, hostaddr):
        self.host, self.hostaddr = host, hostaddr


class _Conn:
    def __init__(self, host, hostaddr):
        self.info = _Info(host, hostaddr)


@pytest.mark.parametrize("host,addr", [("127.0.0.1", "127.0.0.1"), ("localhost", "::1"),
                                       ("/tmp", "")])
def test_connected_locally_accepted(host, addr):
    assert_connected_locally(_Conn(host, addr))


@pytest.mark.parametrize("host,addr", [("127.0.0.1", "10.0.0.5"), ("db.example.com", "203.0.113.4"),
                                       ("/tmp", "203.0.113.4")])
def test_connected_remotely_refused(host, addr):
    with pytest.raises(UnsafeTargetError):
        assert_connected_locally(_Conn(host, addr))


def test_claim_type_required_and_counted():
    _, labs = load_datasets()
    types = [c.claim_type for lab in labs.records for c in lab.accreditation_claims]
    assert len(types) == 5
    assert types.count("states_accredited") == 2
    assert types.count("pursuing_accreditation") == 2
    assert types.count("reported_expired") == 1
    data = raw(DEFAULT_LABS)
    del data["records"][0]["accreditation_claims"][0]["claim_type"]
    with pytest.raises(ValidationError):
        LaboratoryDataset.model_validate(data)


def test_expired_lead_is_not_labelled_accredited():
    _, labs = load_datasets()
    mitra = next(l for l in labs.records if l.laboratory_name.startswith("Mitra SK, Richards Bay"))
    assert [c.claim_type for c in mitra.accreditation_claims] == ["reported_expired"]
