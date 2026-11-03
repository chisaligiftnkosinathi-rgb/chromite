"""Map database errors to safe HTTP responses (no internals leak to clients)."""

import logging

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

logger = logging.getLogger(__name__)

# PostgreSQL insufficient_privilege: a grant or RLS policy refused the request.
PERMISSION_DENIED = "42501"


def database_error(exc: APIError, *, action: str) -> HTTPException:
    code = getattr(exc, "code", None)
    logger.warning("Database refused %s (code=%s)", action, code)
    if code == PERMISSION_DENIED:
        return HTTPException(status.HTTP_403_FORBIDDEN, detail="Not permitted.")
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="Service temporarily unavailable.")
