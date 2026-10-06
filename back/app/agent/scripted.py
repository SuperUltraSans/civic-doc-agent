"""AGENT_MODE=scripted — 프론트 목업과 같은 시나리오 키의 이벤트를 재생한다 (지시서 7.5절).

LLM 연결 전에도 프론트가 실제 SSE 연동을 시험할 수 있게 하는 개발·시연 대비용 모드다.
**실제 에이전트 동작이 아니다.** 제출물 설명에서 실제 동작과 구분해 적는다.
결과의 할 일·형식은 실제 compose 코드(build_result)로 만들어 계약이 어긋나지 않게 한다.
"""

from __future__ import annotations

import asyncio
import random
from datetime import timedelta
from typing import Any

from app.agent.nodes.ask_user import region_question
from app.agent.nodes.compose import build_result
from app.agent.nodes.extract import build_document
from app.agent.runner import ERRORS
from app.config import get_settings
from app.sessions.manager import Session, get_manager
from app.timeutil import today
from app.tools.deadline import manage_deadline
from app.tools.terms import lookup_term
from app.tools.welfare import MEMBERSHIP_ITEM

SCENARIOS = ("arrears", "blurry", "smishing", "local_tax", "error")


def _due(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def _prev_month() -> str:
    first = today().replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _terms(*names: str) -> list[dict[str, Any]]:
    out = []
    for name in names:
        entry = lookup_term(name)
        if entry:
            out.append({"term": entry.term, "plain": entry.plain, "source": "dictionary"})
    return out


class Player:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.steps: list[dict[str, Any]] = []
        self.fast = get_settings().scripted_speed == "fast"

    async def pause(self) -> None:
        await asyncio.sleep(0.2 if self.fast else random.uniform(0.8, 2.0))

    def step(self, sid: str, label: str, status: str, *, done_label: str | None = None, tool: str | None = None, detail: str | None = None) -> None:
        data: dict[str, Any] = {"id": sid, "label": label, "status": status}
        if done_label:
            data["doneLabel"] = done_label
        if tool:
            data["tool"] = tool
        if detail:
            data["detail"] = detail
        self.steps.append(data)
        self.session.push("step", data)

    async def run_step(self, sid: str, label: str, done_label: str, *, tool: str | None = None, detail: str | None = None) -> None:
        self.step(sid, label, "running", done_label=done_label, tool=tool)
        await self.pause()
        self.step(sid, label, "done", done_label=done_label, tool=tool, detail=detail)

    async def read_and_validate(self, label: str, classify_detail: str) -> None:
        await self.run_step("read_text", "사진에서 글자를 읽고 있어요", "글자를 읽었어요", detail="[scripted] 재생 모드")
        self.step("classify", label, "done", detail=classify_detail)
        await self.run_step("validate", "금액과 날짜를 확인하고 있어요", "금액과 날짜를 다시 확인했어요", detail="[scripted] 형식 검사 통과")

    async def explain_and_plan(self, plan: list[dict[str, Any]], situation: str) -> None:
        self.step("explain", "쉬운 말로 바꾸고 있어요", "running", done_label="쉬운 말로 정리했어요", tool="lookup_terms")
        self.step("plan", "무엇을 확인할지 정하고 있어요", "running", done_label="확인할 일을 정했어요")
        await self.pause()
        self.step("explain", "쉬운 말로 바꾸고 있어요", "done", done_label="쉬운 말로 정리했어요", tool="lookup_terms", detail="[scripted]")
        self.step("plan", "무엇을 확인할지 정하고 있어요", "done", done_label="확인할 일을 정했어요", detail=f"[scripted] 상황: {situation}")
        self.session.push("plan", plan)

    async def review(self) -> None:
        """결과 검토 단계 (실제 동작에서는 계획 모델이 도구 결과를 보고 추가 도구를 고른다)."""
        await self.run_step(
            "review",
            "찾은 결과를 보고 더 확인할 것이 있는지 살피고 있어요",
            "찾은 결과를 보고 더 확인할 것을 정했어요",
            detail="[scripted] 판단: 필요한 확인을 모두 마쳤어요 | 추가 확인 없음",
        )

    def finish(self, document: dict[str, Any], explanation: dict[str, Any], plan: list[dict[str, Any]], tools: dict[str, Any], level2: dict[str, Any]) -> None:
        self.step("compose", "해야 할 일을 정리하고 있어요", "running", done_label="해야 할 일을 정리했어요")
        self.step("compose", "해야 할 일을 정리하고 있어요", "done", done_label="해야 할 일을 정리했어요", detail="[scripted]")
        result = build_result(document=document, explanation=explanation, plan=plan, tool_results=tools, steps=self.steps)
        get_manager().store_result(result["docId"], result["document"], result["explanation"], scripted_level2=level2)
        self.session.finish("result", result)


async def _arrears(p: Player) -> None:
    document = build_document(
        "health_insurance_bill",
        "국민건강보험공단",
        {"amount": 32500, "dueDate": _due(5), "billingMonth": _prev_month(), "arrears": 21000, "phone": "1577-1000"},
    )
    await p.read_and_validate("건강보험료 고지서예요", "docType=health_insurance_bill")
    plan = [
        {"tool": "check_impersonation", "reason": "문서에 연락처가 있어 공식 정보와 비교해요", "required": True},
        {"tool": "manage_deadline", "reason": "문서에 내야 하는 날짜가 있어 기한을 정리해요", "required": True},
        {"tool": "search_welfare", "reason": "밀린 보험료가 있어 나눠 내기나 지원 제도를 찾아봐요", "required": False},
    ]
    await p.explain_and_plan(plan, "밀린 금액이 포함된 건강보험료 고지서예요")
    region = p.session.profile.get("region")
    if not region:
        p.session.ask(region_question())
        answer = await p.session.wait_answer(get_settings().answer_timeout_seconds)
        region = answer if answer and answer != "기타" else None
    await p.run_step("impersonation", "연락처가 공단 번호가 맞는지 확인하고 있어요", "연락처를 공단 공식 번호와 비교했어요", tool="check_impersonation", detail="[scripted] seed table hit: 국민건강보험공단")
    await p.run_step("deadline", "내야 하는 날짜를 확인하고 있어요", "내야 하는 날짜를 확인했어요", tool="manage_deadline")
    await p.run_step("welfare", "도움 받을 수 있는 제도를 찾고 있어요", "도움 받을 수 있는 제도를 찾았어요", tool="search_welfare", detail="[scripted]")
    await p.run_step("evaluate", "찾은 내용이 맞는지 확인하고 있어요", "찾은 내용이 맞는지 한 번 더 확인했어요", detail="[scripted]")
    await p.review()
    welfare_items = [
        {
            "name": "건강보험료 분할납부",
            "summary": "밀린 건강보험료를 한 번에 내기 어려우면 여러 번에 나눠 낼 수 있도록 신청하는 제도예요.",
            "reason": "밀린 보험료가 있어 해당될 수 있어요.",
            "url": "https://www.nhis.or.kr",
        },
        {
            "name": "긴급복지지원",
            "summary": "갑작스러운 위기로 생계가 어려워졌을 때 생계비·의료비 등을 빠르게 지원하는 제도예요.",
            "reason": "생활이 갑자기 어려워졌다면 해당될 수 있어요.",
            "url": "https://www.bokjiro.go.kr",
        },
        dict(MEMBERSHIP_ITEM),
    ]
    tools = {
        "impersonation": {
            "status": "match",
            "checkedValue": "1577-1000",
            "officialPhone": "1577-1000",
            "officialSource": "국민건강보험공단 공식 홈페이지(nhis.or.kr)",
            "redFlags": [],
        },
        "deadline": manage_deadline(document),
        "welfare": {"items": welfare_items, "usedProfile": region is not None, "fallbackUsed": False},
    }
    explanation = {
        "level": 1,
        "summaryTemplate": "{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내라는 안내예요.",
        "consequences": ["기한이 지나면 돈이 더 붙을 수 있어요.", "밀린 돈은 나눠 낼 수 있는지 물어볼 수 있어요."],
        "terms": _terms("납기 내 금액", "체납액") + [{"term": "고지 대상 월", "plain": "어느 달 몫의 보험료인지", "source": "llm"}],
    }
    level2 = {
        "level": 2,
        "summaryTemplate": "{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내세요.",
        "consequences": ["늦으면 돈이 더 붙어요.", "밀린 돈은 나눠 낼 수 있어요. 물어보세요."],
        "terms": _terms("납기 내 금액", "체납액", "분할납부"),
    }
    p.finish(document, explanation, plan, tools, level2)


async def _smishing(p: Player) -> None:
    document = build_document(
        "suspicious_message",
        "국민건강보험공단",
        {"amount": 38200, "phone": "010-1234-5678", "url": "http://bit.ly/nhis-refund-example"},
    )
    await p.read_and_validate("사칭 의심 문자예요", "docType=suspicious_message")
    plan = [{"tool": "check_impersonation", "reason": "문서에 연락처가 있어 공식 정보와 비교해요", "required": True}]
    await p.explain_and_plan(plan, "공단을 사칭한 것으로 의심되는 환급 문자예요")
    await p.run_step("impersonation", "연락처가 공단 번호가 맞는지 확인하고 있어요", "연락처를 공단 공식 번호와 비교했어요", tool="check_impersonation", detail="[scripted] 근거: rule:mobile, rule:shortener, kisa-002")
    await p.run_step("evaluate", "찾은 내용이 맞는지 확인하고 있어요", "찾은 내용이 맞는지 한 번 더 확인했어요", detail="[scripted]")
    await p.review()
    tools = {
        "impersonation": {
            "status": "mismatch",
            "checkedValue": "010-1234-5678 / http://bit.ly/nhis-refund-example",
            "officialPhone": "1577-1000",
            "officialSource": "국민건강보험공단 공식 홈페이지(nhis.or.kr)",
            "redFlags": [
                "기관이라면서 휴대전화 번호로 연락하라고 해요",
                "적힌 번호가 공식 번호와 달라요",
                "짧게 줄인 인터넷 주소가 있어요",
                "돈을 돌려준다며 인터넷 주소를 누르게 해요",
            ],
        }
    }
    explanation = {
        "level": 1,
        "summaryTemplate": "{issuer}에서 보냈다고 하는 문자예요.",
        "consequences": ["문자 속 주소를 누르면 돈이나 개인정보를 잃을 수 있어요."],
        "terms": _terms("환급금", "단축 주소", "스미싱"),
    }
    level2 = {"level": 2, "summaryTemplate": "{issuer}라고 적힌 문자예요.", "consequences": ["주소를 누르지 마세요."], "terms": _terms("단축 주소", "스미싱")}
    p.finish(document, explanation, plan, tools, level2)


async def _local_tax(p: Player) -> None:
    document = build_document("local_tax_bill", "김해시", {"amount": 86400, "dueDate": _due(12)})
    await p.read_and_validate("지방세 고지서예요", "docType=local_tax_bill")
    plan = [{"tool": "manage_deadline", "reason": "문서에 내야 하는 날짜가 있어 기한을 정리해요", "required": True}]
    await p.explain_and_plan(plan, "체납 없는 지방세 고지서예요")
    await p.run_step("deadline", "내야 하는 날짜를 확인하고 있어요", "내야 하는 날짜를 확인했어요", tool="manage_deadline")
    await p.run_step("evaluate", "찾은 내용이 맞는지 확인하고 있어요", "찾은 내용이 맞는지 한 번 더 확인했어요", detail="[scripted]")
    await p.review()
    tools = {"deadline": manage_deadline(document)}
    explanation = {
        "level": 1,
        "summaryTemplate": "{issuer}에서 보낸 지방세 {amount}을 {dueDate}까지 내라는 안내예요.",
        "consequences": ["기한이 지나면 돈이 더 붙을 수 있어요."],
        "terms": _terms("납기 내 금액", "재산세", "전자납부번호"),
    }
    level2 = {"level": 2, "summaryTemplate": "지방세 {amount}을 {dueDate}까지 내세요.", "consequences": ["늦으면 돈이 더 붙어요."], "terms": _terms("납기 내 금액", "재산세")}
    p.finish(document, explanation, plan, tools, level2)


async def _blurry(p: Player) -> None:
    await p.run_step("read_text", "사진에서 글자를 읽고 있어요", "글자를 읽었어요", detail="[scripted] legible=false")
    p.step("validate", "금액과 날짜를 확인하고 있어요", "failed", done_label="금액과 날짜를 다시 확인했어요", detail="[scripted] legible=false → 다시 찍기 안내")
    p.session.finish(
        "need_retake",
        {"message": "글씨가 잘 안 보여요", "tips": ["밝은 곳에서 찍어 주세요", "종이를 평평하게 펴 주세요", "종이 전체가 보이게 찍어 주세요"]},
    )


async def _error(p: Player) -> None:
    p.step("read_text", "사진에서 글자를 읽고 있어요", "running", done_label="글자를 읽었어요")
    await p.pause()
    p.step("read_text", "사진에서 글자를 읽고 있어요", "failed", done_label="글자를 읽었어요", detail="[scripted] 연결 끊김")
    p.session.finish("error", ERRORS["network"])


PLAYERS = {"arrears": _arrears, "blurry": _blurry, "smishing": _smishing, "local_tax": _local_tax, "error": _error}


async def run_scripted(session: Session) -> None:
    session.take_image()  # 재생 모드는 이미지를 보지 않는다 (바로 버림)
    scenario = session.scenario if session.scenario in PLAYERS else "arrears"
    await PLAYERS[scenario](Player(session))
