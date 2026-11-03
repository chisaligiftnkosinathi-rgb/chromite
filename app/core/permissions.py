"""Authorisation: who the caller is, which organisations they belong to, and
which platform staff role (if any) they hold.

Rules
- Organisation membership comes from the database through the user's own
  RLS-scoped client, so a user can only ever see their own memberships.
- Staff roles come from `platform_staff`, which clients cannot read; it is
  looked up with the privileged client, read-only.
- A non-member asking about an organisation gets 404, not 403, so the API
  does not reveal which organisations exist.
- An organisation's self-declared type never grants provider or staff rights.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import Depends, HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.api.deps import get_admin_client_optional, get_user_client
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.errors import database_error

logger = logging.getLogger(__name__)

ORG_ROLES = ("owner", "admin", "member")
STAFF_ROLES = ("superadmin", "administrator", "verification_officer", "operations", "finance_officer")


@dataclass(frozen=True)
class Membership:
    organization_id: UUID
    role: str


@dataclass(frozen=True)
class Principal:
    user: AuthenticatedUser
    memberships: tuple[Membership, ...] = field(default_factory=tuple)
    staff_role: str | None = None

    @property
    def user_id(self) -> UUID:
        return self.user.user_id

    def role_in(self, organization_id: UUID) -> str | None:
        for m in self.memberships:
            if m.organization_id == organization_id:
                return m.role
        return None

    def require_org_role(self, organization_id: UUID, *allowed: str) -> str:
        role = self.role_in(organization_id)
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organisation not found.")
        if allowed and role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Your role does not allow this.")
        return role

    def require_staff(self, *allowed: str) -> str:
        if self.staff_role is None or (allowed and self.staff_role not in allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Staff permission required.")
        return self.staff_role


def _load_memberships(client: Client) -> tuple[Membership, ...]:
    try:
        rows = (client.table("organization_memberships")
                .select("organization_id, membership_role").execute().data) or []
    except APIError as exc:
        raise database_error(exc, action="membership lookup") from None
    out = []
    for row in rows:
        role = row.get("membership_role")
        if role in ORG_ROLES:
            out.append(Membership(UUID(str(row["organization_id"])), role))
    return tuple(out)


def _load_staff_role(admin: Client | None, user_id: UUID) -> str | None:
    if admin is None:
        return None
    try:
        rows = (admin.table("platform_staff").select("staff_role, is_active")
                .eq("user_id", str(user_id)).limit(1).execute().data) or []
    except APIError as exc:
        logger.warning("Staff role lookup failed (code=%s); treating as non-staff",
                       getattr(exc, "code", None))
        return None
    if rows and rows[0].get("is_active") and rows[0].get("staff_role") in STAFF_ROLES:
        return rows[0]["staff_role"]
    return None


def get_principal(
    user: AuthenticatedUser = Depends(get_current_user),
    user_client: Client = Depends(get_user_client),
    admin: Client | None = Depends(get_admin_client_optional),
) -> Principal:
    return Principal(
        user=user,
        memberships=_load_memberships(user_client),
        staff_role=_load_staff_role(admin, user.user_id),
    )
