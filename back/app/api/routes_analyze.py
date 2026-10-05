"""/api/analyze, /events, /answer (지시서 3.1~3.3절)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.agent.nodes.preprocess import UnsupportedImage, sniff_format
from app.api.errors import SESSION_GONE, UNSUPPORTED_IMAGE, ApiException
from app.config import get_settings
from app.schemas.agent import AnalyzeStarted, AnswerRequest, UserProfile
from app.sessions.manager import TooBusyError, get_manager

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
SCENARIOS = {"arrears", "blurry", "smishing", "local_tax", "error", "pension"}


def _parse_profile(raw: str | None) -> dict[str, Any]:
    """프론트가 보낸 사용자 정보(지역·나이대). 이상한 값은 버린다. 서버에 저장하지 않는다."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        profile = UserProfile.model_validate(data if isinstance(data, dict) else {})
    except (ValueError, TypeError):
        return {}
    out = profile.to_api()
    if "region" in out:
        out["region"] = str(out["region"]).strip()[:20] or None
        if out["region"] is None:
            out.pop("region")
    return out


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@router.post("/analyze", response_model=None)
async def analyze(
    request: Request,
    image: UploadFile = File(...),
    profile: str | None = Form(None),
    scenario: str | None = Form(None),
) -> dict[str, Any]:
    manager = get_manager()
    if not manager.allow_request(_client_key(request)):
        raise ApiException(429, "server", "요청이 많아요. 잠시 후 다시 해 주세요")

    declared = (image.content_type or "").split(";")[0].strip().lower()
    if declared and declared not in ALLOWED_CONTENT_TYPES and declared != "application/octet-stream":
        raise ApiException(415, "unsupported_image", UNSUPPORTED_IMAGE)
    data = await image.read(MAX_UPLOAD_BYTES + 1)
    await image.close()
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ApiException(415, "unsupported_image", UNSUPPORTED_IMAGE)
    try:
        sniff_format(data)
    except UnsupportedImage:
        raise ApiException(415, "unsupported_image", UNSUPPORTED_IMAGE) from None

    settings = get_settings()
    scenario_key = scenario if scenario in SCENARIOS else None
    if settings.agent_mode == "scripted":
        from app.agent.scripted import run_scripted as runner
    else:
        from app.agent.runner import run_live as runner
    try:
        session = manager.create(image=data, profile=_parse_profile(profile), scenario=scenario_key, runner=runner)
    except TooBusyError:
        raise ApiException(503, "server", "지금 확인하는 분이 많아요. 잠시 후 다시 해 주세요") from None
    finally:
        del data
    return AnalyzeStarted(session_id=session.id).to_api()


@router.get("/analyze/{session_id}/events")
async def events(session_id: str) -> StreamingResponse:
    session = get_manager().get(session_id)
    if session is None:
        raise ApiException(404, "server", SESSION_GONE)
    return StreamingResponse(
        session.stream(get_settings().sse_ping_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/analyze/{session_id}/answer", status_code=204)
async def answer(session_id: str, body: AnswerRequest) -> Response:
    session = get_manager().get(session_id)
    if session is None:
        raise ApiException(404, "server", SESSION_GONE)
    value = body.value.strip()[:20] if isinstance(body.value, str) else None
    if not session.submit_answer(body.field, value or None):
        raise ApiException(409, "server", "지금은 답을 받을 수 없어요. 처음부터 다시 해 주세요")
    return Response(status_code=204)
