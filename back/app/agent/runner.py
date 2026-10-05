"""세션 실행기 — 그래프를 돌리고 종료 이벤트(need_retake / result / error)를 보낸다.

- need_info: interrupt 값을 받아 이벤트로 보내고, /answer 가 오거나 3분이 지나면(null=건너뛰기) 재개한다.
- 실패해도 결과를 낸다: 노드 안의 외부 실패는 대체 경로로 처리되고, 여기까지 올라온 예외만 error 이벤트가 된다.
- 개인정보: 이미지는 세션에서 꺼내는 즉시 세션에서 지우고, 끝나면 체크포인트 스레드를 삭제한다.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.types import Command

from app.agent.graph import checkpointer, get_graph
from app.agent.nodes.ask_user import SKIP
from app.agent.nodes.preprocess import UnsupportedImage
from app.config import get_settings
from app.llm.client import LLMConfigError, LLMNetworkError, LLMTimeout, current_scenario, current_session_id
from app.logging_setup import log_event
from app.sessions.manager import Session, get_manager

ERRORS = {
    "timeout": {"code": "timeout", "message": "확인이 오래 걸리고 있어요. 다시 해 볼까요?"},
    "network": {"code": "network", "message": "연결이 잠시 끊겼어요"},
    "server": {"code": "server", "message": "문제가 생겼어요. 다시 해 볼까요?"},
    "unsupported_image": {"code": "unsupported_image", "message": "이 사진은 열 수 없어요. 카메라로 다시 찍어 주세요"},
}


async def run_live(session: Session) -> None:
    graph = get_graph()
    config: dict[str, Any] = {"configurable": {"thread_id": session.id}, "recursion_limit": 40}
    scenario_token = current_scenario.set(session.scenario or "arrears")
    session_token = current_session_id.set(session.id)
    started = time.perf_counter()
    try:
        inputs: Any = {
            "session_id": session.id,
            "scenario": session.scenario,
            "image_bytes": session.take_image(),
            "profile": dict(session.profile),
            "steps": [],
        }
        asked = False
        while True:
            # durability="exit": 체크포인트를 그래프가 멈추거나 끝날 때만 저장 → 이미지가 담긴 중간 상태를 남기지 않는다
            out = await graph.ainvoke(inputs, config, durability="exit")
            interrupts = out.get("__interrupt__") if isinstance(out, dict) else None
            if not interrupts:
                break
            if asked:  # 질문은 세션당 최대 1회 — 혹시 다시 멈추면 건너뛰기로 진행
                inputs = Command(resume=SKIP)
                continue
            asked = True
            session.ask(interrupts[0].value)
            answer = await session.wait_answer(get_settings().answer_timeout_seconds)
            log_event("answer received", sessionId=session.id, node="ask_user", status="skipped" if answer is None else "answered")
            inputs = Command(resume=answer if answer is not None else SKIP)

        if out.get("retake"):
            session.finish("need_retake", out["retake"])
        elif out.get("result"):
            result = out["result"]
            get_manager().store_result(result["docId"], result["document"], result["explanation"])
            session.finish("result", result)
        else:
            session.finish("error", ERRORS["server"])
        log_event("session done", sessionId=session.id, node="graph", status=session.events[-1].name, durationMs=round((time.perf_counter() - started) * 1000))
    except LLMTimeout:
        session.finish("error", ERRORS["timeout"])
        log_event("session error", level=40, sessionId=session.id, status="timeout")
    except LLMNetworkError:
        session.finish("error", ERRORS["network"])
        log_event("session error", level=40, sessionId=session.id, status="network")
    except UnsupportedImage:
        session.finish("error", ERRORS["unsupported_image"])
    except LLMConfigError:
        session.finish("error", ERRORS["server"])
        log_event("LLM 설정 오류 (모델 ID·권한·리전 확인)", level=40, sessionId=session.id, status="config", exc_info=True)
    except Exception:
        session.finish("error", ERRORS["server"])
        log_event("session error", level=40, sessionId=session.id, status="server", exc_info=True)
    finally:
        checkpointer.delete_thread(session.id)
        current_scenario.reset(scenario_token)
        current_session_id.reset(session_token)
