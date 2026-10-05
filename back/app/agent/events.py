"""단계 이벤트 발행 도우미.

노드는 `step_scope` 로 단계를 연다. 들어갈 때 running, 나올 때 done(또는 failed/skipped)을
세션 버퍼로 보내고, 최종 단계 기록(dict)을 상태의 steps 에 넣을 수 있게 돌려준다.
같은 id의 단계는 running → done 순서로 다시 보낸다 (지시서 3.2절).
서버 로그에는 단계별 소요 시간·토큰을 JSON 한 줄로 남긴다 (지시서 10장).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import Usage, current_usage
from app.logging_setup import log_event
from app.schemas.agent import AgentStep


def _session(session_id: str | None):
    if not session_id:
        return None
    from app.sessions.manager import get_manager

    return get_manager().sessions.get(session_id)


def push_event(session_id: str | None, name: str, data: Any) -> None:
    session = _session(session_id)
    if session is not None:
        session.push(name, data)


def emit_step(session_id: str | None, step: dict[str, Any]) -> dict[str, Any]:
    """AgentStep 모양을 검증해 보내고, 보낸 dict를 돌려준다."""
    data = AgentStep.model_validate(step).to_api()
    push_event(session_id, "step", data)
    return data


@dataclass
class StepHandle:
    session_id: str | None
    id: str
    label: str
    done_label: str | None = None
    tool: str | None = None
    node: str | None = None
    status: str = "done"
    detail: str | None = None
    final: dict[str, Any] | None = None
    usage: Usage = field(default_factory=Usage)
    started: float = field(default_factory=time.perf_counter)

    def base(self) -> dict[str, Any]:
        step: dict[str, Any] = {"id": self.id, "label": self.label}
        if self.done_label:
            step["doneLabel"] = self.done_label
        if self.tool:
            step["tool"] = self.tool
        return step

    def running(self, detail: str | None = None) -> dict[str, Any]:
        return emit_step(self.session_id, {**self.base(), "status": "running", **({"detail": detail} if detail else {})})

    def finish(self, status: str | None = None, detail: str | None = None) -> dict[str, Any]:
        if status:
            self.status = status
        if detail is not None:
            self.detail = detail
        step = {**self.base(), "status": self.status}
        if self.detail:
            step["detail"] = self.detail
        self.final = emit_step(self.session_id, step)
        log_event(
            "step",
            sessionId=self.session_id,
            node=self.node or self.id,
            stepId=self.id,
            status=self.status,
            durationMs=round((time.perf_counter() - self.started) * 1000),
            tokensIn=self.usage.tokens_in,
            tokensOut=self.usage.tokens_out,
            detail=self.detail,
        )
        return self.final


@asynccontextmanager
async def step_scope(
    state: dict[str, Any],
    step_id: str,
    label: str,
    done_label: str | None = None,
    *,
    tool: str | None = None,
    node: str | None = None,
    emit_running: bool = True,
) -> AsyncIterator[StepHandle]:
    """단계 하나를 연다. 예외가 나면 failed로 닫고 예외를 다시 던진다."""
    handle = StepHandle(
        session_id=state.get("session_id"),
        id=step_id,
        label=label,
        done_label=done_label,
        tool=tool,
        node=node,
    )
    token = current_usage.set(handle.usage)
    if emit_running:
        handle.running()
    try:
        yield handle
    except BaseException as exc:
        if handle.final is None:
            why = "시간 초과" if isinstance(exc, TimeoutError) else f"오류: {type(exc).__name__}"
            handle.finish("failed", f"{handle.detail} | {why}" if handle.detail else why)
        raise
    else:
        if handle.final is None:
            handle.finish()
    finally:
        current_usage.reset(token)
