from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mine_name: str
    slug: str
    commodity: str
    province: str
    district: Optional[str] = None
    nearest_town: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    mine_type: Optional[str] = None
    operating_status: str
    verification_status: str
    public_description: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    source_checked_at: Optional[datetime] = None