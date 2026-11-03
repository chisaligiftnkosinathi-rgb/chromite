
from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


def _get_supabase_url() -> str:
    """Return the configured Supabase project URL."""
    return settings.SUPABASE_URL


def _get_publishable_key() -> str:
    """Retrieve the publishable key without exposing it in logs."""
    return settings.SUPABASE_KEY.get_secret_value()


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """
    Return the reusable public Supabase client.

    This client uses the publishable key and does not independently
    grant privileged access to database records.
    """
    return create_client(
        _get_supabase_url(),
        _get_publishable_key(),
    )


def get_supabase_user_client(access_token: str) -> Client:
    """
    Create a user-scoped Supabase client.

    The user's access token is forwarded to PostgREST so that
    database queries execute under the authenticated user's
    PostgreSQL role and applicable RLS policies.

    A new client is created for each user context to prevent
    authentication state from leaking between users.
    """
    if not isinstance(access_token, str) or not access_token.strip():
        raise ValueError("A valid user access token is required")

    client = create_client(
        _get_supabase_url(),
        _get_publishable_key(),
    )

    client.postgrest.auth(access_token.strip())

    return client


@lru_cache(maxsize=1)
def get_supabase_admin() -> Client:
    """
    Return the privileged Supabase client.

    This client must only be used by trusted backend operations.
    Its credentials can bypass database RLS policies.
    """
    admin_key = settings.SUPABASE_SERVICE_ROLE_KEY

    if admin_key is None:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY is not configured. "
            "Privileged database operations are unavailable."
        )

    secret = admin_key.get_secret_value()

    if not secret.strip():
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY cannot be empty."
        )

    return create_client(
        _get_supabase_url(),
        secret,
    )
