"""run_tools — 계획된 도구 병렬 실행 · Tool Use (지시서 5.7절).

asyncio.gather 로 병렬 실행한다. 도구마다 시간 제한을 두고, 실패해도 다른 도구는 계속 진행한다.
각 도구는 시작·종료 시 step 이벤트를 보낸다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.agent.events import step_scope
from app.agent.state import AgentState
from app.tools.deadline import manage_deadline
from app.tools.impersonation import check_impersonation, who_label
from app.tools.welfare import search_welfare

TOOL_TIMEOUTS = {"check_impersonation": 30.0, "manage_deadline": 5.0, "search_welfare": 30.0}
STEP_IDS = {"check_impersonation": "impersonation", "manage_deadline": "deadline", "search_welfare": "welfare"}
RESULT_KEYS = {"check_impersonation": "impersonation", "manage_deadline": "deadline", "search_welfare": "welfare"}


@dataclass
class ToolOutcome:
    tool: str
    result: dict[str, Any] | None
    step: dict[str, Any]


async def _with_step(
    state: AgentState,
    tool: str,
    label: str,
    done_label: str,
    work: Callable[[], Awaitable[tuple[dict[str, Any], str]]],
) -> ToolOutcome:
    """도구 하나 실행. 시간 초과·예외는 failed 단계로 남기고 결과 없이 돌려준다 (다른 도구는 계속)."""
    handle = None
    try:
        async with step_scope(state, STEP_IDS[tool], label, done_label, tool=tool, node="run_tools") as handle:
            result, detail = await asyncio.wait_for(work(), timeout=TOOL_TIMEOUTS[tool])
            handle.detail = detail
        return ToolOutcome(tool, result, handle.final or {})
    except asyncio.CancelledError:
        raise
    except Exception:
        return ToolOutcome(tool, None, (handle.final if handle else None) or {})


async def _run_impersonation(state: AgentState) -> ToolOutcome:
    who = who_label(state["document"].get("issuer"))

    async def work() -> tuple[dict[str, Any], str]:
        outcome = await check_impersonation(state["document"], state.get("raw_excerpt"))
        return outcome.result, outcome.detail

    return await _with_step(
        state, "check_impersonation", f"연락처가 {who} 번호가 맞는지 확인하고 있어요", f"연락처를 {who} 공식 번호와 비교했어요", work
    )


async def _run_deadline(state: AgentState) -> ToolOutcome:
    async def work() -> tuple[dict[str, Any], str]:
        result = manage_deadline(state["document"])
        return result, f"기한 {result['dueDate']}, 달력 제목 '{result['calendarTitle']}'"

    return await _with_step(state, "manage_deadline", "내야 하는 날짜를 확인하고 있어요", "내야 하는 날짜를 확인했어요", work)


async def _run_welfare(state: AgentState) -> ToolOutcome:
    async def work() -> tuple[dict[str, Any], str]:
        outcome = await search_welfare(
            state["document"],
            state.get("profile") or {},
            state.get("situation") or "",
            ignore_region=bool(state.get("welfare_ignore_region")),
        )
        return outcome.result, outcome.detail

    return await _with_step(state, "search_welfare", "도움 받을 수 있는 제도를 찾고 있어요", "도움 받을 수 있는 제도를 찾았어요", work)


RUNNERS: dict[str, Callable[[AgentState], Awaitable[ToolOutcome]]] = {
    "check_impersonation": _run_impersonation,
    "manage_deadline": _run_deadline,
    "search_welfare": _run_welfare,
}


async def run_tools(state: AgentState) -> dict[str, Any]:
    pending = state.get("pending_tools")
    tools = [t for t in (pending or [p["tool"] for p in state.get("plan") or []]) if t in RUNNERS]
    outcomes = await asyncio.gather(*(RUNNERS[t](state) for t in tools))
    results = dict(state.get("tool_results") or {})
    failed: list[str] = []
    steps: list[dict[str, Any]] = []
    for o in outcomes:
        if o.result is None:
            failed.append(o.tool)
        else:
            results[RESULT_KEYS[o.tool]] = o.result
        if o.step:
            steps.append(o.step)
    return {"tool_results": results, "failed_tools": failed, "pending_tools": None, "steps": steps}
