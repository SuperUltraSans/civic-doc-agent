"""계획 병합 (지시서 5.5절): 필수 도구 강제, 목록 밖 도구 제거, 지역 없음 → 질문."""

import pytest

from app.agent.nodes.plan import merge_plan, needs_region, required_tools, route_after_plan

BILL = {"docType": "health_insurance_bill", "fields": {"amount": 1, "dueDate": "2026-10-10", "phone": "1577-1000"}}


@pytest.mark.parametrize(
    "document, tools",
    [
        (BILL, ["check_impersonation", "manage_deadline"]),
        ({"docType": "health_insurance_bill", "fields": {"amount": 1, "dueDate": "2026-10-10"}}, ["manage_deadline"]),
        ({"docType": "suspicious_message", "fields": {}}, ["check_impersonation"]),
        ({"docType": "suspicious_message", "fields": {"url": "bit.ly/x", "dueDate": "2026-10-10"}}, ["check_impersonation"]),
        ({"docType": "basic_pension_notice", "fields": {"url": "https://x.go.kr"}}, ["check_impersonation"]),
        ({"docType": "basic_pension_notice", "fields": {}}, []),
    ],
)
def test_required_rules(document, tools):
    assert [r["tool"] for r in required_tools(document)] == tools
    assert all(r["required"] for r in required_tools(document))


def test_required_tool_forced_when_llm_omits_it():
    merged, dropped = merge_plan(required_tools(BILL), [{"tool": "search_welfare", "reason": "체납이 있어 찾아봐요"}])
    assert [(m["tool"], m["required"]) for m in merged] == [
        ("check_impersonation", True),
        ("manage_deadline", True),
        ("search_welfare", False),
    ]
    assert merged[0]["reason"] == "문서에 연락처가 있어 공식 정보와 비교해요"
    assert dropped == []


def test_out_of_list_tools_dropped_and_duplicates_ignored():
    llm = [
        {"tool": "send_money", "reason": "x"},
        {"tool": "lookup_terms", "reason": "x"},  # 플래너가 고를 수 없는 도구
        {"tool": "manage_deadline", "reason": "날짜를 정리해요"},
        {"tool": "manage_deadline", "reason": "중복"},
    ]
    merged, dropped = merge_plan(required_tools(BILL), llm)
    assert [m["tool"] for m in merged] == ["check_impersonation", "manage_deadline"]
    assert merged[1]["reason"] == "날짜를 정리해요"  # LLM 이유 유지, 필수 표시
    assert merged[1]["required"] is True
    assert dropped == ["send_money", "lookup_terms"]


def test_assertive_reason_replaced():
    merged, _ = merge_plan([], [{"tool": "search_welfare", "reason": "이 분은 수급 대상입니다"}])
    assert "대상입니다" not in merged[0]["reason"]


@pytest.mark.parametrize(
    "plan_tools, profile, asked, route",
    [
        (["search_welfare"], {}, False, "ask_user"),
        (["search_welfare"], {"region": "김해시"}, False, "run_tools"),
        (["search_welfare"], {}, True, "run_tools"),  # 질문은 세션당 1회
        (["manage_deadline"], {}, False, "run_tools"),
    ],
)
def test_region_question_route(plan_tools, profile, asked, route):
    plan = [{"tool": t, "reason": "r", "required": False} for t in plan_tools]
    assert route_after_plan({"plan": plan, "profile": profile, "asked": asked}) == route


def test_needs_region():
    welfare = [{"tool": "search_welfare", "reason": "r", "required": False}]
    assert needs_region(welfare, {}) is True
    assert needs_region(welfare, {"region": "창원시"}) is False
    assert needs_region([], {}) is False


def test_numeric_reason_replaced():
    """이유는 '확인 과정 보기'에 그대로 보이므로 금액·날짜가 들어 있으면 규칙 문장으로 바꾼다."""
    llm = [{"tool": "manage_deadline", "reason": "과태료 32,000원과 2019년 5월 15일 기한을 정리해요"}]
    merged, _ = merge_plan(required_tools(BILL), llm)
    deadline = next(m for m in merged if m["tool"] == "manage_deadline")
    assert deadline["reason"] == "문서에 내야 하는 날짜가 있어 기한을 정리해요"


async def test_numeric_situation_replaced_in_plan_node(monkeypatch):
    """상황 문장에 숫자가 있으면 기본 문장으로 바꾸고, 실행 로그(detail)에도 숫자가 남지 않는다."""
    from app.agent.nodes import plan as plan_node
    from app.llm.schemas import PlanOut

    class StubLLM:
        async def structured(self, **_):
            return PlanOut.model_validate(
                {
                    "situation": "서울특별시 종로구의 32,000원 과태료 고지서로, 납부기한은 2019년 5월 15일이에요.",
                    "plan": [{"tool": "manage_deadline", "reason": "이미 지난 2019-05-15 기한을 정리해요"}],
                    "needUserInfo": [],
                }
            )

    monkeypatch.setattr(plan_node, "get_llm", lambda: StubLLM())
    doc = {
        "docType": "fine_notice",
        "docTypeLabel": "과태료 고지서",
        "issuer": "서울특별시 종로구청",
        "fields": {"amount": 32000, "dueDate": "2019-05-15", "phone": "02-2148-3362"},
    }
    out = await plan_node.plan({"document": doc, "profile": {}})
    assert out["situation"] == "과태료 고지서예요"
    step_detail = out["steps"][0]["detail"]
    assert "32,000" not in step_detail and "2019" not in step_detail
    assert "상황 문장" in step_detail  # 바꿨다는 사실은 남긴다
    assert all("2019" not in p["reason"] for p in out["plan"])


def test_default_situation_mentions_arrears_without_numbers():
    from app.agent.nodes.plan import default_situation

    assert default_situation({"docTypeLabel": "건강보험료 고지서", "fields": {"arrears": 21000}}) == "밀린 금액이 포함된 건강보험료 고지서예요"
    assert default_situation({"docTypeLabel": "기초연금 안내문", "fields": {}}) == "기초연금 안내문이에요"
