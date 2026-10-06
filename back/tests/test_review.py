"""결과 검토(review)·추가 도구(run_followups) — 도구 결과를 보고 LLM이 추가 도구를 고르는 단계.

- 코드 규칙: 목록 밖·조건 밖 도구 버림, 이상한 기관 이름·검색어 버림, 숫자 섞인 이유 교체, 최대 2개
- 실행: 다시 찾아 공식 번호가 나오면 사칭 확인 결과를 바꾸고, 못 찾으면 그대로 둔다. 복지 결과는 합친다
- 안전: 종이 고지서는 구체적 위험 신호가 있을 때만 수법 검사 (진짜 고지서가 '사칭 의심'으로 뒤집히지 않게)
- 그래프 끝까지: 공식 번호 못 찾음 → LLM이 기관 이름 바꿔 다시 찾기 → 대표번호 찾음 → unknown + 대표번호 전화 버튼
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.nodes import review as review_node
from app.agent.nodes.review import availability, route_after_review, validate_actions
from app.llm.schemas import ReviewOut
from app.tools.impersonation import needs_scam_check
from app.tools.welfare import MEMBERSHIP_ITEM, merge_welfare
from tests.conftest import jpeg_bytes, parse_sse

DOC = {
    "docType": "fine_notice",
    "docTypeLabel": "과태료 고지서",
    "issuer": "서울특별시 종로구",
    "fields": {"amount": 32000, "dueDate": "2026-10-26", "phone": "02-2148-3362", "url": "http://cartax.seoul.go.kr"},
}
IMP_NO_OFFICIAL = {"status": "unknown", "checkedValue": "x", "redFlags": ["보호되지 않는 주소(http)예요"]}
IMP_OFFICIAL = {**IMP_NO_OFFICIAL, "officialPhone": "02-2148-1114"}
WELFARE = {"items": [{"name": "긴급복지지원", "summary": "s", "reason": "r", "url": "https://www.bokjiro.go.kr"}, dict(MEMBERSHIP_ITEM)], "usedProfile": False, "fallbackUsed": True}


def state(**tool_results):
    return {"document": DOC, "plan": [], "tool_results": tool_results, "steps": [], "profile": {}}


def act(tool, reason="이유", keywords=(), agency_name=None):
    return SimpleNamespace(tool=tool, reason=reason, keywords=list(keywords), agency_name=agency_name)


# ── 코드 규칙 ──
def test_availability():
    assert availability(state(impersonation=IMP_NO_OFFICIAL))["find_official_contact"] is True
    assert availability(state(impersonation=IMP_OFFICIAL))["find_official_contact"] is False
    assert availability(state())["find_official_contact"] is False  # 사칭 확인을 안 했으면 다시 찾을 것도 없다


def test_validate_accepts_and_filters():
    accepted, dropped = validate_actions(
        [
            act("send_money"),
            act("find_official_contact", "종로구청 이름으로 다시 찾아봐요", agency_name="종로구청"),
            act("find_official_contact", agency_name="중복"),
            act("search_welfare", "02-1234-5678 로 문의", keywords=["긴급지원", "123", "a"]),
        ],
        state(impersonation=IMP_NO_OFFICIAL),
    )
    assert accepted == [
        {"tool": "find_official_contact", "agencyName": "종로구청", "reason": "종로구청 이름으로 다시 찾아봐요"},
        {"tool": "search_welfare", "keywords": ["긴급지원"], "reason": "도움 받을 수 있는 제도를 조금 더 찾아봐요"},  # 숫자 섞인 이유 교체
    ]
    assert any("목록 밖 도구 send_money" in d for d in dropped)


@pytest.mark.parametrize(
    "action, results, why",
    [
        (act("find_official_contact", agency_name="종로구청"), {"impersonation": IMP_OFFICIAL}, "지금은 필요 없음"),
        (act("find_official_contact", agency_name="종로구청 02-123"), {"impersonation": IMP_NO_OFFICIAL}, "형식 오류"),
        (act("find_official_contact", agency_name="서울특별시 종로구청장"), {"impersonation": IMP_NO_OFFICIAL}, "이미 찾아본 이름"),
        (act("search_welfare", keywords=[]), {"welfare": WELFARE}, "검색어 없음"),
    ],
)
def test_validate_drops(action, results, why):
    accepted, dropped = validate_actions([action], state(**results))
    assert accepted == [] and why in dropped[0]


def test_validate_max_two_and_welfare_without_prior_result():
    accepted, _ = validate_actions([act("search_welfare")], state())
    assert accepted == [{"tool": "search_welfare", "keywords": [], "reason": "이유"}]  # 계획에 없던 복지 검색은 기본 검색어로


def test_route_after_review():
    assert route_after_review({"followups": [{"tool": "search_welfare"}]}) == "run_followups"
    assert route_after_review({"followups": []}) == "compose"


# ── 수법 검사 조건 (진짜 고지서 오경고 방지) ──
@pytest.mark.parametrize(
    "doc_type, codes, url_official, expected",
    [
        ("fine_notice", ["phone_differs", "insecure", "has_url"], True, False),  # 공식 도메인 http + 부서 번호 → 하지 않음
        ("fine_notice", ["has_url"], True, False),
        ("fine_notice", ["mobile"], False, True),
        ("fine_notice", ["not_official", "has_url"], False, True),
        ("fine_notice", ["insecure", "has_url"], False, True),  # 공식이 아닌 http 주소
        ("suspicious_message", [], False, True),  # 사칭 의심 문자는 항상
    ],
)
def test_needs_scam_check(doc_type, codes, url_official, expected):
    assert needs_scam_check({"docType": doc_type}, codes, url_official) is expected


def test_merge_welfare_keeps_first_and_dedupes():
    more = {"items": [{"name": "긴급복지지원", "summary": "", "reason": "", "url": "u"}, {"name": "분할납부", "summary": "", "reason": "", "url": "u"}, dict(MEMBERSHIP_ITEM)], "usedProfile": True, "fallbackUsed": False}
    merged = merge_welfare(WELFARE, more)
    assert [i["name"] for i in merged["items"]] == ["긴급복지지원", "분할납부", MEMBERSHIP_ITEM["name"]]
    assert merged["usedProfile"] is True and merged["fallbackUsed"] is True


# ── 노드 ──
async def test_review_node_records_decision(monkeypatch):
    class StubLLM:
        async def structured(self, **kwargs):
            assert kwargs["role"] == "reason" and kwargs["node"] == "review"
            assert "02-2148-3362" not in kwargs["user"] and "cartax" not in kwargs["user"]  # 문서의 연락처·주소 값은 보내지 않는다
            return ReviewOut.model_validate(
                {"assessment": "공식 번호를 못 찾아 구청 이름으로 다시 찾아볼게요", "actions": [{"tool": "find_official_contact", "reason": "구청 이름으로 찾아봐요", "keywords": [], "agencyName": "종로구청"}]}
            )

    monkeypatch.setattr(review_node, "get_llm", lambda: StubLLM())
    out = await review_node.review(state(impersonation=IMP_NO_OFFICIAL))
    assert out["reviewed"] is True
    assert out["followups"] == [{"tool": "find_official_contact", "agencyName": "종로구청", "reason": "구청 이름으로 찾아봐요"}]
    assert "추가 실행: find_official_contact('종로구청')" in out["steps"][0]["detail"]


async def test_review_failure_continues_without_followups(monkeypatch):
    from app.llm.base import LLMTimeout

    class Failing:
        async def structured(self, **_):
            raise LLMTimeout("x")

    monkeypatch.setattr(review_node, "get_llm", lambda: Failing())
    out = await review_node.review(state(impersonation=IMP_NO_OFFICIAL))
    assert out["followups"] == [] and "검토 실패" in out["steps"][0]["detail"]


async def test_run_followups_replaces_only_when_found(monkeypatch):
    calls = []

    async def fake_check(document, excerpt, lookup_name=None):
        calls.append(lookup_name)
        found = lookup_name == "종로구청"
        result = IMP_OFFICIAL if found else IMP_NO_OFFICIAL
        return SimpleNamespace(result=result, detail="d")

    monkeypatch.setattr(review_node, "check_impersonation", fake_check)
    s = {**state(impersonation=IMP_NO_OFFICIAL), "followups": [{"tool": "find_official_contact", "agencyName": "종로구청", "reason": "다시 찾아봐요"}]}
    out = await review_node.run_followups(s)
    assert calls == ["종로구청"]
    assert out["tool_results"]["impersonation"]["officialPhone"] == "02-2148-1114"
    assert out["plan"][-1] == {"tool": "check_impersonation", "reason": "결과를 보고 추가: 다시 찾아봐요", "required": False}
    assert out["steps"][0]["id"] == "impersonation_more" and out["steps"][0]["tool"] == "check_impersonation"

    s["followups"] = [{"tool": "find_official_contact", "agencyName": "다른청", "reason": "r"}]
    out = await review_node.run_followups(s)
    assert out["tool_results"]["impersonation"] is IMP_NO_OFFICIAL  # 못 찾았으면 처음 결과 그대로


# ── 그래프 끝까지 (fake 공급자 + 공식 번호 검색만 가짜로) ──
async def test_city_fine_followup_end_to_end(client, monkeypatch):
    from app.tools import impersonation as imp_mod
    from app.tools.web_search import SearchFound

    searched: list[str] = []

    async def fake_search(name, domains, **_):
        searched.append(name)
        if name == "종로구청":
            return SearchFound(phones=["02-2148-1114"], domains=["jongno.go.kr"], source_url="https://www.jongno.go.kr/"), "검색 결과 10건 중 공식 도메인 1건(jongno.go.kr)"
        return None, "공식 도메인(.go.kr·공식 목록) 결과 없음"

    monkeypatch.setattr(imp_mod, "search_official_phone", fake_search)
    r = await client.post("/api/analyze", files={"image": ("a.jpg", jpeg_bytes(), "image/jpeg")}, data={"scenario": "city_fine"})
    events = parse_sse((await client.get(f"/api/analyze/{r.json()['sessionId']}/events")).text)
    name, result = events[-1]
    assert name == "result"
    assert searched == ["서울특별시 종로구", "종로구청"]  # 처음 이름으로 못 찾음 → LLM이 고른 이름으로 다시

    ids = [s["id"] for s in result["steps"]]
    assert ids.index("impersonation") < ids.index("evaluate") < ids.index("review") < ids.index("impersonation_more") < ids.index("compose")

    imp = result["tools"]["impersonation"]
    # 부서 번호라 대표번호와 다르지만, 공식 도메인 http 만으로는 사칭 신호가 아니고 수법 검사도 하지 않는다
    assert imp["status"] == "unknown" and imp["officialPhone"] == "02-2148-1114"
    assert imp["redFlags"] == ["적힌 번호가 공식 번호와 달라요", "보호되지 않는 주소(http)예요"]
    assert result["plan"][-1]["reason"].startswith("결과를 보고 추가:")

    titles = [t["title"] for t in result["todos"]]
    assert titles == ["공식 대표번호로 확인하기", "과태료 내기"]  # 사칭 의심이 아니므로 납부 할 일이 있다
    calls = [a for t in result["todos"] for a in t["actions"] if a["type"] == "call"]
    assert all(a["tel"] == "02-2148-1114" for a in calls)  # 문서의 부서 번호가 아니라 찾은 대표번호
