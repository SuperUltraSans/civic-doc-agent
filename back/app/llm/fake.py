"""LLM_PROVIDER=fake 응답 — 시나리오별로 미리 기록한 응답 (테스트·초기 연동용, 지시서 7.1절).

시나리오 키는 프론트 목업과 같다: arrears, blurry, smishing, local_tax, error (+ pension).
날짜는 실행 시점 기준 상대값으로 만든다. 이름·번호·주소는 모두 가상값이다.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from app.llm.client import LLMNetworkError
from app.timeutil import today


def _prev_month() -> str:
    first = today().replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _due(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def _extract(scenario: str) -> dict[str, Any]:
    if scenario == "error":
        raise LLMNetworkError("fake: 연결 끊김 시나리오")
    if scenario == "blurry":
        return {
            "docType": "health_insurance_bill",
            "issuer": None,
            "fields": {},
            "confidence": {},
            "legible": False,
            "rawTextExcerpt": None,
        }
    if scenario == "smishing":
        return {
            "docType": "suspicious_message",
            "issuer": "국민건강보험공단",
            "fields": {"amount": 38200, "phone": "010-1234-5678", "url": "http://bit.ly/nhis-refund-example"},
            "confidence": {"amount": 0.93, "phone": 0.95, "url": 0.9},
            "legible": True,
            "rawTextExcerpt": "[국민건강보험] 건강보험료 환급금 38,200원이 발생했습니다. 오늘까지 아래 주소에서 신청하세요 http://bit.ly/nhis-refund-example 문의 010-1234-5678",
        }
    if scenario == "local_tax":
        return {
            "docType": "local_tax_bill",
            "issuer": "김해시",
            "fields": {"amount": 86400, "dueDate": _due(12)},
            "confidence": {"amount": 0.97, "dueDate": 0.95},
            "legible": True,
            "rawTextExcerpt": "재산세(주택) 납부 고지서 납기 내 금액 86,400원 전자납부번호 ○○○ 가상계좌 ○○○",
        }
    if scenario == "city_fine":
        # 시청·구청 과태료 고지서: 시드 표에 없는 기관 + 부서 번호 + http 로 적힌 공식(.go.kr) 주소
        return {
            "docType": "fine_notice",
            "issuer": "서울특별시 종로구청",
            "fields": {"amount": 32000, "dueDate": _due(20), "phone": "02-2148-3362", "url": "http://cartax.seoul.go.kr"},
            "confidence": {"amount": 0.95, "dueDate": 0.95, "phone": 0.9, "url": 0.9},
            "legible": True,
            "rawTextExcerpt": "주정차위반 과태료 부과 사전통지서 과태료 32,000원 납부기한 문의처 02-2148-3362 인터넷 납부 http://cartax.seoul.go.kr",
        }
    if scenario == "pension":
        return {
            "docType": "basic_pension_notice",
            "issuer": "국민연금공단",
            "fields": {"phone": "1355"},
            "confidence": {"phone": 0.9},
            "legible": True,
            "rawTextExcerpt": "기초연금 신청 안내 소득인정액이 선정기준액 이하인 경우 신청할 수 있습니다 문의 1355",
        }
    # arrears (기본): 체납액 신뢰도가 낮아 재확인(Feedback) 흐름을 보여준다
    return {
        "docType": "health_insurance_bill",
        "issuer": "국민건강보험공단",
        "fields": {"amount": 32500, "dueDate": _due(5), "billingMonth": _prev_month(), "arrears": 21000, "phone": "1577-1000"},
        "confidence": {"amount": 0.95, "dueDate": 0.9, "billingMonth": 0.9, "arrears": 0.6, "phone": 0.95},
        "legible": True,
        "rawTextExcerpt": "건강보험료 납입고지서 지역가입자 납기 내 금액 32,500원 체납액 21,000원 (2개월) 장기요양보험료 포함 고객센터 1577-1000",
    }


def _recheck(scenario: str, user: str) -> dict[str, Any]:
    if scenario == "arrears":
        return {"fields": {"arrears": 21000}, "confidence": {"arrears": 0.92}}
    return {"fields": {}, "confidence": {}}


def _payload(user: str) -> dict[str, Any]:
    try:
        return json.loads(user[user.index("{") :]) if "{" in user else {}
    except (ValueError, json.JSONDecodeError):
        return {}


def _explain(scenario: str, user: str) -> dict[str, Any]:
    data = _payload(user)
    level = data.get("level", 1)
    doc = data.get("document") or {}
    fields = doc.get("fields") or {}
    available = set(data.get("availablePlaceholders") or [])
    dict_terms = data.get("dictionaryTerms") or []
    doc_type = doc.get("docType")

    if doc_type == "suspicious_message":
        summary = "{issuer}에서 보냈다고 하는 문자예요." if level == 1 else "{issuer}라고 적힌 문자예요."
        consequences = ["문자 속 주소를 누르면 돈이나 개인정보를 잃을 수 있어요."]
    elif doc_type == "basic_pension_notice":
        summary = "{issuer}에서 기초연금을 신청할 수 있다고 알려 주는 안내문이에요." if level == 1 else "{issuer}에서 보낸 기초연금 신청 안내예요."
        consequences = []
    else:
        pay = {"health_insurance_bill": "건강보험료", "local_tax_bill": "지방세", "fine_notice": "과태료"}.get(doc_type, "돈")
        month = "{billingMonth}분 " if "{billingMonth}" in available else ""
        summary = (
            f"{month}{pay} {{amount}}을 {{dueDate}}까지 내라는 안내예요."
            if level == 1
            else f"{month}{pay} {{amount}}을 {{dueDate}}까지 내세요."
        )
        consequences = ["기한이 지나면 돈이 더 붙을 수 있어요."] if level == 1 else ["늦으면 돈이 더 붙어요."]
        if fields.get("arrears"):
            consequences.append("밀린 돈은 따로 나눠 낼 수 있는지 물어볼 수 있어요." if level == 1 else "밀린 돈은 나눠 낼 수 있는지 물어보세요.")
        # 첫 시도에 숫자를 직접 써서 verify_explanation 의 재생성(Feedback)을 보여준다
        if scenario == "arrears" and level == 1 and not data.get("violations"):
            summary = f"{month}{pay} 32,500원을 {{dueDate}}까지 내라는 안내예요."
    terms = [{"term": t["term"], "plain": t["plain"]} for t in dict_terms[:2]]
    if doc_type == "health_insurance_bill":
        terms.append({"term": "고지 대상 월", "plain": "어느 달 몫의 보험료인지"})
    return {"summaryTemplate": summary, "consequences": consequences, "terms": terms}


def _plan(scenario: str, user: str) -> dict[str, Any]:
    data = _payload(user)
    doc = data.get("document") or {}
    fields = doc.get("fields") or {}
    plan: list[dict[str, str]] = []
    if fields.get("phone") or fields.get("url") or doc.get("docType") == "suspicious_message":
        plan.append({"tool": "check_impersonation", "reason": "적힌 연락처가 기관 공식 번호가 맞는지 확인해요"})
    if fields.get("dueDate") and doc.get("docType") != "suspicious_message":
        plan.append({"tool": "manage_deadline", "reason": "내야 하는 날짜를 놓치지 않게 정리해요"})
    welfare = (fields.get("arrears") or 0) > 0 or doc.get("docType") == "basic_pension_notice"
    if welfare:
        reason = "밀린 돈이 있어 나눠 내기나 지원 제도를 찾아봐요" if fields.get("arrears") else "기초연금 안내문이라 함께 알아볼 만한 제도를 찾아봐요"
        plan.append({"tool": "search_welfare", "reason": reason})
    situations = {
        "health_insurance_bill": "밀린 금액이 포함된 건강보험료 고지서예요" if fields.get("arrears") else "건강보험료 고지서예요",
        "local_tax_bill": "체납 없는 지방세 고지서예요",
        "suspicious_message": "공단을 사칭한 것으로 의심되는 환급 문자예요",
        "basic_pension_notice": "기초연금 신청 안내문이에요",
    }
    return {
        "situation": situations.get(doc.get("docType"), "문서를 확인해요"),
        "plan": plan,
        "needUserInfo": ["region"] if welfare and not data.get("hasRegion") else [],
    }


def _welfare_rerank(scenario: str, user: str) -> dict[str, Any]:
    data = _payload(user)
    tags = data.get("tags") or []
    picks = []
    for c in data.get("candidates") or []:
        hit = next((t for t in tags if t in c.get("name", "") + c.get("summary", "")), None)
        if hit:
            picks.append({"id": c["id"], "reason": f"문서의 '{hit}' 관련 내용과 이어지는 제도라서 해당될 수 있어요."})
        if len(picks) >= 2:
            break
    return {"items": picks}


def _scam_select(scenario: str, user: str) -> dict[str, Any]:
    data = _payload(user)
    excerpt = data.get("excerpt") or ""
    selected = []
    for c in data.get("candidates") or []:
        if any(sig and sig in excerpt for sig in c.get("signals", [])):
            selected.append({"id": c["id"], "evidence": "문자에 해당 표현이 있어요"})
    return {"selected": selected[:2]}


def _review(scenario: str, user: str) -> dict[str, Any]:
    """기록된 검토 응답: 공식 번호를 못 찾았고 시·도가 붙은 시청·구청·군청이면 짧은 관청 이름("종로구청")으로
    다시 찾기, 그 밖에는 추가 확인 없음."""
    data = _payload(user)
    imp = (data.get("results") or {}).get("impersonation") or {}
    issuer = ((data.get("document") or {}).get("issuer") or "").strip()
    available = data.get("available") or {}
    last = issuer.split()[-1] if issuer else ""
    name = last + "청" if last[-1:] in ("시", "구", "군") else last
    if available.get("find_official_contact") and imp and not imp.get("officialPhoneFound") and name.endswith("청") and name != issuer:
        return {
            "assessment": "공식 번호를 찾지 못해 기관 이름을 바꿔 다시 찾아볼게요",
            "actions": [{"tool": "find_official_contact", "reason": "구청 이름으로 공식 번호를 다시 찾아봐요", "keywords": [], "agencyName": name}],
        }
    return {"assessment": "필요한 확인을 모두 마쳤어요", "actions": []}


HANDLERS = {
    "extract_recheck": _recheck,
    "explain": _explain,
    "plan": _plan,
    "welfare_rerank": _welfare_rerank,
    "scam_select": _scam_select,
    "review": _review,
}


def fake_response(*, node: str, scenario: str, user: str) -> dict[str, Any]:
    if node == "extract":
        return _extract(scenario)
    handler = HANDLERS.get(node)
    if handler is None:
        raise KeyError(f"fake response 없음: {node}")
    return handler(scenario, user)
