from fastapi import APIRouter, Depends

from app.core.permissions import Principal, get_principal
from app.schemas.organization import MembershipResponse, MeResponse

router = APIRouter()


@router.get("/", response_model=MeResponse, summary="The signed-in user, memberships and staff role")
def read_me(principal: Principal = Depends(get_principal)):
    return MeResponse(
        user_id=principal.user_id,
        email=principal.user.email,
        memberships=[MembershipResponse(organization_id=m.organization_id, role=m.role)
                     for m in principal.memberships],
        staff_role=principal.staff_role,
    )
