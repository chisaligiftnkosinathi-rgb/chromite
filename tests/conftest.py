"""Shared test configuration.

Tests never contact Supabase or any network service. Placeholder settings
are injected through environment variables, and CHROMITE_ENV_FILE points
Settings at a non-existent file so the developer's real ``.env`` is never
read during tests.
"""

import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Must run before any ``app`` import (Settings reads env at import time).
os.environ["CHROMITE_ENV_FILE"] = str(
    Path(tempfile.mkdtemp(prefix="chromite-tests-")) / "no-such.env"
)

_TEST_ENV = {
    "APP_ENV": "testing",
    "SUPABASE_URL": "https://test-project.invalid",
    "SUPABASE_KEY": "test-placeholder-not-a-real-key",
    "CORS_ORIGINS": '["http://localhost:3000"]',
    "CORS_ALLOW_CREDENTIALS": "true",
    "LOG_LEVEL": "WARNING",
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value
for _key in ("SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL"):
    os.environ.pop(_key, None)
