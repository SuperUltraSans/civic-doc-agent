"""compose — 할 일 카드 구성, 결과 조립 · Goal (지시서 5.10절).

할 일은 코드 규칙으로 만든다 (LLM이 할 일을 지어내지 않게).
전화 버튼 번호는 항상 공식 번호(시드·캐시·검색으로 확인한 번호). 문서에 적힌 번호는 넣지 않는다.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.agent.events import step_scope
from app.agent.state import AgentState
from app.schemas.agent import AgentStep
from app.schemas.document import BILL_TYPES, PAYMENT_NAMES
from app.schemas.result import AnalysisResult
from app.tools.impersonation import resolve_agency
from app.timeutil import now_iso

FALLBACK_TEL = "110"
FALLBACK_TEL_LABEL = "정부민원안내콜센터에 전화하기"


def _call_label(issuer: str | None) -> str:
    agency = resolve_agency(issuer)
    name = agency.short_name if agency else (issuer or "").strip()
    return f"{name}에 전화하기" if name else "공식 번호로 전화하기"


def _official_call(impersonation: dict[str, Any] | None, issuer: str | None) -> dict[str, Any] | None:
    phone = (impersonation or {}).get("officialPhone")
    if not phone:
        return None
    return {"type": "call", "label": _call_label(issuer), "tel": phone}


def _link_label(url: str) -> str:
    return "복지로에서 확인하기" if "bokjiro.go.kr" in url else "홈페이지에서 확인하기"


def build_todos(
    doc_id: str,
    document: dict[str, Any],
    impersonation: dict[str, Any] | None,
    deadline: dict[str, Any] | None,
    welfare: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """5.10절 할 일 규칙 표 그대로."""
    doc_type = document.get("docType")
    fields = document.get("fields") or {}
    issuer = document.get("issuer")
    status = (impersonation or {}).get("status")
    official_call = _official_call(impersonation, issuer)
    todos: list[dict[str, Any]] = []

    # 사칭 확인이 먼저: 진짜인지 확인한 뒤에 돈을 내도록 순서를 둔다
    if status in ("mismatch", "unknown"):
        call = official_call or {"type": "call", "label": FALLBACK_TEL_LABEL, "tel": FALLBACK_TEL}
        todos.append(
            {
                "id": f"{doc_id}-verify",
                "docId": doc_id,
                "title": "공식 번호로 진짜인지 확인하기" if status == "mismatch" else "공식 대표번호로 확인하기",
                "actions": [call],
            }
        )

    if doc_type in BILL_TYPES and fields.get("amount") and fields.get("dueDate") and status != "mismatch":
        actions: list[dict[str, Any]] = []
        if official_call:
            actions.append(official_call)
        actions.append(
            {
                "type": "calendar",
                "label": "달력에 추가하기",
                "title": (deadline or {}).get("calendarTitle") or f"{PAYMENT_NAMES[doc_type]} 내는 날 (읽어드림)",
                "date": fields["dueDate"],
            }
        )
        todos.append(
            {
                "id": f"{doc_id}-pay",
                "docId": doc_id,
                "title": f"{PAYMENT_NAMES[doc_type]} 내기",
                "amount": fields["amount"],
                "dueDate": fields["dueDate"],
                "actions": actions,
            }
        )

    if (fields.get("arrears") or 0) > 0 and status != "mismatch":
        todos.append(
            {
                "id": f"{doc_id}-installment",
                "docId": doc_id,
                "title": "나눠서 낼 수 있는지 물어보기",
                "actions": [official_call] if official_call else [],
            }
        )

    searched = [i for i in (welfare or {}).get("items", []) if not i.get("fixed")]
    if searched:
        first = searched[0]
        todos.append(
            {
                "id": f"{doc_id}-welfare",
                "docId": doc_id,
                "title": "도움 받을 수 있는 제도 알아보기",
                "actions": [{"type": "link", "label": _link_label(first["url"]), "url": first["url"]}],
            }
        )
    return todos


def finalize_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 id는 마지막 상태로, 처음 나온 순서대로."""
    order: list[str] = []
    last: dict[str, dict[str, Any]] = {}
    for s in steps:
        sid = s.get("id")
        if not sid:
            continue
        if sid not in last:
            order.append(sid)
        last[sid] = s
    return [AgentStep.model_validate(last[sid]).to_api() for sid in order]


def build_result(
    *,
    document: dict[str, Any],
    explanation: dict[str, Any],
    plan: list[dict[str, Any]],
    tool_results: dict[str, Any],
    steps: list[dict[str, Any]],
    doc_id: str | None = None,
) -> dict[str, Any]:
    doc_id = doc_id or uuid.uuid4().hex
    impersonation = tool_results.get("impersonation")
    deadline = tool_results.get("deadline")
    welfare = tool_results.get("welfare")
    todos = build_todos(doc_id, document, impersonation, deadline, welfare)
    tools: dict[str, Any] = {}
    if impersonation:
        tools["impersonation"] = impersonation
    if deadline:
        tools["deadline"] = deadline
    if welfare:
        tools["welfare"] = welfare  # 내부 키(region, fixed)는 스키마 검증에서 빠진다
    result = AnalysisResult.model_validate(
        {
            "docId": doc_id,
            "document": document,
            "explanation": explanation,
            "plan": plan,
            "tools": tools,
            "todos": todos,
            "steps": finalize_steps(steps),
            "createdAt": now_iso(),
        }
    )
    return result.to_api()


async def compose(state: AgentState) -> dict[str, Any]:
    async with step_scope(state, "compose", "해야 할 일을 정리하고 있어요", "해야 할 일을 정리했어요", node="compose") as step:
        doc_id = uuid.uuid4().hex
        todos_preview = build_todos(
            doc_id,
            state["document"],
            (state.get("tool_results") or {}).get("impersonation"),
            (state.get("tool_results") or {}).get("deadline"),
            (state.get("tool_results") or {}).get("welfare"),
        )
        step.detail = f"할 일 {len(todos_preview)}개: " + (", ".join(t["title"] for t in todos_preview) or "없음")
    result = build_result(
        document=state["document"],
        explanation=state["explanation"],
        plan=state.get("plan") or [],
        tool_results=state.get("tool_results") or {},
        steps=list(state.get("steps") or []) + [step.final],
        doc_id=doc_id,
    )
    return {"result": result, "steps": [step.final]}
