"""lookup_terms 검색 순서, 로그 가림 처리, 조사 선택."""

import pytest

from app.logging_setup import mask_sensitive
from app.textutil import ieyo
from app.tools.terms import candidate_terms, lookup_term, normalize_term


@pytest.mark.parametrize(
    "query, term",
    [
        ("체납액", "체납액"),  # 정확히 일치
        ("미납액", "체납액"),  # 별칭
        ("체납액은", "체납액"),  # 조사 제거
        ("납기 내 금액이", "납기 내 금액"),  # 공백·조사 제거
        ("납기내금액", "납기 내 금액"),
        ("양자역학", None),
    ],
)
def test_lookup_order(query, term):
    entry = lookup_term(query)
    assert (entry.term if entry else None) == term


def test_normalize_term():
    assert normalize_term(" 납기 내 금액을 ") == "납기내금액"


def test_candidates_prefer_terms_in_document_text():
    entries = candidate_terms("health_insurance_bill", {"amount": 1}, "지역가입자 보험료 고지서")
    assert entries[0].term == "지역가입자"
    assert len(entries) <= 6


@pytest.mark.parametrize(
    "text, expected",
    [
        ("문의 010-1234-5678 로", "문의 010-****-5678 로"),
        ("계좌 123-456-789012", "계좌 ****-9012"),
        ("주소 http://bit.ly/abc?x=1", "주소 bit.ly/…"),
        ("세금 3만 원", "세금 3만 원"),
    ],
)
def test_mask_sensitive(text, expected):
    assert mask_sensitive(text) == expected


@pytest.mark.parametrize(
    "word, expected",
    [("건강보험료 고지서", "건강보험료 고지서예요"), ("기초연금 안내문", "기초연금 안내문이에요"), ("사칭 의심 문자", "사칭 의심 문자예요")],
)
def test_ieyo(word, expected):
    assert ieyo(word) == expected
