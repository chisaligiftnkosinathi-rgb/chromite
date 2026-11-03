"""Map database errors to safe HTTP responses (no internals leak to clients)."""

import logging

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

logger = logging.getLogger(__name__)

# PostgreSQL insufficient_privilege: a grant or RLS policy refused the request.
PERMISSION_DENIED = "42501"
# invalid_parameter_value: a database function rejected an argument.
INVALID_PARAMETER = "22023"
# raise_exception with a hint naming a business rule.
RULE_VIOLATION = "P0001"
RULE_MESSAGES = {"owner_limit": "You already own the maximum number of organisations."}


def database_error(exc: APIError, *, action: str) -> HTTPException:
    code = getattr(exc, "code", None)
    hint = getattr(exc, "hint", None)
    logger.warning("Database refused %s (code=%s)", action, code)
    if code == PERMISSION_DENIED:
        return HTTPException(status.HTTP_403_FORBIDDEN, detail="Not permitted.")
    if code == INVALID_PARAMETER:
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid request.")
    if code == RULE_VIOLATION and hint in RULE_MESSAGES:
        return HTTPException(status.HTTP_409_CONFLICT, detail=RULE_MESSAGES[hint])
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="Service temporarily unavailable.")
