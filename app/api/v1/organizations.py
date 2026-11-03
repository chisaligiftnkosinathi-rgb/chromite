"""Customer organisations. A personal customer is a single-member organisation.

Reads use the caller's own RLS-scoped client. Creation calls one database
function, `create_organization_with_owner`, which writes the organisation, the
caller's owner membership and the audit event in a single transaction: all
three or none. The privileged client is used only to record *refused*
attempts (best effort), since a refused transaction leaves no audit row.
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from postgrest.exceptions import APIError
from supabase import Client

from app.api.deps import get_admin_client_optional, get_user_client
from app.core.errors import database_error
from app.core.permissions import Principal, get_principal
from app.core.rate_limit import write_rate_limit
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.services import audit

logger = logging.getLogger(__name__)
router = APIRouter()

_COLUMNS = "id, organization_name, organization_type, registration_number, country_code, created_at"
CREATE_FUNCTION = "create_organization_with_owner"


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
             summary="Create an organisation; you become its owner (atomic, audited)")
def create_organization(
    body: OrganizationCreate,
    request: Request,
    principal: Principal = Depends(get_principal),
    client: Client = Depends(get_user_client),
    admin: Client | None = Depends(get_admin_client_optional),
):
    request_id = getattr(request.state, "request_id", None)
    try:
        result = client.rpc(CREATE_FUNCTION, {
            "p_organization_name": body.organization_name,
            "p_organization_type": body.organization_type,
            "p_registration_number": body.registration_number,
            "p_request_id": request_id,
        }).execute().data
    except APIError as exc:
        audit.record(admin, action="organization.create", outcome="denied",
                     actor_user_id=principal.user_id, request_id=request_id,
                     metadata={"code": getattr(exc, "code", None)})
        raise database_error(exc, action="organisation create") from None
    if not isinstance(result, dict) or not result.get("id"):
        logger.error("Unexpected result from %s", CREATE_FUNCTION)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service temporarily unavailable.")
    return {**result, "my_role": "owner"}
