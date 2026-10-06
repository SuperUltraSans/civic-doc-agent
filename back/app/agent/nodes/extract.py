"""extract — 문서 종류 분류 + 필드 추출 (VLM 한 번 호출) · Goal (지시서 5.2절).

재추출(validate의 Feedback)일 때는 의심 필드만 다시 묻는 집중 프롬프트를 쓴다.
image_bytes는 재추출까지 끝나면 즉시 상태에서 지운다.
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.events import emit_step, step_scope
from app.agent.state import AgentState
from app.llm.client import get_llm, load_prompt
from app.llm.schemas import ExtractOut, RecheckOut
from app.schemas.document import DOC_TYPE_LABELS, FIELD_NAMES
from app.textutil import ieyo
from app.timeutil import today
from app.tools.impersonation import organization_name

EXTRACT_TIMEOUT = 30.0
MAX_EXTRACT_ATTEMPTS = 2
FIELD_LABELS = {
    "amount": "내야 하는 금액(납기 내 금액)",
    "dueDate": "납부 기한",
    "billingMonth": "고지 대상 월",
    "arrears": "체납액",
    "phone": "문의 전화번호",
    "url": "인터넷 주소",
}


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fields_from_output(fields: Any) -> dict[str, Any]:
    data = fields.to_api() if hasattr(fields, "to_api") else dict(fields or {})
    out: dict[str, Any] = {}
    for name in FIELD_NAMES:
        value = data.get(name)
        if name in ("amount", "arrears"):
            out[name] = value if isinstance(value, int) else None
        else:
            out[name] = _clean_str(value)
    return out


def confidence_from_output(conf: Any) -> dict[str, float | None]:
    data = conf.to_api() if hasattr(conf, "to_api") else dict(conf or {})
    return {name: data.get(name) for name in FIELD_NAMES}


def build_document(doc_type: str, issuer: str | None, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "docType": doc_type,
        "docTypeLabel": DOC_TYPE_LABELS.get(doc_type, DOC_TYPE_LABELS["unknown"]),
        "issuer": organization_name(issuer),  # 프롬프트 규칙을 어겨 직위가 남아도 관청 이름으로 ("○○구청장" → "○○구청")
        "fields": {k: v for k, v in fields.items() if v is not None},
    }


async def extract(state: AgentState) -> dict[str, Any]:
    attempts = state.get("extract_attempts", 0)
    if attempts == 0:
        return await _first_pass(state)
    return await _recheck(state, attempts)


async def _first_pass(state: AgentState) -> dict[str, Any]:
    image = state.get("image_bytes")
    async with step_scope(state, "read_text", "사진에서 글자를 읽고 있어요", "글자를 읽었어요", node="extract") as step:
        out = await get_llm().structured(
            role="vision",
            node="extract",
            system=load_prompt("extract"),
            user=f"오늘 날짜(Asia/Seoul): {today().isoformat()}\n사진 속 문서를 읽고 스키마에 맞춰 답하세요.",
            schema=ExtractOut,
            image=image,
            timeout=EXTRACT_TIMEOUT,
        )
        fields = fields_from_output(out.fields)
        read = [k for k, v in fields.items() if v is not None]
        step.detail = f"docType={out.doc_type}, legible={str(out.legible).lower()}, 읽은 필드: {','.join(read) or '없음'}"

    document = build_document(out.doc_type, out.issuer, fields)
    steps = [step.final]
    if out.legible and out.doc_type != "unknown":
        steps.append(
            emit_step(
                state.get("session_id"),
                {"id": "classify", "label": ieyo(document["docTypeLabel"]), "status": "done", "detail": f"문서 종류 분류: {out.doc_type}"},
            )
        )
    return {
        "document": document,
        "field_confidence": confidence_from_output(out.confidence),
        "legible": bool(out.legible),
        "raw_excerpt": (out.raw_text_excerpt or "")[:600] or None,
        "extract_attempts": 1,
        "steps": steps,
    }


async def _recheck(state: AgentState, attempts: int) -> dict[str, Any]:
    targets = state.get("recheck_fields") or []
    blind = set(state.get("recheck_blind") or [])
    document = dict(state["document"])
    fields = dict(document.get("fields") or {})
    confidence = dict(state.get("field_confidence") or {})
    payload = {
        "docType": document["docType"],
        "recheckFields": {name: FIELD_LABELS.get(name, name) for name in targets},
        # 연락처·주소 값은 보내지 않는다. 기간 밖 기한은 앞선 값에 끌려가지 않게 보여 주지 않는다 (두 번 같아야 인정)
        "previousValues": {name: fields.get(name) for name in targets if name not in ("phone", "url") and name not in blind},
    }
    out = await get_llm().structured(
        role="vision",
        node="extract_recheck",
        system=load_prompt("extract_recheck"),
        user=f"오늘 날짜(Asia/Seoul): {today().isoformat()}\n다시 읽을 필드:\n{json.dumps(payload, ensure_ascii=False)}",
        schema=RecheckOut,
        image=state.get("image_bytes"),
        timeout=EXTRACT_TIMEOUT,
    )
    new_fields = fields_from_output(out.fields)
    new_conf = confidence_from_output(out.confidence)
    for name in targets:
        value = new_fields.get(name)
        if value is None:
            fields.pop(name, None)
        else:
            fields[name] = value
        confidence[name] = new_conf.get(name)
    document["fields"] = fields
    update: dict[str, Any] = {
        "document": document,
        "field_confidence": confidence,
        "extract_attempts": attempts + 1,
        "recheck_fields": None,
    }
    if attempts + 1 >= MAX_EXTRACT_ATTEMPTS:
        update["image_bytes"] = None  # 재추출까지 끝났으니 이미지를 지운다
    return update
