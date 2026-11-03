from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1 import directory, me, mines, organizations
from app.core import middleware
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.docs_enabled else None,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
)

# Only explicitly configured origins are allowed (see CORS_ORIGINS).
# An empty list means no cross-origin browser access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)
# Outermost: request ID, security headers, access log, safe 500s.
middleware.install(app)

v1 = settings.API_V1_STR
app.include_router(health.router)
app.include_router(mines.router, prefix=f"{v1}/mines", tags=["Mines"])
app.include_router(directory.router, prefix=v1, tags=["Directory"])
app.include_router(me.router, prefix=f"{v1}/me", tags=["Account"])
app.include_router(organizations.router, prefix=f"{v1}/organizations", tags=["Organisations"])

# The early sample-batches router (app/api/v1/batches.py) is intentionally
# NOT registered: its sample_batches table does not exist in any migration
# and it bypassed RLS. It is replaced by the booking/sample lifecycle in
# Phase 7. The file is kept unchanged for reference.


@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "message": "Chromite API Backend is running"}
