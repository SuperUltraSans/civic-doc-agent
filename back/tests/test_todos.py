"""할 일 생성 표 (지시서 5.10절의 모든 조건)."""

import pytest

from app.agent.nodes.compose import build_todos, finalize_steps

DOC_ID = "doc1"
BILL = {
    "docType": "health_insurance_bill",
    "docTypeLabel": "건강보험료 고지서",
    "issuer": "국민건강보험공단",
    "fields": {"amount": 32500, "dueDate": "2026-10-10", "arrears": 21000, "phone": "02-999-9999"},
}
MATCH = {"status": "match", "checkedValue": "1577-1000", "officialPhone": "1577-1000", "redFlags": []}
MISMATCH = {"status": "mismatch", "checkedValue": "010-1234-5678", "officialPhone": "1577-1000", "redFlags": ["x"]}
UNKNOWN_NO_PHONE = {"status": "unknown", "checkedValue": "02-999-9999", "redFlags": []}
DEADLINE = {"dueDate": "2026-10-10", "amount": 32500, "calendarTitle": "건강보험료 내는 날 (읽어드림)"}
WELFARE = {
    "items": [
        {"name": "건강보험료 분할납부", "summary": "s", "reason": "r", "url": "https://www.nhis.or.kr"},
        {"name": "복지멤버십", "summary": "s", "reason": "r", "url": "https://www.bokjiro.go.kr", "fixed": True},
    ],
    "usedProfile": True,
    "fallbackUsed": False,
}


def titles(todos):
    return [t["title"] for t in todos]


def test_bill_with_arrears_and_welfare():
    todos = build_todos(DOC_ID, BILL, MATCH, DEADLINE, WELFARE)
    assert titles(todos) == ["건강보험료 내기", "나눠서 낼 수 있는지 물어보기", "도움 받을 수 있는 제도 알아보기"]
    pay = todos[0]
    assert pay["amount"] == 32500 and pay["dueDate"] == "2026-10-10"
    assert pay["actions"] == [
        {"type": "call", "label": "공단에 전화하기", "tel": "1577-1000"},
        {"type": "calendar", "label": "달력에 추가하기", "title": "건강보험료 내는 날 (읽어드림)", "date": "2026-10-10"},
    ]
    assert todos[1]["actions"] == [{"type": "call", "label": "공단에 전화하기", "tel": "1577-1000"}]
    assert todos[2]["actions"] == [{"type": "link", "label": "홈페이지에서 확인하기", "url": "https://www.nhis.or.kr"}]


def test_phone_button_never_uses_document_number():
    for imp in (MATCH, MISMATCH, UNKNOWN_NO_PHONE, None):
        for todo in build_todos(DOC_ID, BILL, imp, DEADLINE, None):
            for action in todo["actions"]:
                if action["type"] == "call":
                    assert action["tel"] in {"1577-1000", "110"}


def test_mismatch_no_payment_todo():
    todos = build_todos(DOC_ID, BILL, MISMATCH, DEADLINE, None)
    assert titles(todos) == ["공식 번호로 진짜인지 확인하기"]
    assert todos[0]["actions"][0]["tel"] == "1577-1000"


def test_mismatch_without_official_phone_uses_110():
    todos = build_todos(DOC_ID, BILL, {**MISMATCH, "officialPhone": None}, DEADLINE, None)
    assert todos[0]["actions"] == [{"type": "call", "label": "정부민원안내콜센터에 전화하기", "tel": "110"}]


def test_unknown_adds_verify_first_then_payment():
    todos = build_todos(DOC_ID, BILL, UNKNOWN_NO_PHONE, DEADLINE, None)
    assert titles(todos) == ["공식 대표번호로 확인하기", "건강보험료 내기", "나눠서 낼 수 있는지 물어보기"]
    assert todos[0]["actions"][0]["tel"] == "110"
    assert [a["type"] for a in todos[1]["actions"]] == ["calendar"]  # 공식 번호 없으면 전화 버튼 없음


@pytest.mark.parametrize(
    "doc_type, title",
    [("local_tax_bill", "지방세 내기"), ("fine_notice", "과태료 내기"), ("health_insurance_bill", "건강보험료 내기")],
)
def test_payment_title_by_doc_type(doc_type, title):
    doc = {**BILL, "docType": doc_type, "fields": {"amount": 1000, "dueDate": "2026-10-10"}}
    assert titles(build_todos(DOC_ID, doc, None, None, None)) == [title]


@pytest.mark.parametrize(
    "fields",
    [{"amount": 1000}, {"dueDate": "2026-10-10"}, {}],
)
def test_payment_needs_amount_and_due(fields):
    doc = {**BILL, "fields": fields}
    assert "건강보험료 내기" not in titles(build_todos(DOC_ID, doc, None, None, None))


def test_non_bill_no_payment_todo_and_membership_only_welfare_no_todo():
    doc = {"docType": "basic_pension_notice", "docTypeLabel": "기초연금 안내문", "issuer": "국민연금공단", "fields": {"dueDate": "2026-10-10"}}
    membership_only = {**WELFARE, "items": [WELFARE["items"][1]]}
    assert build_todos(DOC_ID, doc, None, None, membership_only) == []


def test_todo_ids_unique_and_doc_id():
    todos = build_todos(DOC_ID, BILL, UNKNOWN_NO_PHONE, DEADLINE, WELFARE)
    assert len({t["id"] for t in todos}) == len(todos)
    assert all(t["docId"] == DOC_ID for t in todos)


def test_finalize_steps_keeps_last_status_in_first_order():
    steps = [
        {"id": "a", "label": "A", "status": "running"},
        {"id": "b", "label": "B", "status": "done"},
        {"id": "a", "label": "A", "status": "done", "detail": "d"},
    ]
    assert finalize_steps(steps) == [
        {"id": "a", "label": "A", "status": "done", "detail": "d"},
        {"id": "b", "label": "B", "status": "done"},
    ]


def test_no_contact_on_document_uses_seed_official_phone():
    """문서에 연락처가 없어 사칭 확인을 안 했으면 발신 기관의 시드 표 번호를 쓴다 (문서 번호 아님)."""
    doc = {**BILL, "fields": {"amount": 32500, "dueDate": "2026-10-10", "arrears": 21000}}
    todos = build_todos(DOC_ID, doc, None, DEADLINE, None)
    assert titles(todos) == ["건강보험료 내기", "나눠서 낼 수 있는지 물어보기"]
    assert todos[0]["actions"][0] == {"type": "call", "label": "공단에 전화하기", "tel": "1577-1000"}
    assert todos[1]["actions"] == [{"type": "call", "label": "공단에 전화하기", "tel": "1577-1000"}]


def test_installment_without_any_official_phone_uses_110():
    doc = {**BILL, "issuer": "어느 기관", "fields": {"amount": 32500, "dueDate": "2026-10-10", "arrears": 21000}}
    todos = build_todos(DOC_ID, doc, None, DEADLINE, None)
    assert [a["type"] for a in todos[0]["actions"]] == ["calendar"]  # 납부 할 일: 공식 번호 없으면 전화 버튼 없음
    assert todos[1]["actions"] == [{"type": "call", "label": "정부민원안내콜센터에 전화하기", "tel": "110"}]
