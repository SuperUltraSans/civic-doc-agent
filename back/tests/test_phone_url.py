"""전화번호 정규화, 주소 검사 (지시서 9.1절)."""

import pytest

from app.tools.impersonation import (
    check_url,
    domain_of,
    edit_distance,
    format_phone,
    is_lookalike,
    is_mobile,
    is_valid_phone,
    normalize_phone,
)


@pytest.mark.parametrize(
    "raw, digits, formatted",
    [
        ("1577-1000", "15771000", "1577-1000"),
        ("15771000", "15771000", "1577-1000"),
        ("02-123-4567", "021234567", "02-123-4567"),
        ("010-1234-5678", "01012345678", "010-1234-5678"),
        ("+82 10-1234-5678", "01012345678", "010-1234-5678"),
        ("055 330 3000", "0553303000", "055-330-3000"),
        ("1355", "1355", "1355"),
    ],
)
def test_normalize_and_format(raw, digits, formatted):
    assert normalize_phone(raw) == digits
    assert format_phone(raw) == formatted


@pytest.mark.parametrize(
    "raw, ok",
    [
        ("1577-1000", True),  # 대표번호 8자리
        ("02-123-4567", True),
        ("010-1234-5678", True),
        ("1355", True),  # 특수번호 (지시서 규칙 확장)
        ("110", True),
        ("1234567", False),
        ("0101234567890", False),
        ("", False),
    ],
)
def test_valid_phone(raw, ok):
    assert is_valid_phone(raw) is ok


def test_mobile():
    assert is_mobile("01012345678")
    assert is_mobile("0111234567")
    assert not is_mobile("15771000")
    assert not is_mobile("0553303000")


NHIS = ["nhis.or.kr"]


@pytest.mark.parametrize(
    "url, domains, issues",
    [
        ("https://www.nhis.or.kr/main", NHIS, []),
        ("https://m.nhis.or.kr", NHIS, []),
        ("http://www.nhis.or.kr", NHIS, ["insecure"]),
        ("http://bit.ly/nhis-refund", NHIS, ["shortener", "not_official", "insecure"]),
        ("han.gl/abcd", NHIS, ["shortener", "not_official"]),
        ("https://nhls.or.kr", NHIS, ["not_official", "lookalike"]),  # 편집 거리 1
        ("https://nhis-pay.com/refund", NHIS, ["not_official", "lookalike"]),  # 공식 이름 끼워 넣기
        ("https://www.gov.kr", ["gov.kr"], []),
        ("https://www.mohw.go.kr", NHIS, []),  # .go.kr 은 공식 아님으로 보지 않는다
        ("http://bit.ly/x", [], ["shortener", "insecure"]),  # 공식 도메인을 모르면 공식 여부 검사 생략
        (None, NHIS, []),
    ],
)
def test_check_url(url, domains, issues):
    assert check_url(url, domains) == issues


def test_domain_and_distance():
    assert domain_of("HTTPS://WWW.NHIS.OR.KR/a?b") == "nhis.or.kr"
    assert domain_of("bit.ly/abc") == "bit.ly"
    assert edit_distance("nhis.or.kr", "nhls.or.kr") == 1
    assert not is_lookalike("nhis.or.kr", NHIS)
    assert not is_lookalike("naver.com", NHIS)
