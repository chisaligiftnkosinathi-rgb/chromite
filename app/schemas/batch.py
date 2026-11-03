from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime

class SampleBatchCreate(BaseModel):
    mine_id: UUID
    lab_id: UUID
    sample_type: str
    target_parameters: List[str]
    pickup_address: str

class SampleBatchResponse(BaseModel):
    id: UUID
    tracking_number: str
    client_id: UUID
    mine_id: Optional[UUID]
    lab_id: Optional[UUID]
    status: str
    sample_type: str
    target_parameters: List[str]
    cr2o3_pct: Optional[float] = None
    fe_cr_ratio: Optional[float] = None
    sio2_pct: Optional[float] = None
    moisture_pct: Optional[float] = None
    coa_pdf_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True