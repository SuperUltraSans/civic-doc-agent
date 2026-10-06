"""plan — 필수 규칙 + LLM 플래너 · Planning, Reasoning (지시서 5.5절).

(1) 필수 규칙(코드)으로 강제 도구를 정하고 (2) LLM 플래너가 복지 연계 등 선택 도구를 판단한다.
병합 규칙
- 필수 도구가 LLM 계획에 없으면 추가하고 reason 에 규칙 근거를 쓴다.
- LLM이 목록 밖 도구를 내면 버린다.
- search_welfare 가 계획에 있고 profile.region 이 없으면 ask_user 로 간다.
병합 결과를 plan 이벤트로 보낸다(프론트가 예정 단계를 미리 표시).
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.events import push_event, step_scope
from app.agent.state import AgentState
from app.llm.client import LLMError, get_llm, load_prompt
from app.llm.schemas import PlanOut
from app.schemas.agent import PLANNABLE_TOOLS, PlanItem
from app.textutil import ieyo, is_assertive, numeric_issue

TOOL_ORDER = {name: i for i, name in enumerate(PLANNABLE_TOOLS)}
TOOL_DESCRIPTIONS = {
    "check_impersonation": "연락처·주소를 기관 공식 정보와 비교하고 사칭 수법 자료와 대조",
    "manage_deadline": "내야 하는 날짜·금액 정리, 달력 추가",
    "search_welfare": "도움 받을 수 있는 복지 제도 찾기 (지역 정보가 있으면 더 정확)",
}


def required_tools(document: dict[str, Any]) -> list[dict[str, Any]]:
    """필수 규칙 (코드). LLM 판단과 관계없이 실행한다."""
    fields = document.get("fields") or {}
    doc_type = document.get("docType")
    items: list[dict[str, Any]] = []
    if fields.get("phone") or fields.get("url") or doc_type == "suspicious_message":
        reason = (
            "사칭이 의심되는 문자라 공식 정보와 비교해요"
            if doc_type == "suspicious_message" and not (fields.get("phone") or fields.get("url"))
            else "문서에 연락처가 있어 공식 정보와 비교해요"
        )
        items.append({"tool": "check_impersonation", "reason": reason, "required": True})
    if fields.get("dueDate") and doc_type != "suspicious_message":
        items.append({"tool": "manage_deadline", "reason": "문서에 내야 하는 날짜가 있어 기한을 정리해요", "required": True})
    return items


def default_situation(document: dict[str, Any]) -> str:
    """숫자 없는 기본 상황 문장 (LLM 플래너가 실패했거나 규칙을 어겼을 때)."""
    label = document.get("docTypeLabel") or "문서"
    if (document.get("fields") or {}).get("arrears"):
        return f"밀린 금액이 포함된 {ieyo(label)}"
    return ieyo(label)


def heuristic_optional_tools(document: dict[str, Any]) -> list[dict[str, Any]]:
    """LLM 플래너가 실패했을 때의 대체 판단 (코드)."""
    fields = document.get("fields") or {}
    doc_type = document.get("docType")
    if (fields.get("arrears") or 0) > 0:
        return [{"tool": "search_welfare", "reason": "밀린 금액이 있어 나눠 내기나 지원 제도를 찾아봐요"}]
    if doc_type == "basic_pension_notice":
        return [{"tool": "search_welfare", "reason": "기초연금 안내문이라 함께 받을 수 있는 제도를 찾아봐요"}]
    return []


def merge_plan(rule_items: list[dict[str, Any]], llm_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """필수 도구 강제 + 목록 밖 도구 제거. (병합 결과, 버린 도구 이름)"""
    merged: dict[str, dict[str, Any]] = {}
    dropped: list[str] = []
    rules = {r["tool"]: r for r in rule_items}
    for item in llm_items:
        tool = str(item.get("tool", "")).strip()
        if tool not in TOOL_ORDER:
            dropped.append(tool)
            continue
        if tool in merged:
            continue
        reason = str(item.get("reason", "")).strip()
        # 이유는 "확인 과정 보기"에 그대로 보이므로 단정 표현·숫자(금액·날짜·번호)가 있으면 규칙 문장으로 바꾼다
        if not reason or is_assertive(reason) or numeric_issue(reason):
            reason = rules[tool]["reason"] if tool in rules else "문서 내용에 필요한 확인이라 실행해요"
        merged[tool] = {"tool": tool, "reason": reason, "required": tool in rules}
    for tool, rule in rules.items():
        if tool not in merged:
            merged[tool] = dict(rule)
    ordered = sorted(merged.values(), key=lambda i: TOOL_ORDER[i["tool"]])
    return [PlanItem.model_validate(i).to_api() for i in ordered], dropped


def needs_region(plan: list[dict[str, Any]], profile: dict[str, Any]) -> bool:
    return any(p["tool"] == "search_welfare" for p in plan) and not (profile or {}).get("region")


async def plan(state: AgentState) -> dict[str, Any]:
    document = state["document"]
    profile = state.get("profile") or {}
    rules = required_tools(document)
    async with step_scope(state, "plan", "무엇을 확인할지 정하고 있어요", "확인할 일을 정했어요", node="plan") as step:
        fields = dict(document.get("fields") or {})
        for key in ("phone", "url"):
            if fields.get(key):
                fields[key] = "(있음)"
        payload = {
            "document": {"docType": document.get("docType"), "docTypeLabel": document.get("docTypeLabel"), "issuer": document.get("issuer"), "fields": fields},
            "hasRegion": bool(profile.get("region")),
            "hasAgeGroup": bool(profile.get("ageGroup")),
            "tools": TOOL_DESCRIPTIONS,
        }
        try:
            out = await get_llm().structured(
                role="reason",
                node="plan",
                system=load_prompt("plan"),
                user=json.dumps(payload, ensure_ascii=False),
                schema=PlanOut,
            )
            situation = out.situation.strip()
            llm_items = [{"tool": p.tool, "reason": p.reason} for p in out.plan]
            source = "LLM 플래너"
            # 상황 문장도 화면(확인 과정 보기)과 복지 재정렬 입력에 쓰이므로 숫자·단정 표현이 있으면 기본 문장으로
            why = numeric_issue(situation) or ("단정 표현" if is_assertive(situation) else None)
            if not situation or why:
                situation = default_situation(document)
                source += f" (상황 문장 {why or '비어 있음'} → 기본 문장)"
        except LLMError as exc:
            situation = default_situation(document)
            llm_items = heuristic_optional_tools(document)
            source = f"LLM 플래너 실패({type(exc).__name__}) → 규칙 기반 대체"
        merged, dropped = merge_plan(rules, llm_items)
        forced = [r["tool"] for r in rules if r["tool"] not in {i["tool"] for i in llm_items}]
        detail = [f"상황: {situation}", source, "계획: " + (", ".join(f"{p['tool']}{'(필수)' if p['required'] else ''}" for p in merged) or "없음")]
        if forced:
            detail.append(f"규칙으로 추가: {','.join(forced)}")
        if dropped:
            detail.append(f"목록 밖 도구 버림: {','.join(dropped)}")
        if needs_region(merged, profile) and not state.get("asked"):
            detail.append("지역 정보 없음 → 질문 1회")
        step.detail = " | ".join(detail)
    push_event(state.get("session_id"), "plan", merged)
    return {"plan": merged, "situation": situation, "steps": [step.final]}


def route_after_plan(state: AgentState) -> str:
    if needs_region(state.get("plan") or [], state.get("profile") or {}) and not state.get("asked"):
        return "ask_user"
    return "run_tools"
