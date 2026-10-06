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


# ── 기간 밖 기한: 오래된 문서는 두 번 같게 읽히면 인정 (모바일 실사용에서 옛 고지서가 '다시 찍기'만 반복되던 문제) ──
from app.agent.nodes import validate as validate_mod  # noqa: E402

OLD_FINE = {"docType": "fine_notice", "docTypeLabel": "과태료 고지서", "issuer": "서울특별시 종로구청", "fields": {"amount": 32000, "dueDate": "2019-05-15"}}


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(validate_mod, "today", lambda: BASE)


def test_out_of_range_is_not_format_error():
    assert field_problems({"dueDate": "2019-05-15"}, {}, BASE) == {"dueDate": "기간 밖"}
    assert field_problems({"dueDate": "2019-02-30"}, {}, BASE) == {"dueDate": "형식 오류"}


async def test_out_of_range_due_date_asks_blind_recheck(fixed_today):
    out = await validate_mod.validate({"document": OLD_FINE, "field_confidence": {}, "extract_attempts": 1, "legible": True})
    assert out["recheck_fields"] == ["dueDate"]
    assert out["recheck_blind"] == ["dueDate"] and out["recheck_previous"] == {"dueDate": "2019-05-15"}


async def test_same_value_twice_is_kept_as_old_document(fixed_today):
    state = {
        "document": OLD_FINE,  # 다시 읽어도 같은 날짜
        "field_confidence": {},
        "extract_attempts": 2,
        "legible": True,
        "recheck_previous": {"dueDate": "2019-05-15"},
    }
    out = await validate_mod.validate(state)
    assert "retake" not in out
    assert out["document"]["fields"]["dueDate"] == "2019-05-15"
    assert "두 번 같은 값으로 읽음 → 유지" in out["steps"][0]["detail"]


async def test_different_value_on_recheck_still_retakes_with_date_tip(fixed_today):
    reread = {**OLD_FINE, "fields": {"amount": 32000, "dueDate": "2018-05-15"}}  # 두 번 읽은 값이 다름
    state = {"document": reread, "field_confidence": {}, "extract_attempts": 2, "legible": True, "recheck_previous": {"dueDate": "2019-05-15"}}
    out = await validate_mod.validate(state)
    assert out["retake"]["message"] == "글씨가 잘 안 보여요"
    assert out["retake"]["tips"][0] == "날짜가 적힌 부분이 잘 보이게 찍어 주세요"


async def test_blind_recheck_does_not_show_previous_date(monkeypatch):
    """다시 읽을 때 앞서 읽은 기한을 보여 주지 않는다 (앞선 값에 끌려가 '두 번 같음'이 되지 않게)."""
    from app.agent.nodes import extract as extract_mod
    from app.llm.schemas import RecheckOut

    seen = {}

    class Stub:
        async def structured(self, **kwargs):
            seen["user"] = kwargs["user"]
            return RecheckOut.model_validate({"fields": {"dueDate": "2019-05-15"}, "confidence": {"dueDate": 0.9}})

    monkeypatch.setattr(extract_mod, "get_llm", lambda: Stub())
    out = await extract_mod.extract(
        {"document": OLD_FINE, "extract_attempts": 1, "recheck_fields": ["dueDate"], "recheck_blind": ["dueDate"], "image_bytes": b"x"}
    )
    assert "2019-05-15" not in seen["user"]
    assert out["document"]["fields"]["dueDate"] == "2019-05-15"
