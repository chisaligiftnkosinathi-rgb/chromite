"""Customer organisations. A personal customer is a single-member organisation.

All reads and writes use the caller's own RLS-scoped client. The privileged
client is used only to write audit events and, if the owner membership fails,
to remove the just-created organisation so no orphan is left behind.
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from postgrest.exceptions import APIError
from postgrest.types import ReturnMethod
from supabase import Client

from app.api.deps import get_admin_client_optional, get_user_client
from app.core.errors import database_error
from app.core.permissions import Principal, get_principal
from app.core.rate_limit import write_rate_limit
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.services import audit

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_OWNED_ORGANIZATIONS = 10
_COLUMNS = "id, organization_name, organization_type, registration_number, country_code, created_at"


@router.get("/", response_model=List[OrganizationResponse],
            summary="Organisations you belong to")
def list_organizations(principal: Principal = Depends(get_principal),
                       client: Client = Depends(get_user_client)):
    try:
        rows = client.table("organizations").select(_COLUMNS).order("created_at").execute().data or []
    except APIError as exc:
        raise database_error(exc, action="organisation list") from None
    return [{**r, "my_role": principal.role_in(UUID(str(r["id"])))} for r in rows]


@router.get("/{organization_id}", response_model=OrganizationResponse,
            summary="One organisation you belong to")
def get_organization(organization_id: UUID, principal: Principal = Depends(get_principal),
                     client: Client = Depends(get_user_client)):
    role = principal.require_org_role(organization_id)
    try:
        rows = (client.table("organizations").select(_COLUMNS)
                .eq("id", str(organization_id)).limit(1).execute().data) or []
    except APIError as exc:
        raise database_error(exc, action="organisation read") from None
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organisation not found.")
    return {**rows[0], "my_role": role}


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_rate_limit)],
             summary="Create an organisation; you become its owner")
def create_organization(
    body: OrganizationCreate,
    request: Request,
    principal: Principal = Depends(get_principal),
    client: Client = Depends(get_user_client),
    admin: Client | None = Depends(get_admin_client_optional),
):
    owned = sum(1 for m in principal.memberships if m.role == "owner")
    if owned >= MAX_OWNED_ORGANIZATIONS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"You already own {MAX_OWNED_ORGANIZATIONS} organisations.")
    request_id = getattr(request.state, "request_id", None)
    user_id = principal.user_id

    try:
        created = (client.table("organizations")
                   .insert({**body.model_dump(), "created_by": str(user_id)}).execute().data) or []
    except APIError as exc:
        audit.record(admin, action="organization.create", outcome="denied", actor_user_id=user_id,
                     request_id=request_id, metadata={"code": getattr(exc, "code", None)})
        raise database_error(exc, action="organisation create") from None
    if not created:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service temporarily unavailable.")
    org = created[0]
    org_id = str(org["id"])

    try:
        client.table("organization_memberships").insert(
            {"organization_id": org_id, "user_id": str(user_id), "membership_role": "owner"},
            returning=ReturnMethod.minimal,
        ).execute()
    except APIError as exc:
        removed = False
        if admin is not None:
            try:
                admin.table("organizations").delete().eq("id", org_id).execute()
                removed = True
            except Exception:
                logger.error("Could not remove organisation %s after membership failure", org_id)
        audit.record(admin, action="organization.create", outcome="failure", actor_user_id=user_id,
                     resource_type="organization", resource_id=org_id, request_id=request_id,
                     metadata={"stage": "owner_membership", "orphan_removed": removed,
                               "code": getattr(exc, "code", None)})
        raise database_error(exc, action="owner membership create") from None

    audit.record(admin, action="organization.create", outcome="success", actor_user_id=user_id,
                 actor_role="owner", resource_type="organization", resource_id=org_id,
                 request_id=request_id, metadata={"organization_type": body.organization_type})
    return {**{k: org.get(k) for k in ("id", "organization_name", "organization_type",
                                        "registration_number", "country_code", "created_at")},
            "my_role": "owner"}
