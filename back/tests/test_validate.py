"""validate 규칙 (지시서 5.3절) — 입력 → 기대값 표."""

from datetime import date, timedelta

import pytest

from app.agent.nodes.validate import (
    field_problems,
    is_valid_amount,
    is_valid_arrears,
    is_valid_billing_month,
    is_valid_due_date,
    is_valid_url,
    missing_required,
)

BASE = date(2026, 10, 5)


@pytest.mark.parametrize(
    "value, ok",
    [
        (32500, True),
        (1, True),
        (99_999_999, True),
        (100_000_000, False),  # 1억 원 미만
        (0, False),
        (-100, False),
        ("32500", False),
        (32500.5, False),
        (True, False),
        (None, False),
    ],
)
def test_amount(value, ok):
    assert is_valid_amount(value) is ok


@pytest.mark.parametrize(
    "value, ok",
    [
        ("2026-10-06", True),
        ((BASE - timedelta(days=365)).isoformat(), True),
        ((BASE - timedelta(days=366)).isoformat(), False),
        ((BASE + timedelta(days=180)).isoformat(), True),
        ((BASE + timedelta(days=181)).isoformat(), False),
        ("2026-02-30", False),  # 없는 날짜
        ("2026/10/06", False),
        ("10월 6일", False),
        (None, False),
    ],
)
def test_due_date(value, ok):
    assert is_valid_due_date(value, BASE) is ok


@pytest.mark.parametrize(
    "month, due, ok",
    [
        ("2026-09", "2026-10-06", True),
        ("2026-10", "2026-10-06", True),
        ("2026-11", "2026-10-06", False),  # 기한보다 늦은 월
        ("2026-13", None, False),
        ("2026-9", None, False),
        ("2026-09", None, True),
    ],
)
def test_billing_month(month, due, ok):
    assert is_valid_billing_month(month, due) is ok


@pytest.mark.parametrize(
    "arrears, amount, ok",
    [
        (21000, 32500, True),
        (0, 32500, True),
        (32500, 32500, True),
        (32501, 32500, False),  # 납부 금액 이하
        (-1, 32500, False),
        (21000, None, True),
    ],
)
def test_arrears(arrears, amount, ok):
    assert is_valid_arrears(arrears, amount) is ok


@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://www.nhis.or.kr", True),
        ("bit.ly/abc", True),
        ("http://bit.ly/nhis-refund", True),
        ("not a url", False),
        ("localhost", False),
        ("", False),
    ],
)
def test_url(url, ok):
    assert is_valid_url(url) is ok


def test_low_confidence_is_suspicious():
    problems = field_problems(
        {"amount": 32500, "dueDate": "2026-10-10", "arrears": 21000},
        {"amount": 0.95, "dueDate": 0.69, "arrears": 0.7},
        BASE,
    )
    assert problems == {"dueDate": "신뢰도 낮음(0.69)"}


def test_format_error_beats_confidence():
    problems = field_problems({"amount": -5, "phone": "12"}, {"amount": 0.99, "phone": 0.99}, BASE)
    assert problems == {"amount": "형식 오류", "phone": "형식 오류"}


@pytest.mark.parametrize(
    "doc_type, fields, missing",
    [
        ("health_insurance_bill", {"amount": 1, "dueDate": "2026-10-10"}, []),
        ("health_insurance_bill", {"amount": 1}, ["dueDate"]),
        ("local_tax_bill", {}, ["amount", "dueDate"]),
        ("fine_notice", {"dueDate": "2026-10-10"}, ["amount"]),
        ("basic_pension_notice", {}, []),
        ("suspicious_message", {"url": "bit.ly/x"}, []),
        ("suspicious_message", {"phone": "010-1234-5678"}, []),
        ("suspicious_message", {"amount": 1000}, ["phone", "url"]),
    ],
)
def test_required_fields(doc_type, fields, missing):
    assert missing_required(doc_type, fields) == missing
