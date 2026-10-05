"""사칭 판정 표 (지시서 5.7절 판정 규칙의 모든 경우)."""

import pytest

from app.tools.impersonation import check_url, decide_verdict, resolve_agency

OFFICIAL_PHONES = ["1577-1000"]
OFFICIAL_DOMAINS = ["nhis.or.kr"]


def verdict(phone=None, url=None, phones=OFFICIAL_PHONES, domains=OFFICIAL_DOMAINS, rag=0):
    return decide_verdict(
        doc_phone=phone,
        doc_url=url,
        official_phones=phones,
        official_domains=domains,
        url_issues=check_url(url, domains),
        rag_flag_count=rag,
    )


@pytest.mark.parametrize(
    "case, kwargs, expected",
    [
        # match: 공식 번호 중 하나와 같고 주소 검사에 걸린 것이 없음
        ("공식 번호 일치", {"phone": "1577-1000"}, "match"),
        ("하이픈 없는 공식 번호", {"phone": "15771000"}, "match"),
        ("공식 번호 + 공식 https 주소", {"phone": "1577-1000", "url": "https://www.nhis.or.kr"}, "match"),
        ("번호 없이 공식 https 주소", {"url": "https://www.nhis.or.kr"}, "match"),
        # mismatch: 공식 번호와 다르고 + (휴대전화 | 주소 위반 | 수법 근거 1개 이상)
        ("다른 번호 + 휴대전화", {"phone": "010-1234-5678"}, "mismatch"),
        ("다른 번호 + 단축 주소", {"phone": "02-123-4567", "url": "bit.ly/abc"}, "mismatch"),
        ("다른 번호 + 수법 근거", {"phone": "02-123-4567", "rag": 1}, "mismatch"),
        ("공식 번호여도 가짜 주소", {"phone": "1577-1000", "url": "http://nhis-refund.com"}, "mismatch"),
        ("주소만 있고 단축 주소", {"url": "http://bit.ly/abc"}, "mismatch"),
        # unknown: 그 외 전부
        ("번호만 다르고 다른 신호 없음(지사 번호 가능)", {"phone": "02-123-4567"}, "unknown"),
        ("공식 번호를 못 찾음 + 휴대전화", {"phone": "010-1234-5678", "phones": [], "domains": []}, "unknown"),
        ("공식 정보 없음 + 단축 주소", {"url": "bit.ly/abc", "phones": [], "domains": []}, "unknown"),
        ("공식 번호 + http 공식 주소", {"phone": "1577-1000", "url": "http://www.nhis.or.kr"}, "unknown"),
        ("연락처 없음", {}, "unknown"),
    ],
)
def test_verdict_table(case, kwargs, expected):
    assert verdict(**kwargs) == expected, case


def test_never_safe_value():
    """어떤 경우에도 '안전'을 뜻하는 상태값을 만들지 않는다."""
    for kwargs in ({"phone": "1577-1000"}, {"phone": "010-0000-0000"}, {}):
        assert verdict(**kwargs) in {"match", "mismatch", "unknown"}


@pytest.mark.parametrize(
    "issuer, name",
    [
        ("국민건강보험공단", "국민건강보험공단"),
        ("국민건강보험공단 ○○지사", "국민건강보험공단"),
        ("건보공단", "국민건강보험공단"),
        ("김해시장", "김해시"),
        ("서울중앙지검", "대검찰청"),
        ("모르는 회사", None),
        ("", None),
    ],
)
def test_resolve_agency(issuer, name):
    agency = resolve_agency(issuer)
    assert (agency.name if agency else None) == name
