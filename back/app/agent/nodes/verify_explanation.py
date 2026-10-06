"""verify_explanation — 설명 안 숫자·자리표시자 검사 · Feedback (지시서 5.4절).

- 허용 목록 밖의 자리표시자 → 위반
- 값이 null인 필드의 자리표시자 → 위반
- 자리표시자 밖의 3자리 이상 숫자, 날짜·금액 형태(10월 6일, 2026-10, 3만 원 등) → 위반
- 단정 표현("안전합니다" 등) → 위반
위반 시 위반 내용을 알려 주며 1회 재생성. 다시 위반하면 문서 종류별 기본 문구로 대체한다.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.events import StepHandle
from app.agent.state import AgentState
from app.schemas.document import BILL_TYPES, PAYMENT_NAMES
from app.schemas.explanation import Explanation
from app.textutil import ieyo, is_assertive, numeric_issue
from app.tools.terms import candidate_terms

ALLOWED_PLACEHOLDERS = ("amount", "arrears", "dueDate", "billingMonth", "issuer")
MAX_EXPLAIN_ATTEMPTS = 2
LABEL = "쉬운 말로 바꾸고 있어요"
DONE_LABEL = "쉬운 말로 정리했어요"

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def available_placeholders(document: dict[str, Any]) -> list[str]:
    fields = document.get("fields") or {}
    out = [name for name in ("amount", "arrears", "dueDate", "billingMonth") if fields.get(name) is not None]
    if (document.get("issuer") or "").strip():
        out.append("issuer")
    return out


def _check_text(where: str, text: str, available: list[str]) -> list[str]:
    violations: list[str] = []
    for m in _PLACEHOLDER.finditer(text):
        name = m.group(1)
        if name not in ALLOWED_PLACEHOLDERS:
            violations.append(f"{where}: 허용되지 않은 자리표시자 {{{name}}}")
        elif name not in available:
            violations.append(f"{where}: 값이 없는 필드의 자리표시자 {{{name}}}")
    outside = _PLACEHOLDER.sub(" ", text)
    if "{" in outside or "}" in outside:
        violations.append(f"{where}: 닫히지 않은 중괄호")
    why = numeric_issue(outside)
    if why:
        violations.append(f"{where}: 자리표시자 밖 {why}")
    if is_assertive(text):
        violations.append(f"{where}: 단정 표현")
    if re.search(r"<[^<>]+>", text):
        violations.append(f"{where}: HTML 태그")  # 응답은 문자열만, 프론트는 텍스트로만 렌더링
    return violations


def find_violations(explanation: dict[str, Any], document: dict[str, Any], base: dict[str, Any] | None = None) -> list[str]:
    available = available_placeholders(document)
    summary = (explanation.get("summaryTemplate") or "").strip()
    violations: list[str] = []
    if not summary:
        violations.append("summaryTemplate: 비어 있음")
    violations += _check_text("summaryTemplate", summary, available)
    for i, c in enumerate(explanation.get("consequences") or []):
        violations += _check_text(f"consequences[{i}]", c, available)
    for i, t in enumerate(explanation.get("terms") or []):
        if t.get("source") == "llm":
            violations += _check_text(f"terms[{i}].plain", t.get("plain", ""), available)
    if base is not None:
        # level 2: 내용과 자리표시자는 바꾸지 않는다
        before = set(_PLACEHOLDER.findall(base.get("summaryTemplate") or ""))
        after = set(_PLACEHOLDER.findall(summary))
        if before != after:
            violations.append("summaryTemplate: 기본 설명과 자리표시자가 다름")
    return violations


def default_explanation(document: dict[str, Any], level: int = 1, excerpt: str | None = None) -> dict[str, Any]:
    """문서 종류별 기본 문구. 숫자는 자리표시자로만."""
    doc_type = document.get("docType", "unknown")
    fields = document.get("fields") or {}
    label = document.get("docTypeLabel") or "문서"
    has = set(available_placeholders(document))
    by = "{issuer}에서 " if "issuer" in has else ""
    consequences: list[str] = []

    if doc_type in BILL_TYPES:
        pay = PAYMENT_NAMES[doc_type]
        month = "{billingMonth}분 " if "billingMonth" in has else ""
        if {"amount", "dueDate"} <= has:
            summary = f"{pay} {{amount}}을 {{dueDate}}까지 내야 해요." if level == 2 else f"{by}{month}{pay} {{amount}}을 {{dueDate}}까지 내라는 안내예요."
        elif "amount" in has:
            summary = f"{by}{month}{pay} {{amount}}을 내라는 안내예요."
        else:
            summary = f"{by}보낸 {ieyo(label)}."
        if "dueDate" in has:
            consequences.append("기한이 지나면 돈이 더 붙을 수 있어요." if level == 1 else "늦으면 돈이 더 붙을 수 있어요.")
        if fields.get("arrears"):
            consequences.append("밀린 돈을 계속 안 내면 독촉을 받을 수 있어요." if level == 1 else "밀린 돈이 있어요.")
    elif doc_type == "suspicious_message":
        summary = "{issuer}에서 보냈다고 하는 문자예요." if "issuer" in has else "기관에서 보낸 것처럼 보이는 문자예요."
        consequences.append(
            "문자 속 주소를 누르거나 적힌 번호로 연락하면 돈이나 개인정보를 잃을 수 있어요." if level == 1 else "주소를 누르지 마세요."
        )
    elif doc_type == "basic_pension_notice":
        summary = f"{by}보낸 기초연금 안내문이에요." if level == 1 else "기초연금에 대한 안내예요."
        if "dueDate" in has:
            summary += " {dueDate}까지 확인이 필요해요."
    else:
        summary = f"{by}보낸 {ieyo(label)}."

    terms = [
        {"term": e.term, "plain": e.plain, "source": "dictionary"}
        for e in candidate_terms(doc_type, fields, excerpt, limit=3 if level == 1 else 2)
    ]
    return Explanation.model_validate(
        {"level": level, "summaryTemplate": summary, "consequences": consequences, "terms": terms}
    ).to_api()


async def verify_explanation(state: AgentState) -> dict[str, Any]:
    document = state["document"]
    explanation = state["explanation"]
    attempts = state.get("explain_attempts", 1)
    notes = list(state.get("explain_notes") or [])
    violations = find_violations(explanation, document)

    if violations and attempts < MAX_EXPLAIN_ATTEMPTS:
        notes.append(f"검사 위반 {len(violations)}건({violations[0]}) → 1회 재생성")
        return {"explain_violations": violations, "explain_notes": notes}

    if violations:
        explanation = default_explanation(document, 1, state.get("raw_excerpt"))
        notes.append(f"재생성 후에도 위반({violations[0]}) → 기본 문구로 대체")
    else:
        notes.append("자리표시자·숫자 검사 통과")
    step = StepHandle(
        session_id=state.get("session_id"), id="explain", label=LABEL, done_label=DONE_LABEL, tool="lookup_terms", node="verify_explanation"
    )
    final = step.finish("done", " | ".join(notes))
    return {"explanation": explanation, "explain_violations": None, "explain_notes": notes, "steps": [final]}


def route_after_verify(state: AgentState) -> str:
    return "explain" if state.get("explain_violations") else "compose"
