"""LangGraph 그래프 조립 (지시서 4.1절).

preprocess ──(사진 품질 명백히 나쁨)──▶ END(need_retake)
    └▶ extract → validate ──(누락·판독 불가)──▶ END(need_retake)
                ▲          │
                └(1회 재추출)┤
                           ├─▶ explain ─▶ verify_explanation ──(위반 시 1회 재생성)──▶ explain
                           │                       └─▶ compose(대기)
                           └─▶ plan ──(정보 부족)──▶ ask_user(interrupt) ─▶ run_tools
                                  └────────────────────────────────────▶ run_tools(병렬)
                                                                          ▼
                                                     evaluate ──(1회 재실행)──▶ run_tools
                                                         └─▶ review(LLM이 도구 결과 검토, 1회)
                                                               ├─(추가 도구)─▶ run_followups ─▶ evaluate
                                                               └─▶ compose ─▶ END(result)

explain 과 plan 은 둘 다 검증된 추출 결과만 쓰므로 병렬 분기로 동시에 실행한다 (지시서 7.4절).
compose 는 defer 노드라서 두 갈래가 모두 끝난 뒤 한 번만 실행된다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.ask_user import ask_user
from app.agent.nodes.compose import compose
from app.agent.nodes.evaluate import evaluate, route_after_evaluate
from app.agent.nodes.explain import explain
from app.agent.nodes.extract import extract
from app.agent.nodes.plan import plan, route_after_plan
from app.agent.nodes.preprocess import preprocess, route_after_preprocess
from app.agent.nodes.review import review, route_after_review, run_followups
from app.agent.nodes.run_tools import run_tools
from app.agent.nodes.validate import route_after_validate, validate
from app.agent.nodes.verify_explanation import route_after_verify, verify_explanation
from app.agent.state import AgentState

checkpointer = InMemorySaver()  # 사용자 응답 대기(interrupt)용. 메모리 방식, 세션 종료 시 스레드 삭제


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("preprocess", preprocess)
    g.add_node("extract", extract)
    g.add_node("validate", validate)
    g.add_node("explain", explain)
    g.add_node("verify_explanation", verify_explanation)
    g.add_node("plan", plan)
    g.add_node("ask_user", ask_user)
    g.add_node("run_tools", run_tools)
    g.add_node("evaluate", evaluate)
    g.add_node("review", review)
    g.add_node("run_followups", run_followups)
    g.add_node("compose", compose, defer=True)

    g.add_edge(START, "preprocess")
    g.add_conditional_edges("preprocess", route_after_preprocess, ["extract", END])  # 사진 품질이 명백히 나쁘면 바로 다시 찍기
    g.add_edge("extract", "validate")
    g.add_conditional_edges("validate", route_after_validate, ["extract", "explain", "plan", END])
    g.add_edge("explain", "verify_explanation")
    g.add_conditional_edges("verify_explanation", route_after_verify, ["explain", "compose"])
    g.add_conditional_edges("plan", route_after_plan, ["ask_user", "run_tools"])
    g.add_edge("ask_user", "run_tools")
    g.add_edge("run_tools", "evaluate")
    g.add_conditional_edges("evaluate", route_after_evaluate, ["run_tools", "review", "compose"])
    g.add_conditional_edges("review", route_after_review, ["run_followups", "compose"])
    g.add_edge("run_followups", "evaluate")
    g.add_edge("compose", END)
    return g


@lru_cache
def get_graph() -> Any:
    return build_graph().compile(checkpointer=checkpointer)
