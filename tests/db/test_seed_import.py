"""Seed importer against the local replay cluster (skipped without it)."""

import psycopg
import pytest

from app.seeding.importer import load_datasets, run_import
from tests.db.test_migration_replay import ADMIN_DSN, FWD, M1, M2, Replay, _dsn

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="CHROMITE_REPLAY_ADMIN_DSN not set")


@pytest.fixture
def db():
    replay = Replay([M1, M2, FWD])
    yield replay
    replay.drop()


def _import(db, apply=True):
    mines, labs = load_datasets()
    with psycopg.connect(_dsn(db.name, "postgres")) as conn:
        return run_import(conn, mines, labs, apply=apply)


def test_dry_run_writes_nothing(db):
    report = _import(db, apply=False)
    assert report.counts()["mines_inserted"] == 5
    with db.owner() as c:
        assert c.execute("SELECT count(*) FROM public.mines WHERE slug LIKE 'samancor-%' OR slug IN ('tharisa-mine','dwarsrivier-chrome-mine')").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM public.platform_audit_logs").fetchone()[0] == 0


def test_apply_imports_drafts_only(db):
    report = _import(db)
    assert report.counts()["mines_inserted"] == 5
    assert report.counts()["mines_held_back"] == 4
    assert report.counts()["labs_inserted"] == 8
    assert report.audit_written
    with db.owner() as c:
        statuses = c.execute(
            "SELECT DISTINCT publication_status, verification_status FROM public.mines"
            " WHERE source_reference IS NOT NULL").fetchall()
        assert statuses == [("draft", "pending")]
        lab_statuses = c.execute(
            "SELECT DISTINCT publication_status, verification_status FROM public.laboratories"
            " WHERE source_checked_at IS NOT NULL").fetchall()
        assert lab_statuses == [("draft", "unverified")]
        assert c.execute("SELECT count(*) FROM public.lab_accreditation_scopes").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM public.mine_legal_rights").fetchone()[0] == 0


def test_seeded_records_are_not_public(db):
    _import(db)
    with db.as_role("anon") as c:
        names = [r[0] for r in c.execute("SELECT mine_name FROM public.public_mines")]
        labs = [r[0] for r in c.execute("SELECT laboratory_name FROM public.public_laboratories")]
    assert "Tharisa Mine" not in names
    assert not any("Cotecna" in n for n in labs)


def test_reimport_is_idempotent(db):
    _import(db)
    second = _import(db)
    assert second.counts()["mines_inserted"] == 0
    assert second.counts()["mines_existing_unchanged"] == 5
    assert second.counts()["labs_inserted"] == 0
    assert second.counts()["labs_existing_unchanged"] == 8
    with db.owner() as c:
        assert c.execute("SELECT count(*) FROM public.mines WHERE slug = 'tharisa-mine'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM public.laboratories WHERE laboratory_name LIKE 'AHK%'").fetchone()[0] == 3


def test_reviewer_status_changes_are_preserved(db):
    _import(db)
    with db.owner() as c:
        c.execute("UPDATE public.mines SET verification_status = 'verified' WHERE slug = 'tharisa-mine'")
        c.execute("UPDATE public.laboratories SET verification_status = 'pending'"
                  " WHERE laboratory_name LIKE 'Cotecna%'")
    _import(db)
    with db.owner() as c:
        assert c.execute("SELECT verification_status FROM public.mines WHERE slug = 'tharisa-mine'").fetchone()[0] == "verified"
        assert c.execute("SELECT verification_status FROM public.laboratories"
                         " WHERE laboratory_name LIKE 'Cotecna%'").fetchone()[0] == "pending"


def test_reviewer_edits_without_status_change_are_preserved(db):
    """The gap found in review: a draft edited by a reviewer must survive re-import."""
    _import(db)
    with db.owner() as c:
        c.execute("UPDATE public.mines SET public_description = 'Reviewer wording', nearest_town = 'Marikana'"
                  " WHERE slug = 'samancor-mooinooi'")
        c.execute("UPDATE public.laboratories SET physical_address = 'Reviewer address'"
                  " WHERE laboratory_name = 'IMEC Laboratory Services'")
    second = _import(db)
    assert "samancor-mooinooi" in second.mines_existing
    with db.owner() as c:
        assert c.execute("SELECT public_description, nearest_town, publication_status, verification_status"
                         " FROM public.mines WHERE slug = 'samancor-mooinooi'").fetchone() == \
            ("Reviewer wording", "Marikana", "draft", "pending")
        assert c.execute("SELECT physical_address FROM public.laboratories"
                         " WHERE laboratory_name = 'IMEC Laboratory Services'").fetchone()[0] == "Reviewer address"


def test_verification_queue_lists_every_claim(db):
    report = _import(db, apply=False)
    queue = "\n".join(report.verification_queue)
    assert "T0974" in queue and "T0658" in queue
    assert "kroondal-chrome-mine: source lacks province" in queue
