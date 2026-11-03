"""Liveness and readiness probes for the hosting platform.

/readyz reports ready only when every dependency of the authenticated API works:
  database    — a public query through the publishable key (PostgREST + RLS)
  auth        — Supabase Auth answers its health endpoint
  privileged  — the backend's privileged key is configured and can read the
                staff registry (needed for staff roles and audit events)
Only check names and ok/unavailable are returned; no error details.
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.supabase import get_supabase_admin, get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])

TIMEOUT_SECONDS = 3.0


def _check_database() -> None:
    get_supabase_client().table("public_mines").select("id").limit(1).execute()


def _check_auth() -> None:
    response = httpx.get(
        f"{settings.SUPABASE_URL}/auth/v1/health",
        headers={"apikey": settings.SUPABASE_KEY.get_secret_value()},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _check_privileged() -> None:
    get_supabase_admin().table("platform_staff").select("user_id").limit(1).execute()


def get_readiness_checks() -> dict[str, Callable[[], None]]:
    return {"database": _check_database, "auth": _check_auth, "privileged": _check_privileged}


@router.get("/healthz", summary="Liveness: the process is running")
def healthz():
    return {"status": "ok", "version": settings.VERSION}


@router.get("/readyz", summary="Readiness: database, auth and privileged access all work")
def readyz(checks: dict[str, Callable[[], None]] = Depends(get_readiness_checks)):
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:
            logger.warning("Readiness check %s failed: %s", name, type(exc).__name__)
            results[name] = "unavailable"
    ready = all(v == "ok" for v in results.values())
    return JSONResponse({"status": "ready" if ready else "not_ready", "checks": results},
                        status_code=200 if ready else 503)
