"""evaluate — 결과 점검, 필요 시 1회 재실행 · Feedback (지시서 5.9절).

| 점검                                   | 문제 시 처리                     |
| 필수 도구가 모두 실행되었는가          | 실패한 필수 도구를 1회 재시도    |
| 복지 결과가 비었는가                   | 지역 조건을 빼고 1회 재검색      |
| 지역 한정 제도가 사용자 지역과 다른가  | 해당 항목 제거                   |
| 사칭 mismatch 인데 근거가 비었는가     | unknown 으로 낮춤                |
"""

from __future__ import annotations

from typing import Any

from app.agent.events import StepHandle
from app.agent.state import AgentState
from app.tools.welfare import effective_region, region_sido_map, searched_count

MAX_EVAL_ATTEMPTS = 1
LABEL = "찾은 내용이 맞는지 확인하고 있어요"
DONE_LABEL = "찾은 내용이 맞는지 한 번 더 확인했어요"
RESULT_KEYS = {"check_impersonation": "impersonation", "manage_deadline": "deadline", "search_welfare": "welfare"}


def filter_region_items(welfare: dict[str, Any], region: str | None) -> tuple[dict[str, Any], int]:
    """사용자 지역과 다른 지역 한정 제도를 뺀다. 지역을 모르면 지역 한정 제도는 모두 뺀다."""
    sido = region_sido_map().get(region or "")
    kept, removed = [], 0
    for item in welfare.get("items", []):
        item_region = item.get("region") or ""
        if item_region and item_region not in (region, sido):
            removed += 1
            continue
        kept.append(item)
    return {**welfare, "items": kept}, removed


def plan_retry(state: AgentState) -> tuple[list[str], bool, list[str]]:
    """다시 실행할 도구, 복지 지역 조건 제외 여부, 점검 메모."""
    plan = state.get("plan") or []
    results = state.get("tool_results") or {}
    planned = {p["tool"] for p in plan}
    notes: list[str] = []
    retry: list[str] = []
    ignore_region = False

    failed_required = [p["tool"] for p in plan if p["required"] and RESULT_KEYS[p["tool"]] not in results]
    if failed_required:
        retry += failed_required
        notes.append(f"필수 도구 실패 {','.join(failed_required)} → 1회 재시도")

    welfare = results.get("welfare")
    if "search_welfare" in planned and welfare is not None and searched_count(welfare) == 0:
        if welfare.get("usedProfile"):
            retry.append("search_welfare")
            ignore_region = True
            notes.append("복지 결과 0건 → 지역 조건 제외 재검색")
        else:
            notes.append("복지 결과 0건 (지역 조건 없음, 재검색 생략)")
    elif "search_welfare" in planned and welfare is None and "search_welfare" not in retry:
        retry.append("search_welfare")
        notes.append("복지 검색 실패 → 1회 재시도")
    return retry, ignore_region, notes


async def evaluate(state: AgentState) -> dict[str, Any]:
    attempts = state.get("eval_attempts", 0)
    notes = list(state.get("eval_notes") or [])
    step = StepHandle(session_id=state.get("session_id"), id="evaluate", label=LABEL, done_label=DONE_LABEL, node="evaluate")
    if attempts == 0:
        step.running()
    else:
        welfare = (state.get("tool_results") or {}).get("welfare")
        if welfare is not None and state.get("welfare_ignore_region"):
            notes.append(f"재검색 결과 {searched_count(welfare)}건")

    retry, ignore_region, retry_notes = plan_retry(state) if attempts < MAX_EVAL_ATTEMPTS else ([], False, [])
    if retry:
        notes += retry_notes
        return {"pending_tools": retry, "welfare_ignore_region": ignore_region, "eval_attempts": attempts + 1, "eval_notes": notes}
    if attempts >= MAX_EVAL_ATTEMPTS:
        still_failed = [p["tool"] for p in state.get("plan") or [] if p["required"] and RESULT_KEYS[p["tool"]] not in (state.get("tool_results") or {})]
        if still_failed:
            notes.append(f"재시도 후에도 실패: {','.join(still_failed)}")
    else:
        notes += retry_notes

    results = dict(state.get("tool_results") or {})
    welfare = results.get("welfare")
    if welfare is not None:
        region = None if state.get("welfare_ignore_region") else effective_region(state.get("profile") or {})
        filtered, removed = filter_region_items(welfare, region)
        if removed:
            notes.append(f"다른 지역 한정 제도 {removed}건 제거")
        if state.get("welfare_ignore_region"):
            filtered["usedProfile"] = False
        results["welfare"] = filtered

    imp = results.get("impersonation")
    if imp is not None and imp.get("status") == "mismatch" and not imp.get("redFlags"):
        results["impersonation"] = {**imp, "status": "unknown"}
        notes.append("사칭 mismatch 근거 없음 → unknown 으로 낮춤")

    if not notes:
        notes.append("필수 도구 실행·결과 점검 이상 없음")
    final = step.finish("done", " | ".join(notes))
    return {"tool_results": results, "pending_tools": None, "eval_notes": notes, "steps": [final]}


def route_after_evaluate(state: AgentState) -> str:
    """코드 점검의 재실행 → (처음 한 번) 결과 검토 → 결과 조립."""
    if state.get("pending_tools"):
        return "run_tools"
    if not state.get("reviewed"):
        return "review"
    return "compose"
