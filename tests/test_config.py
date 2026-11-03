import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_comma_separated_cors_origins_parse(monkeypatch):
    s = make(monkeypatch, CORS_ORIGINS="http://localhost:3000, http://127.0.0.1:3000/")
    assert s.CORS_ORIGINS == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_json_cors_origins_parse(monkeypatch):
    s = make(monkeypatch, CORS_ORIGINS='["https://app.example.co.za"]')
    assert s.CORS_ORIGINS == ["https://app.example.co.za"]


def test_documented_env_example_format_boots(monkeypatch):
    # Exact value shipped in .env.example
    s = make(monkeypatch, CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000")
    assert len(s.CORS_ORIGINS) == 2


def test_duplicate_and_blank_origins_removed(monkeypatch):
    s = make(monkeypatch, CORS_ORIGINS="http://a.example,,http://a.example")
    assert s.CORS_ORIGINS == ["http://a.example"]


def test_invalid_origin_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, CORS_ORIGINS="not-a-url")


def test_wildcard_with_credentials_rejected_in_any_env(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, APP_ENV="development", CORS_ORIGINS="*", CORS_ALLOW_CREDENTIALS="true")


def test_wildcard_rejected_in_production(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, APP_ENV="production", CORS_ORIGINS="*", CORS_ALLOW_CREDENTIALS="false")


def test_production_requires_explicit_origins_with_credentials(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, APP_ENV="production", CORS_ORIGINS="")


def test_plain_http_supabase_url_rejected_outside_localhost(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, SUPABASE_URL="http://project.supabase.co")


def test_http_localhost_supabase_url_allowed(monkeypatch):
    s = make(monkeypatch, SUPABASE_URL="http://127.0.0.1:54321/")
    assert s.SUPABASE_URL == "http://127.0.0.1:54321"


def test_blank_supabase_key_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, SUPABASE_KEY="   ")


def test_secrets_are_masked_in_repr(monkeypatch):
    s = make(monkeypatch, SUPABASE_KEY="placeholder-value-123")
    assert "placeholder-value-123" not in repr(s)
