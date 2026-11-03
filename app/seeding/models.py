"""Validated seed-record models for the chrome mine and laboratory pilot datasets.

Seed files describe *candidates*, never verified facts. These models enforce:
- every record cites a source (name, https URL, date checked);
- a seed can never mark anything published, verified or accredited;
- coordinates come in pairs and inside South Africa's bounding box;
- accreditation claims are always "unverified" and attributed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SourceKind = Literal[
    "official_government",
    "company_primary",
    "company_press_release",
    "conference_paper",
    "trade_press",
]

# Values allowed by mines.operating_status (initial schema).
OperatingStatus = Literal[
    "operating",
    "care_and_maintenance",
    "temporarily_closed",
    "closed",
    "under_development",
    "unknown",
]

SOUTH_AFRICAN_PROVINCES = {
    "Eastern Cape",
    "Free State",
    "Gauteng",
    "KwaZulu-Natal",
    "Limpopo",
    "Mpumalanga",
    "North West",
    "Northern Cape",
    "Western Cape",
}

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SeedSource(_Strict):
    name: str = Field(min_length=3, max_length=300)
    url: HttpUrl
    published: Optional[date] = None
    checked_at: date
    kind: SourceKind

    @field_validator("url")
    @classmethod
    def https_only(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("source URL must use https")
        return value

    @model_validator(mode="after")
    def dates_make_sense(self):
        if self.published and self.published > self.checked_at:
            raise ValueError("published date is after the date the source was checked")
        return self


class MineSeed(_Strict):
    slug: str = Field(min_length=3, max_length=80)
    mine_name: str = Field(min_length=2, max_length=200)
    province: Optional[str] = None
    nearest_town: Optional[str] = Field(default=None, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    mine_type: Optional[str] = Field(default=None, max_length=50)
    operating_status: OperatingStatus = "unknown"
    public_description: str = Field(min_length=10, max_length=1000)
    source: SeedSource
    legal_right_leads: list[str] = Field(default_factory=list)
    review_notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value: str) -> str:
        if not SLUG_PATTERN.match(value):
            raise ValueError("slug must be lowercase words separated by hyphens")
        return value

    @field_validator("province")
    @classmethod
    def known_province(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in SOUTH_AFRICAN_PROVINCES:
            raise ValueError(f"unknown South African province: {value!r}")
        return value

    @model_validator(mode="after")
    def coordinates(self):
        lat, lon = self.latitude, self.longitude
        if (lat is None) != (lon is None):
            raise ValueError("latitude and longitude must be given together")
        if lat is not None and not (-35.0 <= lat <= -22.0 and 16.0 <= lon <= 33.0):
            raise ValueError("coordinates fall outside South Africa")
        return self

    @property
    def missing_required(self) -> list[str]:
        """Fields the mines table requires that this source did not supply."""
        return ["province"] if self.province is None else []


class AccreditationClaim(_Strict):
    claim: str = Field(min_length=10, max_length=1000)
    # What is being claimed: that accreditation is held, or only being pursued.
    claim_type: Literal["states_accredited", "pursuing_accreditation"]
    accreditation_body: Literal["SANAS"]
    accreditation_number_claimed: Optional[str] = Field(default=None, pattern=r"^T\d{4}$")
    claimed_by: Literal["laboratory", "third_party"]
    # A seed may never assert verification. Only a verification officer can.
    status: Literal["unverified"]


class LaboratorySeed(_Strict):
    laboratory_name: str = Field(min_length=3, max_length=200)
    city: Optional[str] = Field(default=None, max_length=100)
    province: Optional[str] = None
    physical_address: Optional[str] = Field(default=None, max_length=300)
    website_url: Optional[HttpUrl] = None
    source: SeedSource
    accreditation_claims: list[AccreditationClaim] = Field(default_factory=list)
    review_notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("province")
    @classmethod
    def known_province(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in SOUTH_AFRICAN_PROVINCES:
            raise ValueError(f"unknown South African province: {value!r}")
        return value

    @property
    def match_key(self) -> tuple[str, str]:
        return (self.laboratory_name.casefold(), (self.city or "").casefold())


class _Dataset(_Strict):
    dataset: str
    version: int = Field(ge=1)
    compiled_on: date
    notice: str = Field(min_length=20)


class MineDataset(_Dataset):
    records: list[MineSeed]

    @model_validator(mode="after")
    def unique_slugs(self):
        slugs = [r.slug for r in self.records]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        if dupes:
            raise ValueError(f"duplicate slugs: {sorted(dupes)}")
        return self


class LaboratoryDataset(_Dataset):
    records: list[LaboratorySeed]

    @model_validator(mode="after")
    def unique_labs(self):
        keys = [r.match_key for r in self.records]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"duplicate laboratories: {sorted(dupes)}")
        return self
