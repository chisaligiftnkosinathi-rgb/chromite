from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Types a user may choose when registering. Provider types ("laboratory",
# "sampling_provider") are deliberately absent: provider status is granted only
# through a verified provider record, never by self-declaration.
SelfServiceOrganizationType = Literal["customer", "mine_owner", "mine_operator", "trader", "other"]


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    organization_name: str = Field(min_length=2, max_length=200)
    organization_type: SelfServiceOrganizationType = "customer"
    registration_number: Optional[str] = Field(default=None, max_length=50)
    country_code: Literal["ZA"] = "ZA"

    @field_validator("organization_name")
    @classmethod
    def printable(cls, value: str) -> str:
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("organisation name contains control characters")
        return value


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_name: str
    organization_type: str
    registration_number: Optional[str] = None
    country_code: str
    created_at: datetime
    my_role: Optional[str] = None


class MembershipResponse(BaseModel):
    organization_id: UUID
    role: str


class MeResponse(BaseModel):
    user_id: UUID
    email: Optional[str] = None
    memberships: list[MembershipResponse]
    staff_role: Optional[str] = None
