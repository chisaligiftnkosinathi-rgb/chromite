import logging

from app.core.logging import RedactingFilter, redact

# Synthetic look-alikes only; none of these are real credentials.
FAKE_SECRET = "sb_secret_" + "TESTONLY0000000000000000"
FAKE_PUBLISHABLE = "sb_publishable_" + "TESTONLY000000000000"
FAKE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJ0ZXN0In0" + "." + "c2lnbmF0dXJl"


def test_redacts_supabase_keys():
    out = redact(f"key={FAKE_SECRET} pub={FAKE_PUBLISHABLE}")
    assert "TESTONLY" not in out
    assert "sb_secret_[REDACTED]" in out and "sb_publishable_[REDACTED]" in out


def test_redacts_bearer_and_jwt():
    out = redact(f"Authorization: Bearer abc.def.ghi token={FAKE_JWT}")
    assert "abc.def.ghi" not in out and FAKE_JWT not in out


def test_redacts_database_password():
    out = redact("postgresql://postgres:" + "p4ssw0rd-test" + "@db.example.invalid:5432/postgres")
    assert "p4ssw0rd-test" not in out


def test_filter_rewrites_record():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "using %s", (FAKE_SECRET,), None)
    RedactingFilter().filter(record)
    assert "TESTONLY" not in record.getMessage()


def test_filter_redacts_tracebacks():
    try:
        raise ValueError(f"leaked {FAKE_SECRET}")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    RedactingFilter().filter(record)
    assert "TESTONLY" not in logging.Formatter().format(record)
