"""Public laboratory and sampling-provider directories (published rows only)."""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from supabase import Client

from app.api.deps import get_public_client
from app.core.rate_limit import public_rate_limit
from app.schemas.directory import (
    AccreditationScopePublic,
    LaboratoryPublic,
    SamplingProviderPublic,
    SamplingServicePublic,
)

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(public_rate_limit)])

PROVINCE_PATTERN = r"^[A-Za-z][A-Za-z '\-]{1,49}$"
_UNAVAILABLE = HTTPException(503, detail="Directory is temporarily unavailable.")


def _run(query, what: str):
    try:
        return query.execute().data or []
    except APIError as exc:
        logger.warning("Directory query failed (%s, code=%s)", what, exc.code)
        raise _UNAVAILABLE from None
    except Exception:
        logger.exception("Unexpected directory failure (%s)", what)
        raise _UNAVAILABLE from None


@router.get("/laboratories/", response_model=List[LaboratoryPublic],
            summary="Published laboratories")
def list_laboratories(
    province: Optional[str] = Query(default=None, min_length=2, max_length=50,
                                    pattern=PROVINCE_PATTERN),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    client: Client = Depends(get_public_client),
):
    query = client.table("public_laboratories").select("*")
    if province:
        query = query.ilike("province", province)
    return _run(query.order("laboratory_name").range(offset, offset + limit - 1), "laboratories")


@router.get("/laboratories/{laboratory_id}", response_model=LaboratoryPublic,
            summary="One published laboratory")
def get_laboratory(laboratory_id: UUID, client: Client = Depends(get_public_client)):
    rows = _run(client.table("public_laboratories").select("*")
                .eq("id", str(laboratory_id)).limit(1), "laboratory")
    if not rows:
        raise HTTPException(404, detail="Laboratory not found.")
    return rows[0]


@router.get("/laboratories/{laboratory_id}/accreditation-scopes",
            response_model=List[AccreditationScopePublic],
            summary="Verified, currently valid accreditation scope entries for a laboratory")
def list_scopes(laboratory_id: UUID, client: Client = Depends(get_public_client)):
    return _run(client.table("public_lab_accreditation_scopes").select("*")
                .eq("laboratory_id", str(laboratory_id))
                .order("analyte_or_parameter"), "accreditation scopes")


@router.get("/sampling-providers/", response_model=List[SamplingProviderPublic],
            summary="Published sampling providers")
def list_sampling_providers(
    province: Optional[str] = Query(default=None, min_length=2, max_length=50,
                                    pattern=PROVINCE_PATTERN),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    client: Client = Depends(get_public_client),
):
    query = client.table("public_sampling_providers").select("*")
    if province:
        query = query.ilike("province", province)
    return _run(query.order("provider_name").range(offset, offset + limit - 1), "sampling providers")


@router.get("/sampling-providers/{provider_id}/services",
            response_model=List[SamplingServicePublic],
            summary="Verified, published services of a sampling provider")
def list_provider_services(provider_id: UUID, client: Client = Depends(get_public_client)):
    return _run(client.table("public_sampling_services").select("*")
                .eq("provider_id", str(provider_id)).order("service_name"), "sampling services")
