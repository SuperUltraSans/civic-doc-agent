"""/api/simplify — 보관된 추출 결과로 설명만 level 2로 다시 만든다 (지시서 3.4절)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.agent.nodes.explain import simplify_explanation
from app.api.errors import RESULT_GONE, ApiException
from app.config import get_settings
from app.schemas.result import SimplifyRequest
from app.sessions.manager import get_manager

router = APIRouter(prefix="/api")


@router.post("/simplify")
async def simplify(body: SimplifyRequest) -> dict[str, Any]:
    manager = get_manager()
    stored = manager.get_result(body.doc_id)
    if stored is None:
        raise ApiException(404, "server", RESULT_GONE)
    if stored.explanation.get("level") == 2:
        return stored.explanation
    if get_settings().agent_mode == "scripted" and stored.scripted_level2:
        explanation = stored.scripted_level2
    else:
        explanation = await simplify_explanation(stored.document, stored.explanation)
    stored.explanation = explanation
    return explanation
