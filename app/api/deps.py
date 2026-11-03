"""Shared FastAPI dependencies for database clients.

- Public endpoints use the publishable-key client (RLS: published rows only).
- Authenticated endpoints use a per-request client carrying the user's own
  token, so row-level security applies to every query.
- The privileged client is optional and used only by named, permission-checked
  services (staff-role lookup, audit events). It is never handed to a route
  that serves customer data directly.
"""

import logging

from fastapi import Depends
from supabase import Client

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.supabase import get_supabase_admin, get_supabase_client, get_supabase_user_client

logger = logging.getLogger(__name__)


def get_public_client() -> Client:
    return get_supabase_client()


def get_user_client(user: AuthenticatedUser = Depends(get_current_user)) -> Client:
    return get_supabase_user_client(user.access_token)


def get_admin_client_optional() -> Client | None:
    try:
        return get_supabase_admin()
    except RuntimeError:
        logger.warning("Privileged client not configured; staff roles and audit events unavailable")
        return None
