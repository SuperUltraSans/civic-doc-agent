"""verify_explanation (지시서 5.4절): 허용 밖 자리표시자, null 필드 자리표시자, 숫자 노출."""

import pytest

from app.agent.nodes.verify_explanation import available_placeholders, default_explanation, find_violations

DOC = {
    "docType": "health_insurance_bill",
    "docTypeLabel": "건강보험료 고지서",
    "issuer": "국민건강보험공단",
    "fields": {"amount": 32500, "dueDate": "2026-10-10", "billingMonth": "2026-09"},
}


def exp(summary, consequences=(), terms=()):
    return {"level": 1, "summaryTemplate": summary, "consequences": list(consequences), "terms": list(terms)}


@pytest.mark.parametrize(
    "summary, ok",
    [
        ("{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내라는 안내예요.", True),
        ("{issuer}에서 보낸 고지서예요.", True),
        ("두 번 나눠 낼 수도 있어요.", True),
        ("{phone}으로 전화하세요.", False),  # 허용 목록 밖
        ("{arrears}이 밀려 있어요.", False),  # 값이 null인 필드
        ("{ amount }을 내세요.", False),  # 허용 밖 이름
        ("건강보험료 32,500원을 내세요.", False),  # 쉼표 숫자
        ("건강보험료 32500원을 내세요.", False),  # 3자리 이상 숫자
        ("10월 6일까지 내세요.", False),  # 날짜 형태
        ("2026-10 분 보험료예요.", False),
        ("3만 원이에요.", False),  # 금액 표현
        ("가산금 3%가 붙어요.", False),
        ("{amount}을 {dueDate}까지 내세요. 이 문서는 안전합니다.", False),  # 단정 표현
        ("{amount을 내세요.", False),  # 닫히지 않은 중괄호
        ("<b>{amount}</b>을 내세요.", False),  # HTML 금지
        ("", False),
    ],
)
def test_summary_rules(summary, ok):
    assert (find_violations(exp(summary), DOC) == []) is ok


def test_consequences_and_llm_terms_checked():
    bad = exp("{amount}을 내세요.", consequences=["5일 지나면 연체금이 붙어요."])
    assert find_violations(bad, DOC)
    bad_term = exp("{amount}을 내세요.", terms=[{"term": "가산금", "plain": "3% 더 내는 돈", "source": "llm"}])
    assert find_violations(bad_term, DOC)
    dict_term = exp("{amount}을 내세요.", terms=[{"term": "x", "plain": "100원", "source": "dictionary"}])
    assert find_violations(dict_term, DOC) == []  # 사전 풀이는 고정 문구라 검사하지 않음


def test_level2_must_keep_placeholders():
    base = exp("{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내라는 안내예요.")
    same = exp("{billingMonth}분 보험료 {amount}을 {dueDate}까지 내세요.")
    dropped = exp("보험료 {amount}을 {dueDate}까지 내세요.")
    assert find_violations(same, DOC, base=base) == []
    assert find_violations(dropped, DOC, base=base)


@pytest.mark.parametrize(
    "doc_type, fields, issuer",
    [
        ("health_insurance_bill", {"amount": 32500, "dueDate": "2026-10-10", "arrears": 1000}, "국민건강보험공단"),
        ("local_tax_bill", {"amount": 86400, "dueDate": "2026-10-17"}, ""),
        ("fine_notice", {"amount": 40000}, "경찰청"),
        ("suspicious_message", {"url": "bit.ly/x"}, "국민건강보험공단"),
        ("suspicious_message", {"url": "bit.ly/x"}, ""),
        ("basic_pension_notice", {}, "국민연금공단"),
    ],
)
@pytest.mark.parametrize("level", [1, 2])
def test_default_explanation_always_passes(doc_type, fields, issuer, level):
    doc = {"docType": doc_type, "docTypeLabel": "문서", "issuer": issuer, "fields": fields}
    default = default_explanation(doc, level)
    assert default["level"] == level
    assert find_violations(default, doc) == []


def test_available_placeholders():
    assert available_placeholders(DOC) == ["amount", "dueDate", "billingMonth", "issuer"]
    assert available_placeholders({"issuer": " ", "fields": {"arrears": 0}}) == ["arrears"]
