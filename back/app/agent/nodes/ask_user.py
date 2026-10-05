"""ask_user — 부족한 정보 질문 · Reasoning, Memory (지시서 5.6절).

LangGraph interrupt로 그래프를 멈추고, /answer 가 오면 같은 thread_id(=sessionId)로 재개한다.
재개 시 이 노드는 처음부터 다시 실행되므로 interrupt 전에는 부작용이 없어야 한다
(need_info 이벤트는 실행기가 interrupt 값을 보고 보낸다).

- 질문은 세션당 최대 1회. 나이대는 묻지 않는다.
- 선택지는 설정 파일(data/regions.json)로 관리, 7개 이하.
- "기타" 또는 null(건너뛰기)이면 지역 조건 없이 찾고 usedProfile=false.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from langgraph.types import interrupt

from app.agent.state import AgentState
from app.config import get_settings
from app.schemas.agent import InfoQuestion

MAX_OPTIONS = 7
# LangGraph는 Command(resume=None)을 "재개 값 없음"으로 보므로 건너뛰기는 이 값으로 재개한다
SKIP = "__skip__"


@lru_cache
def region_question() -> dict[str, Any]:
    raw = json.loads((get_settings().data_dir / "regions.json").read_text(encoding="utf-8"))
    options = [{"label": o["label"], "value": o["value"]} for o in raw["options"]][:MAX_OPTIONS]
    return InfoQuestion.model_validate({"field": "region", "question": raw["question"], "options": options}).to_api()


def normalize_answer(value: Any) -> str | None:
    if not isinstance(value, str) or value == SKIP:
        return None
    text = value.strip()[:20]
    return text or None


async def ask_user(state: AgentState) -> dict[str, Any]:
    answer = normalize_answer(interrupt(region_question()))
    profile = dict(state.get("profile") or {})
    profile["region"] = answer if answer and answer != "기타" else None
    return {"profile": profile, "asked": True}
