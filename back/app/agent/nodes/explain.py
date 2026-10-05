"""explain — 쉬운 말 설명 생성 · Goal (지시서 5.4절).

입력은 검증된 ExtractedDocument JSON뿐이다. 이미지를 다시 넣지 않는다.
숫자·날짜는 자리표시자로만 쓰게 하고, 실제 값은 프론트가 채운다.
용어는 먼저 lookup_terms(사전)로 찾고, 사전에 없는 용어만 LLM이 풀이한다(source: llm).
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.events import StepHandle
from app.agent.nodes.verify_explanation import (
    DONE_LABEL,
    LABEL,
    MAX_EXPLAIN_ATTEMPTS,
    available_placeholders,
    default_explanation,
    find_violations,
)
from app.agent.state import AgentState
from app.llm.client import LLMError, get_llm, load_prompt
from app.llm.schemas import ExplainOut
from app.schemas.explanation import Explanation
from app.tools.terms import candidate_terms, lookup_term

MAX_TERMS = 3


def _document_for_llm(document: dict[str, Any]) -> dict[str, Any]:
    """연락처·주소 값은 설명에 필요 없으므로 '있음'으로만 알린다."""
    fields = dict(document.get("fields") or {})
    for key in ("phone", "url"):
        if fields.get(key):
            fields[key] = "(있음)"
    return {"docType": document.get("docType"), "docTypeLabel": document.get("docTypeLabel"), "issuer": document.get("issuer"), "fields": fields}


def resolve_terms(llm_terms: list[Any]) -> tuple[list[dict[str, Any]], int]:
    """LLM이 고른 용어를 사전으로 다시 확인: 사전에 있으면 사전 풀이(dictionary), 없으면 llm."""
    out: list[dict[str, Any]] = []
    hits = 0
    for t in llm_terms:
        term = (t.term if hasattr(t, "term") else t.get("term", "")).strip()
        plain = (t.plain if hasattr(t, "plain") else t.get("plain", "")).strip()
        if not term:
            continue
        entry = lookup_term(term)
        item = (
            {"term": entry.term, "plain": entry.plain, "source": "dictionary"}
            if entry
            else {"term": term, "plain": plain, "source": "llm"}
        )
        if entry:
            hits += 1
        if item["plain"] and all(x["term"] != item["term"] for x in out):
            out.append(item)
        if len(out) >= MAX_TERMS:
            break
    return out, hits


async def generate_explanation(
    document: dict[str, Any],
    level: int,
    *,
    excerpt: str | None = None,
    base: dict[str, Any] | None = None,
    violations: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """LLM으로 설명을 한 번 만든다. 실패하면 기본 문구."""
    dict_terms = candidate_terms(document.get("docType", "unknown"), document.get("fields") or {}, excerpt)
    payload: dict[str, Any] = {
        "level": level,
        "document": _document_for_llm(document),
        "availablePlaceholders": [f"{{{p}}}" for p in available_placeholders(document)],
        "dictionaryTerms": [{"term": e.term, "plain": e.plain} for e in dict_terms],
    }
    if base is not None:
        payload["baseExplanation"] = {k: base.get(k) for k in ("summaryTemplate", "consequences", "terms")}
    if violations:
        payload["violations"] = violations
    try:
        out = await get_llm().structured(
            role="fast",
            node="explain",
            system=load_prompt("explain"),
            user=json.dumps(payload, ensure_ascii=False),
            schema=ExplainOut,
        )
    except LLMError as exc:
        return default_explanation(document, level, excerpt), f"설명 생성 실패({type(exc).__name__}) → 기본 문구"
    terms, hits = resolve_terms(out.terms)
    explanation = Explanation.model_validate(
        {
            "level": level,
            "summaryTemplate": out.summary_template.strip(),
            "consequences": [c.strip() for c in out.consequences if c and c.strip()][:3],
            "terms": terms,
        }
    ).to_api()
    note = f"lookup_terms 후보 {len(dict_terms)}건, 사전 일치 {hits}건, LLM 풀이 {len(terms) - hits}건"
    return explanation, note


async def explain(state: AgentState) -> dict[str, Any]:
    attempts = state.get("explain_attempts", 0)
    started: list[dict[str, Any]] = []
    if attempts == 0:
        # 실행 로그 순서를 실제 시작 순서에 맞추려고 running 단계도 기록한다 (최종 상태는 verify_explanation 이 정함)
        started.append(StepHandle(session_id=state.get("session_id"), id="explain", label=LABEL, done_label=DONE_LABEL, tool="lookup_terms").running())
    explanation, note = await generate_explanation(
        state["document"], 1, excerpt=state.get("raw_excerpt"), violations=state.get("explain_violations")
    )
    notes = list(state.get("explain_notes") or []) + [note]
    return {
        "explanation": explanation,
        "explain_attempts": attempts + 1,
        "explain_notes": notes,
        "explain_violations": None,
        "steps": started,
    }


async def simplify_explanation(document: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """/api/simplify: 보관된 추출 결과로 설명만 level 2로 다시 만든다 (검사·1회 재생성 포함)."""
    violations: list[str] | None = None
    for _ in range(MAX_EXPLAIN_ATTEMPTS):
        explanation, _note = await generate_explanation(document, 2, base=base, violations=violations)
        violations = find_violations(explanation, document, base=base)
        if not violations:
            return explanation
    return default_explanation(document, 2)
