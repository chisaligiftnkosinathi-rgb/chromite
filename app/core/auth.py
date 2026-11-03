"""Authentication dependency.

Verifies a Supabase access token supplied as ``Authorization: Bearer <token>``
and returns the authenticated user. Authorisation (organisation membership,
staff roles) is layered on top of this in later phases.

Error mapping:
    missing / malformed header, invalid or expired token -> 401
    Supabase Auth unreachable or failing                 -> 503
The token is never logged.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, status
from supabase import Client
from supabase_auth.errors import AuthError, AuthRetryableError

from app.core.supabase import get_supabase_client

logger = logging.getLogger(__name__)

_UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing authentication credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)

_AUTH_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Authentication service is temporarily unavailable.",
)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None = None
    # Kept for creating user-scoped (RLS-enforced) database clients.
    access_token: str = field(default="", repr=False)


def get_auth_client() -> Client:
    """Supabase client used only for token verification (overridable in tests)."""
    return get_supabase_client()


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _UNAUTHORISED

    parts = authorization.split()

    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise _UNAUTHORISED

    token = parts[1].strip()

    if len(token) > 8192:
        raise _UNAUTHORISED

    return token


def get_current_user(
    authorization: str | None = Header(default=None),
    client: Client = Depends(get_auth_client),
) -> AuthenticatedUser:
    token = extract_bearer_token(authorization)

    try:
        response = client.auth.get_user(token)
    except AuthRetryableError:
        logger.warning("Supabase Auth unavailable during token verification")
        raise _AUTH_UNAVAILABLE from None
    except AuthError:
        raise _UNAUTHORISED from None
    except httpx.HTTPError:
        logger.warning("Network error during token verification")
        raise _AUTH_UNAVAILABLE from None
    except Exception as exc:
        # Log the type only: exception text may echo the token.
        logger.error(
            "Unexpected error during token verification: %s",
            type(exc).__name__,
        )
        raise _AUTH_UNAVAILABLE from None

    user = getattr(response, "user", None)

    if user is None or not getattr(user, "id", None):
        raise _UNAUTHORISED

    try:
        user_id = UUID(str(user.id))
    except ValueError:
        raise _UNAUTHORISED from None

    return AuthenticatedUser(
        user_id=user_id,
        email=getattr(user, "email", None),
        access_token=token,
    )
