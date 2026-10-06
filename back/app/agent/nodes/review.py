"""review · run_followups — 도구 결과를 보고 추가 도구를 고르고 실행한다 · Reasoning, Tool Use (지시서 5.9절 보완).

evaluate(코드 점검)가 끝나면 한 번 실행한다. 계획 모델이 도구 실행 결과를 보고, 정해진 추가 도구 중 필요한 것을
최대 2개 고른다. 고른 도구는 run_followups 가 병렬로 실행하고, 다시 evaluate 를 거쳐 compose 로 간다.

    run_tools → evaluate → review ─(추가 도구 있음)→ run_followups → evaluate → compose
                                  └(없음)──────────────────────────────────────→ compose

- LLM은 "무엇을 왜 더 할지"만 정한다. 공식 번호·사칭 판정·할 일은 지금처럼 코드가 정한다.
- 추가 도구
  - find_official_contact: 공식 번호를 못 찾았을 때 다른 기관 이름으로 다시 찾는다.
    번호는 여전히 시드 표·캐시·.go.kr 검색(기관명이 페이지에 있어야 채택)으로만 정해진다. LLM은 이름만 제안한다.
  - search_welfare: 다른 검색어로 복지 제도를 더 찾거나, 계획에 없었지만 필요해 보이면 찾는다.
- 목록 밖 도구, 조건에 맞지 않는 도구, 숫자가 섞인 이유, 이상한 기관 이름·검색어는 코드가 버린다.
- 질문은 하지 않는다 (세션당 1회 원칙). 지역을 모르면 지역 조건 없이 찾는다.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.agent.events import StepHandle
from app.agent.nodes.run_tools import ToolOutcome, _with_step
from app.agent.state import AgentState
from app.llm.client import LLMError, get_llm, load_prompt
from app.llm.schemas import ReviewOut
from app.textutil import is_assertive, numeric_issue
from app.tools.impersonation import check_impersonation, organization_name
from app.tools.welfare import merge_welfare, search_welfare, searched_count

LABEL = "찾은 결과를 보고 더 확인할 것이 있는지 살피고 있어요"
DONE_LABEL = "찾은 결과를 보고 더 확인할 것을 정했어요"
MAX_ACTIONS = 2
FOLLOWUP_TOOLS = ("find_official_contact", "search_welfare")
DEFAULT_REASONS = {
    "find_official_contact": "공식 번호를 찾지 못해 다른 기관 이름으로 다시 찾아봐요",
    "search_welfare": "도움 받을 수 있는 제도를 조금 더 찾아봐요",
}
_AGENCY_NAME = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z ]{1,29}")
_KEYWORD = re.compile(r"[가-힣]{2,10}")


def _last_step_detail(state: AgentState, step_id: str) -> str | None:
    for step in reversed(state.get("steps") or []):
        if step.get("id") == step_id and step.get("detail"):
            return str(step["detail"])
    return None


def availability(state: AgentState) -> dict[str, bool]:
    """지금 부를 수 있는 추가 도구."""
    results = state.get("tool_results") or {}
    imp = results.get("impersonation")
    return {
        "find_official_contact": imp is not None and not imp.get("officialPhone"),
        "search_welfare": True,
    }


def review_payload(state: AgentState) -> dict[str, Any]:
    """검토 모델 입력. 문서의 연락처·주소 값은 넣지 않는다."""
    document = state["document"]
    fields = dict(document.get("fields") or {})
    for key in ("phone", "url"):
        if fields.get(key):
            fields[key] = "(있음)"
    results = state.get("tool_results") or {}
    imp = results.get("impersonation")
    welfare = results.get("welfare")
    available = availability(state)
    return {
        "document": {"docType": document.get("docType"), "docTypeLabel": document.get("docTypeLabel"), "issuer": document.get("issuer"), "fields": fields},
        "situation": state.get("situation") or "",
        "plan": [{"tool": p["tool"], "required": p["required"]} for p in state.get("plan") or []],
        "results": {
            "impersonation": None
            if imp is None
            else {
                "status": imp.get("status"),
                "officialPhoneFound": bool(imp.get("officialPhone")),
                "warnings": imp.get("redFlags") or [],
                "lookupLog": _last_step_detail(state, "impersonation"),
            },
            "deadline": {"organized": results.get("deadline") is not None},
            "welfare": None
            if welfare is None
            else {
                "programs": [i["name"] for i in welfare.get("items", []) if not i.get("fixed")],
                "usedRegion": welfare.get("usedProfile"),
                "usedBackupData": welfare.get("fallbackUsed"),
            },
            "failedTools": state.get("failed_tools") or [],
        },
        "available": {name: ok for name, ok in available.items()},
    }


def validate_actions(actions: list[Any], state: AgentState) -> tuple[list[dict[str, Any]], list[str]]:
    """LLM이 고른 추가 도구를 코드 규칙으로 걸러낸다. (받아들인 것, 버린 이유)"""
    available = availability(state)
    document = state["document"]
    tried_names = {organization_name(document.get("issuer"))}
    welfare = (state.get("tool_results") or {}).get("welfare")
    accepted: list[dict[str, Any]] = []
    dropped: list[str] = []
    for action in actions:
        tool = str(getattr(action, "tool", "") or "").strip()
        if tool not in FOLLOWUP_TOOLS:
            dropped.append(f"목록 밖 도구 {tool or '(빈 값)'}")
            continue
        if not available.get(tool):
            dropped.append(f"{tool} 지금은 필요 없음")
            continue
        if any(a["tool"] == tool for a in accepted):
            continue
        if len(accepted) >= MAX_ACTIONS:
            dropped.append(f"{tool} 최대 {MAX_ACTIONS}개 초과")
            continue
        reason = str(getattr(action, "reason", "") or "").strip()
        if not reason or numeric_issue(reason) or is_assertive(reason):
            reason = DEFAULT_REASONS[tool]
        if tool == "find_official_contact":
            name = re.sub(r"\s+", " ", str(getattr(action, "agency_name", "") or "").strip())
            if not _AGENCY_NAME.fullmatch(name):
                dropped.append("find_official_contact 기관 이름 형식 오류")
                continue
            if organization_name(name) in tried_names:
                dropped.append(f"find_official_contact 이미 찾아본 이름({name})")
                continue
            accepted.append({"tool": tool, "agencyName": name, "reason": reason})
        else:
            keywords = list(dict.fromkeys(k.strip() for k in getattr(action, "keywords", None) or [] if _KEYWORD.fullmatch(k.strip())))[:3]
            if welfare is not None and not keywords:
                dropped.append("search_welfare 같은 검색을 다시 할 이유 없음(검색어 없음)")
                continue
            accepted.append({"tool": tool, "keywords": keywords, "reason": reason})
    return accepted, dropped


def _describe(action: dict[str, Any]) -> str:
    if action["tool"] == "find_official_contact":
        return f"find_official_contact('{action['agencyName']}')"
    return f"search_welfare({', '.join(action['keywords']) or '기본 검색어'})"


async def review(state: AgentState) -> dict[str, Any]:
    step = StepHandle(session_id=state.get("session_id"), id="review", label=LABEL, done_label=DONE_LABEL, node="review")
    step.running()
    try:
        out = await get_llm().structured(
            role="reason",
            node="review",
            system=load_prompt("review"),
            user=json.dumps(review_payload(state), ensure_ascii=False),
            schema=ReviewOut,
        )
    except LLMError as exc:
        final = step.finish("done", f"검토 실패({type(exc).__name__}) → 추가 확인 없이 진행")
        return {"reviewed": True, "followups": [], "steps": [final]}
    accepted, dropped = validate_actions(out.actions, state)
    assessment = out.assessment.strip()
    if not assessment or numeric_issue(assessment) or is_assertive(assessment):
        assessment = "도구 결과를 살펴봤어요"
    detail = [f"판단: {assessment}"]
    detail.append("추가 실행: " + ", ".join(_describe(a) for a in accepted) if accepted else "추가 확인 없음")
    if dropped:
        detail.append("버림: " + "; ".join(dropped))
    final = step.finish("done", " | ".join(detail))
    return {"reviewed": True, "followups": accepted, "steps": [final]}


def route_after_review(state: AgentState) -> str:
    return "run_followups" if state.get("followups") else "compose"


# ── 추가 도구 실행 ──
async def _official_followup(state: AgentState, action: dict[str, Any]) -> ToolOutcome:
    name = action["agencyName"]

    async def work() -> tuple[dict[str, Any], str]:
        outcome = await check_impersonation(state["document"], state.get("raw_excerpt"), lookup_name=name)
        return outcome.result, f"'{name}'(으)로 다시 찾기 | {outcome.detail}"

    return await _with_step(
        state,
        "check_impersonation",
        "다른 이름으로 공식 번호를 다시 찾고 있어요",
        "공식 번호를 다시 찾아봤어요",
        work,
        step_id="impersonation_more",
        node="run_followups",
    )


async def _welfare_followup(state: AgentState, action: dict[str, Any]) -> ToolOutcome:
    async def work() -> tuple[dict[str, Any], str]:
        outcome = await search_welfare(
            state["document"],
            state.get("profile") or {},
            state.get("situation") or "",
            extra_keywords=action["keywords"],
        )
        return outcome.result, f"추가 검색어 {','.join(action['keywords']) or '없음'} | {outcome.detail}"

    return await _with_step(
        state,
        "search_welfare",
        "도움 받을 수 있는 제도를 더 찾고 있어요",
        "도움 받을 수 있는 제도를 더 찾아봤어요",
        work,
        step_id="welfare_more",
        node="run_followups",
    )


async def run_followups(state: AgentState) -> dict[str, Any]:
    actions = state.get("followups") or []
    runners = {"find_official_contact": _official_followup, "search_welfare": _welfare_followup}
    outcomes = await asyncio.gather(*(runners[a["tool"]](state, a) for a in actions))
    results = dict(state.get("tool_results") or {})
    plan = list(state.get("plan") or [])
    steps: list[dict[str, Any]] = []
    for action, outcome in zip(actions, outcomes, strict=True):
        if outcome.step:
            steps.append(outcome.step)
        plan.append({"tool": outcome.tool, "reason": f"결과를 보고 추가: {action['reason']}", "required": False})
        if outcome.result is None:
            continue
        if action["tool"] == "find_official_contact":
            # 다시 찾아서 공식 번호가 나왔을 때만 바꾼다 (못 찾았으면 처음 결과를 그대로 둔다)
            if outcome.result.get("officialPhone"):
                results["impersonation"] = outcome.result
        else:
            merged = merge_welfare(results.get("welfare"), outcome.result)
            if searched_count(merged) >= searched_count(results.get("welfare") or {"items": []}):
                results["welfare"] = merged
    return {"tool_results": results, "plan": plan, "followups": None, "steps": steps}
