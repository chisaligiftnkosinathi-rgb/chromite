from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_DIRECTORY_STATUS = ("Directory-record verification status. It is NOT an accreditation "
                     "status; accreditation is per test, see accreditation scopes.")


class LaboratoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    laboratory_name: str
    country_code: str
    province: Optional[str] = None
    city: Optional[str] = None
    physical_address: Optional[str] = None
    website_url: Optional[str] = None
    verification_status: str = Field(description=_DIRECTORY_STATUS)


class AccreditationScopePublic(BaseModel):
    """A verified, currently valid accreditation scope entry (per analyte and method)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    laboratory_id: UUID
    accreditation_body: str
    accreditation_number: str
    certificate_reference: Optional[str] = None
    standard: str
    scope_title: str
    material_matrix: str
    analyte_or_parameter: str
    test_method: str
    scope_valid_from: Optional[date] = None
    scope_valid_until: Optional[date] = None
    verification_status: str


class SamplingProviderPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_name: str
    country_code: str
    province: Optional[str] = None
    city: Optional[str] = None
    physical_address: Optional[str] = None
    website_url: Optional[str] = None
    service_description: Optional[str] = None
    verification_status: str = Field(description=_DIRECTORY_STATUS)


class SamplingServicePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    service_name: str
    material_type: str
    service_description: Optional[str] = None
    service_status: str
