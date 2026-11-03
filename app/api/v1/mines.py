
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from postgrest.exceptions import APIError

from app.core.supabase import get_supabase_client
from app.schemas.mine import MineResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[MineResponse],
    summary="Get published chrome mines",
)
def get_mines(
    province: Optional[str] = Query(default=None, min_length=2),
    operating_status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = (
            get_supabase_client()
            .table("public_mines")
            .select("*")
        )

        if province:
            query = query.ilike("province", province.strip())

        if operating_status:
            query = query.eq(
                "operating_status",
                operating_status.strip(),
            )

        result = (
            query
            .order("mine_name")
            .range(offset, offset + limit - 1)
            .execute()
        )

        return result.data or []

    except APIError as exc:
        logger.exception(
            "Mine directory database error. Code=%s Message=%s Details=%s",
            exc.code,
            exc.message,
            exc.details,
        )

        raise HTTPException(
            status_code=503,
            detail="Mine directory is temporarily unavailable.",
        ) from exc

    except Exception:
        logger.exception("Unexpected mine directory failure")

        raise HTTPException(
            status_code=503,
            detail="Mine directory is temporarily unavailable.",
        )

