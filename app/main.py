from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import mines
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# Only explicitly configured origins are allowed (see CORS_ORIGINS).
# An empty list means no cross-origin browser access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(mines.router, prefix=f"{settings.API_V1_STR}/mines", tags=["Mines"])

# The early sample-batches router (app/api/v1/batches.py) is intentionally
# NOT registered: its sample_batches table does not exist in any migration
# and it bypassed RLS. It is replaced by the booking/sample lifecycle in
# Phase 7. The file is kept unchanged for reference.


@app.get("/")
def root():
    return {"status": "ok", "message": "Chromite API Backend is running"}
