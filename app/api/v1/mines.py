import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from postgrest.exceptions import APIError

from app.core.supabase import get_supabase_client
from app.core.rate_limit import public_rate_limit
from app.schemas.mine import MineResponse

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(public_rate_limit)])

# Values allowed by the mines.operating_status CHECK constraint.
OperatingStatus = Literal[
    "operating",
    "care_and_maintenance",
    "temporarily_closed",
    "closed",
    "under_development",
    "unknown",
]

# Letters, spaces, hyphens and apostrophes only (e.g. "KwaZulu-Natal").
# This excludes the LIKE/PostgREST wildcards %, _ and *.
PROVINCE_PATTERN = r"^[A-Za-z][A-Za-z '\-]{1,49}$"


@router.get(
    "/",
    response_model=List[MineResponse],
    summary="Get published chrome mines",
)
def get_mines(
    province: Optional[str] = Query(
        default=None, min_length=2, max_length=50, pattern=PROVINCE_PATTERN
    ),
    operating_status: Optional[OperatingStatus] = None,
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
            query = query.eq("operating_status", operating_status)

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



@router.get(
    "/{slug}",
    response_model=MineResponse,
    summary="One published chrome mine",
)
def get_mine(slug: str = Path(min_length=3, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")):
    try:
        rows = (
            get_supabase_client()
            .table("public_mines")
            .select("*")
            .eq("slug", slug)
            .limit(1)
            .execute()
            .data
        ) or []
    except Exception:
        logger.exception("Mine lookup failed")
        raise HTTPException(status_code=503, detail="Mine directory is temporarily unavailable.")
    if not rows:
        raise HTTPException(status_code=404, detail="Mine not found.")
    return rows[0]
