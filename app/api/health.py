"""Liveness and readiness probes for the hosting platform."""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from supabase import Client

from app.api.deps import get_public_client
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get("/healthz", summary="Liveness: the process is running")
def healthz():
    return {"status": "ok", "version": settings.VERSION}


@router.get("/readyz", summary="Readiness: the database answers a public query")
def readyz(client: Client = Depends(get_public_client)):
    try:
        client.table("public_mines").select("id").limit(1).execute()
    except Exception as exc:
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        return JSONResponse({"status": "not_ready", "checks": {"database": "unavailable"}},
                            status_code=503)
    return {"status": "ready", "checks": {"database": "ok"}}
