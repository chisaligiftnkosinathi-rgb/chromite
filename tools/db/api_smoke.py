"""End-to-end API smoke test against a LOCAL Supabase stack (never hosted).

Run by tools/db/local-supabase-stack-test.ps1 after the migrations are applied.
Creates two synthetic users in the throwaway stack, signs them in, and drives the
real FastAPI app (in-process) with their real tokens, so row-level security is
exercised end to end: PostgREST + GoTrue + Postgres + this API.

Environment (set by the stack script from `supabase status`):
  SMOKE_SUPABASE_URL      http://127.0.0.1:<port>   (must be local)
  SMOKE_PUBLISHABLE_KEY   local stack publishable/anon key
  SMOKE_SECRET_KEY        local stack secret/service key
"""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

url = os.environ["SMOKE_SUPABASE_URL"].rstrip("/")
publishable = os.environ["SMOKE_PUBLISHABLE_KEY"]
secret = os.environ["SMOKE_SECRET_KEY"]

if urlparse(url).hostname not in {"127.0.0.1", "localhost"}:
    sys.exit(f"REFUSED: {url} is not a local Supabase stack")

# Configure the app for the local stack before importing it; never read .env.
os.environ.update({
    "CHROMITE_ENV_FILE": str(Path(tempfile.mkdtemp()) / "no-such.env"),
    "APP_ENV": "testing",
    "SUPABASE_URL": url,
    "SUPABASE_KEY": publishable,
    "SUPABASE_SERVICE_ROLE_KEY": secret,
    "CORS_ORIGINS": '["http://localhost:3000"]',
    "LOG_LEVEL": "WARNING",
})

from fastapi.testclient import TestClient  # noqa: E402
from supabase import create_client  # noqa: E402

from app.main import app  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {label}")
    else:
        print(f"FAIL: {label} {detail}")
        failures.append(label)


def make_user(tag: str) -> str:
    email = f"smoke-{tag}-{secrets.token_hex(4)}@example.com"  # synthetic test user
    password = secrets.token_urlsafe(18)
    admin = create_client(url, secret)
    admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
    session = create_client(url, publishable).auth.sign_in_with_password(
        {"email": email, "password": password}).session
    return session.access_token


api = TestClient(app)
token_a, token_b = make_user("a"), make_user("b")
A = {"Authorization": f"Bearer {token_a}"}
B = {"Authorization": f"Bearer {token_b}"}

check("readiness probe sees the database", api.get("/readyz").status_code == 200)
for path in ("/api/v1/mines/", "/api/v1/laboratories/", "/api/v1/sampling-providers/"):
    r = api.get(path)
    check(f"public directory {path} -> 200", r.status_code == 200, f"got {r.status_code}")

check("bad token -> 401", api.get("/api/v1/me/", headers={"Authorization": "Bearer nope"}).status_code == 401)
r = api.get("/api/v1/me/", headers=A)
check("user A /me -> 200 with no memberships", r.status_code == 200 and r.json()["memberships"] == [],
      r.text[:200])

r = api.post("/api/v1/organizations/", headers=A,
             json={"organization_name": "SYNTHETIC SMOKE ORG", "organization_type": "customer"})
check("user A creates an organisation and becomes owner",
      r.status_code == 201 and r.json().get("my_role") == "owner", f"{r.status_code} {r.text[:200]}")
org_id = r.json().get("id") if r.status_code == 201 else None

r = api.get("/api/v1/me/", headers=A)
check("user A /me shows owner membership",
      [m["role"] for m in r.json().get("memberships", [])] == ["owner"], r.text[:200])
r = api.get("/api/v1/organizations/", headers=A)
check("user A lists exactly their organisation", r.status_code == 200 and len(r.json()) == 1, r.text[:200])

r = api.get("/api/v1/organizations/", headers=B)
check("user B sees no organisations", r.status_code == 200 and r.json() == [], r.text[:200])
if org_id:
    check("user B cannot read user A's organisation",
          api.get(f"/api/v1/organizations/{org_id}", headers=B).status_code == 404)
check("provider type cannot be self-declared",
      api.post("/api/v1/organizations/", headers=B,
               json={"organization_name": "Fake Lab", "organization_type": "laboratory"}).status_code == 422)

admin = create_client(url, secret)
events = (admin.table("platform_audit_logs").select("action, outcome")
          .eq("action", "organization.create").eq("outcome", "success").execute().data) or []
check("organisation creation was audited", len(events) >= 1, f"found {len(events)}")

if failures:
    print(f"\nAPI SMOKE TEST FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAPI SMOKE TEST PASSED")
