import random
import string
from fastapi import APIRouter, HTTPException, Header
from app.core.supabase import get_supabase_client
from app.schemas.batch import SampleBatchCreate, SampleBatchResponse

router = APIRouter()

def generate_tracking_number() -> str:
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"CHR-{chars}"

@router.post("/", response_model=SampleBatchResponse)
def create_sample_batch(batch_in: SampleBatchCreate, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    supabase = get_supabase_client()
    user_res = supabase.auth.get_user(token)
    
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    user_id = user_res.user.id
    tracking_no = generate_tracking_number()
    
    batch_data = {
        "tracking_number": tracking_no,
        "client_id": user_id,
        "mine_id": str(batch_in.mine_id),
        "lab_id": str(batch_in.lab_id),
        "sample_type": batch_in.sample_type,
        "target_parameters": batch_in.target_parameters,
        "pickup_address": batch_in.pickup_address,
        "status": "logged"
    }
    
    res = supabase.table("sample_batches").insert(batch_data).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create sample batch")
    
    return res.data[0]