"""Write platform audit events (append-only table, privileged client only).

Audit writes never raise into the request: a failure is logged as an error so
operations can see it, and the business action's own outcome stands.
Metadata must never contain tokens, passwords, keys or personal documents.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from postgrest.types import ReturnMethod
from supabase import Client

logger = logging.getLogger(__name__)


def record(
    admin: Client | None,
    *,
    action: str,
    outcome: str,
    actor_user_id: UUID | None = None,
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    if admin is None:
        logger.error("Audit event not recorded (no privileged client): action=%s outcome=%s",
                     action, outcome)
        return False
    row = {
        "action": action,
        "outcome": outcome,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_role": actor_role,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "request_id": request_id,
        "metadata": metadata or {},
    }
    try:
        admin.table("platform_audit_logs").insert(row, returning=ReturnMethod.minimal).execute()
        return True
    except Exception as exc:
        logger.error("Audit event not recorded (%s): action=%s outcome=%s",
                     type(exc).__name__, action, outcome)
        return False
